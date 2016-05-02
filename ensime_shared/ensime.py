import sys
import os
import inspect
import webbrowser

# Ensime shared imports
from ensime_shared.error import Error
from ensime_shared.util import catch, module_exists, Util
from ensime_shared.launcher import EnsimeLauncher
from ensime_shared.debugger import DebuggerClient
from ensime_shared.config import gconfig, feedback

from threading import Thread
from subprocess import Popen, PIPE

import json
import time
import datetime

# Queue depends on python version
if sys.version_info > (3, 0):
    from queue import Queue
else:
    from Queue import Queue

commands = {
    "enerror_matcher": "matchadd('EnErrorStyle', '\\%{}l\\%>{}c\\%<{}c')",
    "highlight_enerror": "highlight EnErrorStyle ctermbg=red gui=underline",
    "exists_enerrorstyle": "exists('g:EnErrorStyle')",
    "set_enerrorstyle": "let g:EnErrorStyle='EnError'",
    # http://vim.wikia.com/wiki/Timer_to_execute_commands_periodically
    # Set to low values to improve responsiveness
    "set_updatetime": "set updatetime=1000",
    "current_file": "expand('%:p')",
    "until_last_char_word": "normal e",
    "until_first_char_word": "normal b",
    # Avoid to trigger requests to server when writing
    "write_file": "noautocmd w",
    "input_save": "call inputsave()",
    "input_restore": "call inputrestore()",
    "set_input": "let user_input = input('{}')",
    "get_input": "user_input",
    "edit_file": "edit {}",
    "reload_file": "checktime",
    "display_message": "echo \"{}\"",
    "split_window": "split {}",
    "vert_split_window": "vsplit {}",
    "new_vertical_window": "{}vnew {}",
    "new_vertical_scratch": "{}vnew {} | setlocal nobuflisted buftype=nofile bufhidden=wipe noswapfile",
    "doautocmd_bufleave": "doautocmd BufLeave",
    "doautocmd_bufreadenter": "doautocmd BufReadPre,BufRead,BufEnter",
    "filetype": "&filetype",
    "set_filetype": "set filetype={}",
    "go_to_char": "goto {}",
    "set_ensime_completion": "set omnifunc=EnCompleteFunc",
    "set_quickfix_list": "call setqflist({}, '')",
    "open_quickfix": "copen",
    "disable_plugin": "set runtimepath-={}",
    "runtimepath": "&runtimepath",
    "syntastic_available": 'exists("g:SyntasticRegistry")',
    "syntastic_enable": "if exists('g:SyntasticRegistry') | let &runtimepath .= ',' . {!r} | endif",
    "syntastic_append_notes": 'if ! exists("b:ensime_scala_notes") | let b:ensime_scala_notes = [] | endif | let b:ensime_scala_notes += {}',
    "syntastic_reset_notes": 'let b:ensime_scala_notes = []',
    "syntastic_show_notes": "silent! SyntasticCheck ensime",
    "get_cursor_word": 'expand("<cword>")',
    "select_item_list": 'inputlist({})',
    "append_line": 'call append({}, {!r})'
}


class EnsimeClient(DebuggerClient, object):
    """Represents an Ensime client per ensime configuration path."""

    def __init__(self, vim, launcher, config_path):
        def setup_vim():
            """Set up vim and execute global commands."""
            self.vim = vim
            if not int(self.vim_eval("exists_enerrorstyle")):
                self.vim_command("set_enerrorstyle")
            self.vim_command("highlight_enerror")
            self.vim_command("set_updatetime")
            self.vim_command("set_ensime_completion")
            self.vim.command("autocmd FileType package_info nnoremap <buffer> <Space> :call EnPackageDecl()<CR>")
            self.vim.command("autocmd FileType package_info  setlocal splitright")

        def setup_logger_and_paths():
            """Set up paths and logger."""
            osp = os.path
            self.config_path = osp.abspath(config_path)
            config_dirname = osp.dirname(self.config_path)
            self.ensime_cache = osp.join(config_dirname, ".ensime_cache")
            self.log_dir = self.ensime_cache \
                if osp.isdir(self.ensime_cache) else "/tmp/"
            self.log_file = os.path.join(self.log_dir, "ensime-vim.log")

        def fetch_runtime_paths():
            """Fetch all the runtime paths of ensime-vim plugin."""
            paths = self.vim_eval("runtimepath")
            tag = "ensime-vim"
            ps = [p for p in paths.split(',') if tag in p]
            home = os.environ.get("HOME")
            if home:
                ps = map(lambda s: s.replace(home, "~"), ps)
            return ps

        setup_logger_and_paths()
        setup_vim()
        self.log("__init__: in")

        self.ws = None
        self.ensime = None
        self.launcher = launcher
        self.ensime_server = None

        self.call_id = 0
        self.call_options = {}
        self.refactor_id = 1
        self.refactorings = {}
        self.receive_callbacks = {}

        self.matches = []
        self.errors = []
        self.queue = Queue()
        self.suggestions = None
        self.completion_timeout = 10  # seconds
        self.completion_started = False
        self.en_format_source_id = None
        self.enable_fulltype = False
        self.toggle_teardown = True
        self.connection_attempts = 0
        self.tmp_diff_folder = "/tmp/ensime-vim/diffs/"
        Util.mkdir_p(self.tmp_diff_folder)

        # Set the runtime path here in case we need
        # to disable the plugin. It needs to be done
        # beforehand since vim.eval is not threadsafe
        self.runtime_paths = fetch_runtime_paths()

        # By default, don't connect to server more than once
        self.number_try_connection = 1

        self.debug_thread_id = None
        self.running = True
        Thread(target=self.queue_poll, args=()).start()

        self.handlers = {}
        self.register_responses_handlers()

        self.websocket_exists = module_exists("websocket")
        if not self.websocket_exists:
            self.tell_module_missing("websocket-client")

    def log(self, what):
        """Log `what` in a file at the .ensime_cache folder or /tmp."""
        with open(self.log_file, "a") as f:
            now = datetime.datetime.now()
            tm = now.strftime("%Y-%m-%d %H:%M:%S.%f")
            f.write("{}: {}\n".format(tm, what))

    def queue_poll(self, sleep_t=0.5):
        """Put new messages on the queue as they arrive. Blocking in a thread.

        Value of sleep is low to improve responsiveness.
        """
        connection_alive = True
        while self.running:
            if self.ws:
                def logger_and_close(m):
                    self.log("Websocket exception: {}".format(m))
                    if not self.running:
                        # Tear down has been invoked
                        # Prepare to exit the program
                        connection_alive = False
                    else:
                        if not self.number_try_connection:
                            # Stop everything and disable plugin
                            self.teardown()
                            self.disable_plugin()

                # WebSocket exception may happen
                with catch(Exception, logger_and_close):
                    result = self.ws.recv()
                    self.queue.put(result)

            if connection_alive:
                time.sleep(sleep_t)

    def on_receive(self, name, callback):
        """Executed when a response is received from the server."""
        self.log("on_receive: {}".format(callback))
        self.receive_callbacks[name] = callback

    def vim_command(self, key):
        """Execute a vim cached command from the commands dictionary."""
        vim_cmd = commands[key]
        self.vim.command(vim_cmd)

    def vim_eval(self, key):
        """Eval a vim cached expression from the commands dictionary."""
        vim_cmd = commands[key]
        return self.vim.eval(vim_cmd)

    def setup(self, quiet=False, create_classpath=False):
        """Check the classpath and connect to the server if necessary."""
        def lazy_initialize_ensime():
            if not self.ensime:
                called_by = inspect.stack()[4][3]
                self.log(str(inspect.stack()))
                self.log("setup({}, {}) called by {}()"
                         .format(quiet, create_classpath, called_by))
                no_classpath = self.launcher.no_classpath_file(
                    self.config_path)
                if not create_classpath and no_classpath:
                    if not quiet:
                        self.message("warn_classpath")
                    return False
                self.ensime = self.launcher.launch(self.config_path)
            return bool(self.ensime)

        def ready_to_connect():
            if not self.websocket_exists:
                return False
            if not self.ws and self.ensime.is_ready():
                self.connect_ensime_server()
            return True

        # True if ensime is up and connection is ok, otherwise False
        return self.running and lazy_initialize_ensime() and ready_to_connect()

    def tell_module_missing(self, name):
        """Warn users that a module is not available in their machines."""
        msg = feedback["module_missing"]
        self.raw_message(msg.format(name, name))

    def threadsafe_vim(self, command):
        """Threadsafe call if neovim, normal if vim."""
        def normal_vim(e):
            self.vim.command(command)
        with catch(Exception, normal_vim):
            self.vim.session.threadsafe_call(command)

    def disable_plugin(self):
        """Disable plugin temporarily, including also related plugins."""
        self.log("disable_plugin: in")

        for path in self.runtime_paths:
            self.log(path)
            disable = commands["disable_plugin"].format(path)
            self.threadsafe_vim(disable)

        warning = "A WS exception happened, 'ensime-vim' has been disabled. " +\
            "For more information, have a look at the logs in `.ensime_cache`"
        display_msg = commands["display_message"].format(warning)
        self.threadsafe_vim(display_msg)

    def send(self, msg):
        """Send something to the ensime server."""
        def reconnect(e):
            self.log("send error: {}, reconnecting...".format(e))
            self.connect_ensime_server()
            if self.ws:
                self.ws.send(msg + "\n")

        self.log("send: in")
        if self.running and self.ws:
            with catch(Exception, reconnect):
                self.log("send: {}".format(msg))
                self.ws.send(msg + "\n")

    def connect_ensime_server(self):
        """Start initial connection with the server."""
        self.log("connect_ensime_server: in")

        def disable_completely(e):
            if e:
                self.log("connection error: {}".format(e))
            self.shutdown_server()
            self.disable_plugin()

        if self.running and self.number_try_connection:
            self.number_try_connection -= 1
            if not self.ensime_server:
                port = self.ensime.http_port()
                self.ensime_server = gconfig["ensime_server"].format(port)
            with catch(Exception, disable_completely):
                from websocket import create_connection
                self.ws = create_connection(self.ensime_server)
            if self.ws:
                self.send_request({"typehint": "ConnectionInfoReq"})
        else:
            # If it hits this, number_try_connection is 0
            disable_completely(None)

    def shutdown_server(self):
        """Shut down server if it is alive."""
        if self.ensime and self.toggle_teardown:
            self.ensime.stop()

    def teardown(self):
        """Tear down the server or keep it alive."""
        self.log("teardown: in")
        self.running = False
        self.shutdown_server()

    def cursor(self):
        """Return the row and col of the current buffer."""
        return self.vim.current.window.cursor

    def set_cursor(self, row, col):
        """Set cursor at a given row and col in a buffer."""
        self.log("set_cursor: {}".format((row, col)))
        self.vim.current.window.cursor = (row, col)

    def width(self):
        """Return the width of the window."""
        return self.vim.current.window.width

    def path(self):
        """Return the current path."""
        self.log("path: in")
        return self.vim.current.buffer.name

    def start_end_pos(self):
        """Return start and end positions of the cursor respectively."""
        self.vim_command("until_last_char_word")
        e = self.cursor()
        self.vim_command("until_first_char_word")
        b = self.cursor()
        return b, e

    def send_at_position(self, what, where="range"):
        self.log("send_at_position: in")
        b, e = self.start_end_pos()
        bcol, ecol = b[1], e[1]
        s, line = ecol - bcol, b[0]
        self.send_at_point_req(what, self.path(), line, bcol + 1, s, where)

    def set_position(self, decl_pos):
        """Set position from declPos data."""
        if decl_pos["typehint"] == "LineSourcePosition":
            self.set_cursor(decl_pos['line'], 0)
        else:  # OffsetSourcePosition
            point = decl_pos["offset"]
            cmd = commands["go_to_char"].format(str(point + 1))
            self.vim.command(cmd)

    def get_position(self, row, col):
        """Get char position in all the text from row and column."""
        result = col
        self.log("{} {}".format(row, col))
        lines = self.vim.current.buffer[:row - 1]
        result += sum([len(l) + 1 for l in lines])
        self.log("{}".format(result))
        return result

    def get_file_content(self):
        """Get content of file."""
        return "\n".join(self.vim.current.buffer)

    def get_file_info(self):
        """Returns filename and content of a file."""
        return {"file": self.path(),
                "contents": self.get_file_content()}

    def ask_input(self, message='input: '):
        """Ask input to vim and display info string."""
        self.vim_command("input_save")
        # Format to display message with input()
        cmd = commands["set_input"]
        self.vim.command(cmd.format(message))
        self.vim_command("input_restore")
        return self.vim_eval("get_input")

    def raw_message(self, m):
        """Display a message in the vim status line."""
        self.log("message: in")
        self.log(m)
        cmd = commands["display_message"]
        escaped = m.replace('"', '\\"')
        self.vim.command(cmd.format(escaped))

    def message(self, key):
        """Display a message already defined in `feedback`."""
        msg = feedback[key]
        self.raw_message(msg)

    def register_responses_handlers(self):
        """Register handlers for responses from the server.

        A handler must accept only one parameter: `payload`.
        """
        self.handlers["SymbolInfo"] = self.handle_symbol_info
        f_indexer = lambda ci, p: self.message("indexer_ready")
        self.handlers["IndexerReadyEvent"] = f_indexer
        f_indexer = lambda ci, p: self.message("analyzer_ready")
        self.handlers["AnalyzerReadyEvent"] = f_indexer
        self.handlers["NewScalaNotesEvent"] = (self.handle_new_scala_notes_event_with_syntastic
                if self.vim_eval('syntastic_available') else self.handle_new_scala_notes_event)
        self.handlers["BasicTypeInfo"] = self.show_type
        self.handlers["ArrowTypeInfo"] = self.show_ftype
        self.handlers["StringResponse"] = self.handle_string_response
        self.handlers["CompletionInfoList"] = self.handle_completion_info_list
        self.handlers["TypeInspectInfo"] = self.handle_type_inspect
        self.handlers["SymbolSearchResults"] = self.handle_symbol_search
        self.handlers["DebugOutputEvent"] = self.handle_debug_output
        self.handlers["DebugBreakEvent"] = self.handle_debug_break
        self.handlers["DebugBacktrace"] = self.handle_debug_backtrace
        self.handlers["DebugVmError"] = self.handle_debug_vm_error
        self.handlers["RefactorDiffEffect"] = self.apply_refactor
        self.handlers["ImportSuggestions"] = self.handle_import_suggestions
        self.handlers["PackageInfo"] = self.handle_package_info

    def handle_debug_vm_error(self, call_id, payload):
        self.vim.command(commands['display_message'].format("Error. Check ensime-vim log for details."))

    def handle_import_suggestions(self, call_id, payload):
        imports = list(sorted(set(suggestion['name'].replace('$', '.') for suggestions in payload['symLists'] for suggestion in suggestions)))
        if imports:
            chosen_import = int(self.vim.eval(commands['select_item_list'].format(json.dumps(
                ["Select class to import:"] + ["{}. {}".format(num + 1, imp) for (num, imp) in enumerate(imports)]))))

            if chosen_import > 0:
                self.add_import(imports[chosen_import - 1])

        else:
            self.vim.command(commands['display_message'].format("No import suggestions found"))

    def handle_package_info(self, call_id, payload):
        package = payload["fullName"]
        # Create a new buffer 45 columns wide
        def add(member, indentLevel):
            indent = "  " * indentLevel
            t = member["declAs"]["typehint"] if member["typehint"] == "BasicTypeInfo" else ""
            line = "{}{}: {}".format(indent, t, member["name"])
            self.vim.command(commands["append_line"].format("\'$\'", str(line)))
            if indentLevel < 4:
                for m in member["members"]:
                    add(m, indentLevel + 1)

        cmd = commands["new_vertical_scratch"].format(str(45),"package_info")
        self.vim.command(cmd)
        self.vim.command(commands["set_filetype"].format("package_info"))
        self.vim.command(commands["append_line"].format("\'$\'", str(package)))
        for member in payload["members"]:
            add(member, 1)

    def open_decl_for_inspector_symbol(self):
        self.log("open_decl_for_inspector_symbol: in")

        def indent(ln):
           n = 0
           for c in ln:
               if c == ' ':
                   n += 1
               else:
                   break
           return n/2

        row,col = self.cursor()
        lines = self.vim.current.buffer[:row]
        i = indent(lines[-1])
        fqn = [lines[-1].split()[-1]]

        for ln in reversed(lines):
            if indent(ln) == i -1:
                i -= 1
                fqn.insert(0, ln.split()[-1])

        symbolName = ".".join(fqn)
        self.symbol_by_name([symbolName])
        self.unqueue(should_wait=True)

    def to_quickfix_item(self, file_name, line_number, message, tpe):
        return { "filename" : file_name,
         "lnum"     : line_number,
         "text"     : message,
         "type"     : tpe }

    def symbol_by_name(self, args, range=None):
        self.log("symbol_by_name: in")
        if not args:
            msg = commands["display_message"].format("Must provide a fully qualifed symbol name")
            return

        self.call_options[self.call_id] = {"split": True,
                                           "vert": True ,
                                           "open_definition": True }
        fqn = args[0]
        req = {
            "typehint": "SymbolByNameReq",
            "typeFullName": fqn
        }
        if len(args) == 2:
            req["memberName"] = args[1]
        self.send_request(req)

    def write_quickfix_list(self, qf_list):
        cmd = commands["set_quickfix_list"].format(str(qf_list))
        self.vim.command(cmd)
        self.vim_command("open_quickfix")

    def handle_symbol_search(self, call_id, payload):
        """Handler for symbol search results"""
        self.log(payload)
        syms = payload["syms"]
        qfList = []
        for sym in syms:
            p = sym.get("pos")
            if p:
                item = self.to_quickfix_item(str(p["file"]),
                                            p["line"],
                                            str(sym["name"]),
                                            "info")
                qfList.append(item)
        self.write_quickfix_list(qfList)

    def handle_symbol_info(self, call_id, payload):
        """Handler for response `SymbolInfo`."""
        warn = lambda e: self.message("unknown_symbol")
        with catch(KeyError, warn):
            decl_pos = payload["declPos"]
            f = decl_pos.get("file")
            self.log(str(self.call_options[call_id]))
            display = self.call_options[call_id].get("display")
            if display and f:
                self.vim.command(commands["display_message"].format(f))

            open_definition = self.call_options[call_id].get("open_definition")
            if open_definition and f:
                self.clean_errors()
                self.vim_command("doautocmd_bufleave")
                split = self.call_options[call_id].get("split")
                vert = self.call_options[call_id].get("vert")
                key = ""
                if split:
                    key = "vert_split_window" if vert else "split_window"
                else:
                    key = "edit_file"
                self.vim.command(commands[key].format(f))
                self.vim_command("doautocmd_bufreadenter")
                self.set_position(decl_pos)
                del self.call_options[call_id]


    def handle_new_scala_notes_event_with_syntastic(self, call_id, payload):
        """Syntastic specific handler for response `NewScalaNotesEvent`."""

        def is_note_correct(note):
            return note['beg'] != -1 and note['end'] != -1

        current_file = os.path.abspath(self.path())
        loclist = list({
                'bufnr': self.vim.current.buffer.number,
                'lnum': note['line'],
                'col': note['col'],
                'text': note['msg'],
                'len': note['end'] - note['beg'] + 1,
                'type': note['severity']['typehint'][4:5],
                'valid': 1
            } for note in payload["notes"] \
                    if current_file == os.path.abspath(note['file']) and \
                        is_note_correct(note)
        )

        json_list = json.dumps(loclist)
        if json_list:
            self.vim.command(commands['syntastic_append_notes'].format(json_list))
            self.vim_command('syntastic_show_notes')

    def handle_new_scala_notes_event(self, call_id, payload):
        """Handler for response `NewScalaNotesEvent`."""
        current_file = os.path.abspath(self.path())
        for note in payload["notes"]:
            l = note["line"]
            c = note["col"] - 1
            e = note["col"] + (note["end"] - note["beg"] + 1)

            if current_file == os.path.abspath(note["file"]):
                self.errors.append(Error(note["file"], note["msg"], l, c, e))
                matcher = commands["enerror_matcher"].format(l, c, e)
                match = self.vim.eval(matcher)
                add_match_msg = "adding match {} at line {} column {} error {}"
                self.log(add_match_msg.format(match, l, c, e))
                self.matches.append(match)

    def handle_string_response(self, call_id, payload):
        """Handler for response `StringResponse`.

        This is the response for the following requests:
          1. `DocUriAtPointReq` or `DocUriForSymbolReq`
          2. `DebugToStringReq`
          3. `FormatOneSourceReq`
        """
        self.log(str(payload))
        self.handle_doc_uri(call_id, payload)

    def handle_doc_uri(self, call_id, payload):
        """Handler for responses of Doc URIs."""
        if not self.en_format_source_id:
            self.log("handle_string_response: received doc path")
            port = self.ensime.http_port()
            url = gconfig["localhost"].format(port, payload["text"])
            browse_enabled = self.call_options[call_id].get("browse")

            if browse_enabled:
                log_msg = "handle_string_response: browsing doc path {}"
                self.log(log_msg.format(url))
                try:
                    if webbrowser.open(url):
                        self.log("opened {}".format(url))
                except webbrowser.Error, e:
                    log_msg = "handle_string_response: webbrowser error: {}"
                    self.log(log_msg.format(e))
                    self.raw_message(feedback["manual_doc"].format(url))

            del self.call_options[call_id]
        else:
            self.vim.current.buffer[:] = \
                [line.encode('utf-8') for line in payload["text"].split("\n")]
            self.en_format_source_id = None

    def handle_completion_info_list(self, call_id, payload):
        """Handler for a completion response."""
        completions = payload["completions"]
        self.log("handle_completion_info_list: in")
        self.suggestions = [self.completion_to_suggest(c) for c in completions]
        self.log("handle_completion_info_list: {}".format(self.suggestions))

    def handle_type_inspect(self, call_id, payload):
        """Handler for responses `TypeInspectInfo`."""
        interfaces = payload.get("interfaces")
        ts = [i["type"]["name"] for i in interfaces]
        prefix = "( " + ", ".join(ts) + " ) => "
        self.raw_message(prefix + payload["type"]["fullName"])

    def show_type(self, call_id, payload):
        """Show type of a variable or scala type."""
        tpe = payload["fullName"]
        args = payload["typeArgs"]

        if args:
            if len(args) > 1:
                tpes = [x["name"] for x in args]
                tpe += self.concat_tparams(tpes)
            else:  # is 1
                tpe += "[{}]".format(args[0]["fullName"])

        self.log(feedback["displayed_type"].format(tpe))
        self.raw_message(tpe)

    def show_ftype(self, call_id, payload):
        """Show the type of a function."""
        self.log("entering")
        rtype = payload["resultType"]
        lparams = payload["paramSections"]
        tpe = ""
        tname = "fullName" if self.enable_fulltype else "name"

        if rtype and lparams:
            for l in lparams:
                tpe += "("
                f = lambda x: (x[0], x[1][tname])
                params = list(map(f, l["params"]))
                tpe += self.concat_params(params)
                tpe += ")"
            tpe += " => {}".format(rtype["fullName"])

        self.log(feedback["displayed_type"].format(tpe))
        self.raw_message(tpe)

    def handle_incoming_response(self, call_id, payload):
        """Get a registered handler for a given response and execute it."""
        self.log("handle_incoming_response: in {}".format(payload))
        typehint = payload["typehint"]
        handler = self.handlers.get(typehint)
        if handler:
            handler(call_id, payload)
        else:
            self.log(feedback["unhandled_response"].format(payload))

    def complete(self, row, col):
        self.log("complete: in")
        pos = self.get_position(row, col)
        self.send_request({"point": pos, "maxResults": 100,
                           "typehint": "CompletionsReq",
                           "caseSens": True,
                           "fileInfo": self.get_file_info(),
                           "reload": False})

    def send_at_point_req(self, what, path, row, col, size, where="range"):
        """Ask the server to perform an operation at a given position."""
        i = self.get_position(row, col)
        self.send_request(
            {"typehint": what + "AtPointReq",
             "file": path,
             where: {"from": i, "to": i + size}})

    def do_toggle_teardown(self, args, range=None):
        self.log("do_toggle_teardown: in")
        self.toggle_teardown = not self.toggle_teardown

    def type_check_cmd(self, args, range=None):
        self.log("type_check_cmd: in")
        self.type_check("")

    def en_classpath(self, args, range=None):
        self.log("en_classpath: in")

    def format_source(self, args, range=None):
        self.log("type_check_cmd: in")
        req = {"typehint": "FormatOneSourceReq",
               "file": self.get_file_info()}
        self.en_format_source_id = self.send_request(req)

    def type(self, args, range=None):
        self.log("type: in")
        self.send_at_position("Type")

    def toggle_fulltype(self, args, range=None):
        self.log("toggle_fulltype: in")
        self.enable_fulltype = not self.enable_fulltype

    def symbol_at_point_req(self, open_definition, display=False):
        opts = self.call_options.get(self.call_id)
        if opts:
            opts["open_definition"] = open_definition
            opts["display"] = display
        else:
            self.call_options[self.call_id] = {
                "open_definition": open_definition,
                "display": display
            }
        pos = self.get_position(self.cursor()[0], self.cursor()[1])
        self.send_request({
            "point": pos + 1,
            "typehint": "SymbolAtPointReq",
            "file": self.path()})

    def inspect_package(self, args):
        pkg = None
        if not args:
            pkg = Util.extract_package_name(self.vim.current.buffer)
            msg = commands["display_message"].format("Using Currently Focused Package")
            self.vim.command(msg)
        else:
            pkg = args[0]
        self.send_request({
            "typehint": "InspectPackageByPathReq",
            "path": pkg
        })

    def open_declaration(self, args, range=None):
        self.log("open_declaration: in")
        self.symbol_at_point_req(True)

    def open_declaration_split(self, args, range=None):
        self.log("open_declaration: in")
        if "v" in args:
            self.call_options[self.call_id] = {"split": True, "vert": True}
        else:
            self.call_options[self.call_id] = {"split": True }

        self.symbol_at_point_req(True)

    def symbol(self, args, range=None):
        self.log("symbol: in")
        self.symbol_at_point_req(False, True)

    def suggest_import(self, args, range=None):
        self.log("inspect_type: in")
        pos = self.get_position(self.cursor()[0], self.cursor()[1])
        word = self.vim_eval('get_cursor_word')
        req = {"point": pos,
               "maxResults": 10,
               "names": [word],
               "typehint": "ImportSuggestionsReq",
               "file": self.path()}
        self.send_request(req)

    def inspect_type(self, args, range=None):
        self.log("inspect_type: in")
        pos = self.get_position(self.cursor()[0], self.cursor()[1])
        self.send_request({
            "point": pos,
            "typehint": "InspectTypeAtPointReq",
            "file": self.path(),
            "range": {"from": pos, "to": pos}})

    def doc_uri(self, args, range=None):
        """Request doc of whatever at cursor."""
        self.log("doc_uri: in")
        self.send_at_position("DocUri", "point")

    def doc_browse(self, args, range=None):
        """Browse doc of whatever at cursor."""
        self.log("browse: in")
        self.call_options[self.call_id] = {"browse": True}
        self.doc_uri(args, range=None)

    def rename(self, new_name, range=None):
        """Request a rename to the server."""
        self.log("rename: in")
        if not new_name:
            new_name = self.ask_input("Rename to: ")
        self.vim_command("write_file")
        b, e = self.start_end_pos()
        current_file = self.path()
        self.raw_message(current_file)
        self.send_refactor_request(
            "RefactorReq",
            {
                "typehint": "RenameRefactorDesc",
                "newName": new_name,
                "start": self.get_position(b[0], b[1]),
                "end": self.get_position(e[0], e[1]) + 1,
                "file": current_file,
            },
            {"interactive": False}
        )

    def inlineLocal(self, range=None):
        """Perform a local inline"""
        self.log("inline: in")
        self.vim_command("write_file")
        b, e = self.start_end_pos()
        current_file = self.path()
        self.raw_message(current_file)
        self.send_refactor_request(
            "RefactorReq",
            {
                "typehint": "InlineLocalRefactorDesc",
                "start": self.get_position(b[0], b[1]),
                "end": self.get_position(e[0], e[1]) + 1,
                "file": current_file,
            },
            { "interactive": False }
        )

    def organize_imports(self, args, range=None):
        self.vim_command("write_file")
        current_file = self.path()
        self.send_refactor_request(
            "RefactorReq",
            {
                "typehint": "OrganiseImportsRefactorDesc",
                "file": current_file,
            },
            {"interactive": False}
        )

    def add_import(self, name, range=None):
        if not name:
            name = self.ask_input("Qualified name to import: ")
        self.vim_command("write_file")
        current_file = self.path()
        self.send_refactor_request(
            "RefactorReq",
            {
                "typehint": "AddImportRefactorDesc",
                "file": current_file,
                "qualifiedName": name
            },
            {"interactive": False}
        )

    def symbol_search(self, search_terms):
        """Search for symbols matching a set of keywords"""
        if not rename_to:
            msg = commands["display_message"].format("Must provide symbols to search for")
            self.vim.command(msg)
            return
        self.log("symbol_search: in")
        terms = search_terms.split()
        req = {
            "typehint": "PublicSymbolSearchReq",
            "keywords": terms,
            "maxResults": 25
        }
        self.send_request(req)

    def send_refactor_request(self, ref_type, ref_params, ref_options):
        """Send a refactor request to the Ensime server.

        The `ref_params` field will always have a field `type`.
        """
        request = {
            "typehint": ref_type,
            "procId": self.refactor_id,
            "params": ref_params
        }
        f = ref_params["file"]
        self.refactorings[self.refactor_id] = f
        self.refactor_id += 1
        request.update(ref_options)
        self.send_request(request)

    def apply_refactor(self, call_id, payload):
        """Apply a refactor depending on its type."""
        if payload["refactorType"]["typehint"] in ["Rename", "InlineLocal", "AddImport", "OrganizeImports"]:
            diff_filepath = payload["diff"]
            path = self.path()
            bname = os.path.basename(path)
            target = os.path.join(self.tmp_diff_folder, bname)
            reject_arg = "--reject-file={}.rej".format(target)
            backup_pref = "--prefix={}".format(self.tmp_diff_folder)
            # Patch utility is prepackaged or installed with vim
            cmd = ["patch", reject_arg, backup_pref, path, diff_filepath]
            failed = Popen(cmd, stdout=PIPE, stderr=PIPE).wait()
            if failed:
                self.message("failed_refactoring")
            # Update file and reload highlighting
            cmd = commands["edit_file"].format(self.path())
            self.vim.command(cmd)
            self.vim_command("doautocmd_bufreadenter")

    def concat_params(self, params):
        """Return list of params from list of (pname, ptype)."""
        name_and_types = [": ".join(p) for p in params]
        return ", ".join(name_and_types)

    def concat_tparams(self, tparams):
        """Return a valid signature from a list of type parameters."""
        types = [", ".join(p) for p in tparams]
        return "[{}]".format(types)

    def formatted_completion_type(self, completion):
        f_result = completion["typeSig"]["result"]
        if not completion["isCallable"]:
            # It's a raw type
            return f_result
        elif len(completion["typeSig"]["sections"]) == 0:
            return f_result

        # It's a function type
        f_params = completion["typeSig"]["sections"][0]
        ps = self.concat_params(f_params) if f_params else ""
        return "({}) => {}".format(ps, f_result)

    def completion_to_suggest(self, completion):
        """Convert from a completion to a suggestion."""
        res = {"word": completion["name"],
               "menu": "[scala]",
               "kind": self.formatted_completion_type(completion)}
        self.log("completion_to_suggest: {}".format(res))
        return res

    def send_request(self, request):
        """Send a request to the server."""
        self.log("send_request: in")
        self.send(json.dumps({"callId": self.call_id, "req": request}))
        call_id = self.call_id
        self.call_id += 1
        return call_id

    def clean_errors(self):
        """Clean errors and unhighlight them in vim."""
        self.vim.eval("clearmatches()")
        self.vim_command('syntastic_reset_notes')
        self.matches = []
        self.errors = []

    def buffer_leave(self, filename):
        """User is changing of buffer."""
        self.log("buffer_leave: {}".format(filename))
        self.clean_errors()

    def type_check(self, filename):
        """Update type checking when user saves buffer."""
        self.log("type_check: in")
        self.send_request(
            {"typehint": "TypecheckFilesReq",
             "files": [self.path()]})
        self.clean_errors()

    def unqueue(self, timeout=10, should_wait=False):
        """Unqueue all the received ensime responses for a given file."""
        def trigger_callbacks(_json):
            for name in self.receive_callbacks:
                self.log("launching callback: {}".format(name))
                self.receive_callbacks[name](self, _json["payload"])

        start, now = time.time(), time.time()
        wait = self.queue.empty() and should_wait
        while (not self.queue.empty() or wait) and (now - start) < timeout:
            if wait and self.queue.empty():
                time.sleep(0.25)
                now = time.time()
            else:
                result = self.queue.get(False)
                self.log("unqueue: result received {}".format(str(result)))
                if result and result != "nil":
                    wait = None
                    # Restart timeout
                    start, now = time.time(), time.time()
                    _json = json.loads(result)
                    # Watch out, it may not have callId
                    call_id = _json.get("callId")
                    if _json["payload"]:
                        trigger_callbacks(_json)
                        self.handle_incoming_response(call_id, _json["payload"])
                else:
                    self.log("unqueue: nil or None received")

        if (now - start) >= timeout:
            self.log("unqueue: no reply from server for {}s"
                     .format(timeout))

    def unqueue_and_display(self, filename):
        """Unqueue messages and give feedback to user (if necessary)."""
        if self.running and self.ws:
            self.lazy_display_error(filename)
            self.unqueue()

    def lazy_display_error(self, filename):
        """Display error when user is over it."""
        error = self.get_error_at(self.cursor())
        if error:
            report = error.get_truncated_message(
                self.cursor(), self.width() - 1)
            self.raw_message(report)

    def on_cursor_hold(self, filename):
        """Handler for event CursorHold."""
        if self.connection_attempts < 10:
            # Trick to connect ASAP when
            # plugin is  started without
            # user interaction (CursorMove)
            self.setup(True, False)
            self.connection_attempts += 1
        self.unqueue_and_display(filename)
        # Make sure any plugin overrides this
        self.vim_command("set_updatetime")
        # Keys with no effect, just retrigger CursorHold
        self.vim.command('call feedkeys("f\e")')

    def on_cursor_move(self, filename):
        """Handler for event CursorMoved."""
        self.setup(True, False)
        self.unqueue_and_display(filename)

    def vim_enter(self, filename):
        """Set up EnsimeClient when vim enters.

        This is useful to start the EnsimeLauncher as soon as possible."""
        success = self.setup(True, False)
        if success:
            self.message("start_message")

    def get_error_at(self, cursor):
        """Return error at position `cursor`."""
        for error in self.errors:
            if error.includes(self.vim.eval("expand('%:p')"), cursor):
                return error
        return None

    def complete_func(self, findstart, base):
        """Handle omni completion."""
        def detect_row_column_start():
            row, col = self.cursor()
            start = col
            line = self.vim.current.line
            while start > 0 and line[start - 1] not in " .":
                start -= 1
            # Start should be 1 when startcol is zero
            return row, col, start if start else 1

        self.log("complete_func: in {} {}".format(findstart, base))
        if str(findstart) == "1":
            row, col, startcol = detect_row_column_start()

            # Make request to get response ASAP
            self.complete(row, col)
            self.completion_started = True

            # We always allow autocompletion, even with empty seeds
            return startcol
        else:
            result = []
            # Only handle snd invocation if fst has already been done
            if self.completion_started:
                self.vim_command("until_first_char_word")
                # Unqueing messages until we get suggestions
                self.unqueue(timeout=self.completion_timeout, should_wait=True)
                suggestions = self.suggestions or []
                self.log("complete_func: suggests in {}".format(suggestions))
                for m in suggestions:
                    result.append(m)
                self.suggestions = None
                self.completion_started = False
            return result


def execute_with_client(quiet=False,
                        create_classpath=False,
                        create_client=True):
    """Decorator that gets a client and performs an operation on it."""
    def wrapper(f):

        def wrapper2(self, *args, **kwargs):
            client = self.current_client(
                quiet=quiet,
                create_classpath=create_classpath,
                create_client=create_client)
            if client and client.running:
                return f(self, client, *args, **kwargs)
        return wrapper2

    return wrapper


class Ensime(object):

    def __init__(self, vim):
        self.vim = vim
        # Map ensime configs to a ensime clients
        self.clients = {}
        self.launcher = EnsimeLauncher(vim)
        self.init_integrations()

    def init_integrations(self):
        syntastic_runtime = os.path.abspath(
            os.path.join(os.path.dirname(__file__),
                os.path.pardir,
                'plugin_integrations',
                'syntastic'))
        self.vim.command(commands['syntastic_enable'].format(syntastic_runtime))

    def client_keys(self):
        return self.clients.keys()

    def client_status(self, config_path):
        """Get the client status of a given project."""
        c = self.client_for(config_path)
        status = "stopped"
        if not c or not c.ensime:
            status = 'unloaded'
        elif c.ensime.is_ready():
            status = 'ready'
        elif c.ensime.is_running():
            status = 'startup'
        elif c.ensime.aborted():
            status = 'aborted'
        return status

    def teardown(self):
        """Say goodbye..."""
        for c in self.clients.values():
            c.teardown()

    def current_client(self, quiet, create_classpath, create_client):
        """Return the current client for a given project."""
        # Use current_file command because we cannot access self.vim
        current_file_cmd = commands["current_file"]
        current_file = self.vim.eval(current_file_cmd)
        config_path = self.find_config_path(current_file)
        if config_path:
            return self.client_for(
                config_path,
                quiet=quiet,
                create_classpath=create_classpath,
                create_client=create_client)

    def find_config_path(self, path):
        """Recursive function that finds the ensime config filepath."""
        abs_path = os.path.abspath(path)
        config_path = os.path.join(abs_path, '.ensime')

        if abs_path == os.path.abspath('/'):
            config_path = None
        elif not os.path.isfile(config_path):
            dirname = os.path.dirname(abs_path)
            config_path = self.find_config_path(dirname)

        return config_path

    def client_for(self, config_path, quiet=False, create_classpath=False,
                   create_client=False):
        """Get a cached client for a project, otherwise create one."""
        client = None
        abs_path = os.path.abspath(config_path)
        if abs_path in self.clients:
            client = self.clients[abs_path]
        elif create_client:
            client = EnsimeClient(self.vim, self.launcher, config_path)
            if client.setup(quiet=quiet, create_classpath=create_classpath):
                self.clients[abs_path] = client
        return client

    def is_scala_file(self):
        cmd = commands["filetype"]
        return self.vim.eval(cmd) == 'scala'

    @execute_with_client()
    def com_en_toggle_teardown(self, client, args, range=None):
        client.do_toggle_teardown(None, None)

    @execute_with_client()
    def com_en_type_check(self, client, args, range=None):
        client.type_check_cmd(None)

    @execute_with_client()
    def com_en_type(self, client, args, range=None):
        client.type(None)

    @execute_with_client()
    def com_en_toggle_fulltype(self, client, args, range=None):
        client.toggle_fulltype(None)

    @execute_with_client()
    def com_en_format_source(self, client, args, range=None):
        client.format_source(None)

    @execute_with_client()
    def com_en_declaration(self, client, args, range=None):
        client.open_declaration(args, range)

    @execute_with_client()
    def com_en_declaration_split(self, client, args, range=None):
        client.open_declaration_split(args, range)

    @execute_with_client()
    def com_en_symbol_by_name(self, client, args, range=None):
        client.symbol_by_name(args, range)

    @execute_with_client()
    def fun_en_package_decl(self, client, args, range=None):
        client.open_decl_for_inspector_symbol()

    @execute_with_client()
    def com_en_symbol(self, client, args, range=None):
        client.symbol(args, range)

    @execute_with_client()
    def com_en_inspect_type(self, client, args, range=None):
        client.inspect_type(args, range)

    @execute_with_client()
    def com_en_doc_uri(self, client, args, range=None):
        return client.doc_uri(args, range)

    @execute_with_client()
    def com_en_doc_browse(self, client, args, range=None):
        client.doc_browse(args, range)

    @execute_with_client()
    def com_en_suggest_import(self, client, args, range=None):
        client.suggest_import(args, range)

    @execute_with_client()
    def com_en_set_break(self, client, args, range=None):
        client.set_break(args, range)

    @execute_with_client()
    def com_en_clear_breaks(self, client, args, range=None):
        client.clear_breaks(args, range)

    @execute_with_client()
    def com_en_debug_start(self, client, args, range=None):
        client.debug_start(args, range)

    @execute_with_client(create_classpath=True)
    def com_en_classpath(self, client, args, range=None):
        client.en_classpath(args, range)

    @execute_with_client()
    def com_en_debug_continue(self, client, args, range=None):
        client.debug_continue(args, range)

    @execute_with_client()
    def com_en_backtrace(self, client, args, range=None):
        client.backtrace(args, range)

    @execute_with_client()
    def com_en_rename(self, client, args, range=None):
        client.rename(None)

    @execute_with_client()
    def com_en_inline(self, client, args, range=None):
        client.inlineLocal(None)

    @execute_with_client()
    def com_en_organize_imports(self, client, args, range=None):
        client.organize_imports(args, range)

    @execute_with_client()
    def com_en_add_import(self, client, args, range=None):
        client.add_import(None)

    @execute_with_client()
    def com_en_clients(self, client, args, range=None):
        for path in self.client_keys():
            status = self.client_status(path)
            client.raw_message("{}: {}".format(path, status))

    @execute_with_client()
    def com_en_sym_search(self, client, args, range=None):
        client.symbol_search(args)

    @execute_with_client()
    def com_en_package_inspect(self, client, args, range=None):
        client.inspect_package(args)

    @execute_with_client(quiet=True)
    def au_vim_enter(self, client, filename):
        client.vim_enter(filename)

    @execute_with_client()
    def au_vim_leave(self, client, filename):
        self.teardown()

    @execute_with_client()
    def au_buf_leave(self, client, filename):
        client.buffer_leave(filename)

    @execute_with_client()
    def au_cursor_hold(self, client, filename):
        client.on_cursor_hold(filename)

    @execute_with_client(quiet=True)
    def au_cursor_moved(self, client, filename):
        client.on_cursor_move(filename)

    @execute_with_client()
    def fun_en_complete_func(self, client, findstart_and_base, base=None):
        """Invokable function from vim and neovim to perform completion."""
        if self.is_scala_file():
            client.log("{} {}".format(findstart_and_base, base))
            if not (isinstance(findstart_and_base, list)):
                # Invoked by vim
                findstart = findstart_and_base
            else:
                # Invoked by neovim
                findstart = findstart_and_base[0]
                base = findstart_and_base[1]
            return client.complete_func(findstart, base)

    @execute_with_client()
    def on_receive(self, client, name, callback):
        client.on_receive(name, callback)

    @execute_with_client()
    def send_request(self, client, request):
        client.send_request(request)


