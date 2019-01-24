# coding: utf-8

import inspect
import json
import logging
import os
import shutil
import sys
import tempfile
import time
from subprocess import PIPE, Popen
from threading import Thread


from .config import feedback, gconfig, LOG_FORMAT
from .debugger import DebuggerClient
from .errors import InvalidJavaPathError
from .protocol import ProtocolHandler, ProtocolHandlerV1, ProtocolHandlerV2
from .typecheck import TypecheckHandler
from .util import catch, Pretty, Util

# Queue depends on python version
#if sys.version_info >= (3, 5):
import asyncio
import websockets
#elif sys.version_info > (3, 0):
#    from queue import Queue
#    import websocket
#else:
#    from Queue import Queue
#    import websocket


class EnsimeClient(TypecheckHandler, DebuggerClient, ProtocolHandler):
    """An ENSIME client for a project configuration path (``.ensime``).

    This is a base class with an abstract ProtocolHandler – you will
    need to provide a concrete one or use a ready-mixed subclass like
    ``EnsimeClientV1``.

    Once constructed, a client instance can either connect to an existing
    ENSIME server or launch a new one with a call to the ``setup()`` method.

    Communication with the server is done over a websocket (`self.ws`). Messages
    are sent to the server in the calling thread, while messages are received on
    a separate background thread and enqueued in `self.queue` upon receipt.

    Each call to the server contains a `callId` field with an integer ID,
    generated from `self.call_id`. Responses echo back the `callId` field so
    that appropriate handlers can be invoked.

    Responses also contain a `typehint` field in their `payload` field, which
    contains the type of the response. This is used to key into `self.handlers`,
    which stores the a handler per response type.
    """

    def __init__(self, editor, launcher):  # noqa: C901 FIXME
        # Our use case of a logger per class instance with independent log files
        # requires a bunch of manual programmatic config :-/
        def setup_logger():
            path = os.path
            config = self.launcher.config
            projectdir = path.abspath(config['root-dir'])
            project = config.get('name', path.basename(projectdir))
            logger = logging.getLogger(__name__).getChild(project)

            if os.environ.get('ENSIME_VIM_DEBUG'):
                logger.setLevel(logging.DEBUG)
            else:
                logger.setLevel(logging.INFO)

            # The launcher also creates this - if we refactored the weird
            # lazy_initialize_ensime path this could go away. Fixes C901.
            logdir = config['cache-dir']
            if not path.isdir(logdir):
                try:
                    os.mkdir(logdir)
                except OSError:
                    logger.addHandler(logging.NullHandler())
                    return logger

            logfile = path.join(logdir, 'ensime-vim.log')
            handler = logging.FileHandler(logfile, mode='w')
            handler.setFormatter(logging.Formatter(LOG_FORMAT))

            logger.addHandler(handler)
            logger.info('Initializing project - %s', projectdir)
            return logger

        super(EnsimeClient, self).__init__()
        self.editor = editor
        self.launcher = launcher

        self.log = setup_logger()
        self.log.debug('__init__: in')
        self.editor.initialize()

        self.ws = None
        self.ensime = None
        self.ensime_server = None

        self.call_id = 0
        self.call_options = {}
        self.refactor_id = 1
        self.refactorings = {}

        # Queue for messages received from the ensime server.
#        if sys.version_info >= (3, 5):
        self.ws_loop = None
        self.queue = None
#        else:
#            self.queue = Queue()
        self.suggestions = None
        self.completion_timeout = 10  # seconds
        self.completion_started = False

        self.full_types_enabled = False
        """Whether fully-qualified types are displayed by inspections or not"""

        self.toggle_teardown = True
        self.connection_attempts = 0
        self.tmp_diff_folder = tempfile.mkdtemp(prefix='ensime-vim-diffs')

        # By default, don't connect to server more than once
        self.number_try_connection = 1

        self.debug_thread_id = None
        self.running = True

        thread = Thread(name='queue-poller', target=self.run_queuer)
        thread.daemon = True
        thread.start()

    async def queue_poll(self, sleep_t=0.5):
        """Put new messages on the queue as they arrive. Blocking in a thread.

        Value of sleep is low to improve responsiveness.
        """
        self.log.debug("entered poller")
        while self.running:
            if self.ws:
                self.log.debug('got ws!')
                def logger_and_close(msg):
                    self.log.error('Websocket exception', exc_info=True)
                    if self.running:
                        if not self.number_try_connection:
                            # Stop everything.
                            self.teardown()
                            self._display_ws_warning()
                            self.ws = None

                with catch(Exception, logger_and_close):
                    self.log.debug('poller waiting')
                    result = await self.ws.recv()
                    self.log.debug('got result!' + result)
                    self.queue.put_nowait(result)

            else:
                self.log.debug('poller sleeping - no ws!')
                await asyncio.sleep(sleep_t)
                self.log.debug('poller slept well. no ws!')

    def run_queuer(self):
        self.log.debug("get event loop")
        self.ws_loop = asyncio.new_event_loop()
        self.queue = asyncio.Queue(loop = self.ws_loop)
        asyncio.set_event_loop(self.ws_loop)
        self.log.debug('starting poller!')
        with catch(Exception, self.log.error):
            self.ws_loop.run_until_complete(self.queue_poll())
        self.log.debug('done poller!')
        self.ws_loop.close()

    def setup(self, quiet=False, bootstrap_server=False):
        """Check the classpath and connect to the server if necessary."""
        def lazy_initialize_ensime():
            if not self.ensime:
                called_by = inspect.stack()[4][3]
                self.log.debug(str(inspect.stack()))
                self.log.debug('setup(quiet=%s, bootstrap_server=%s) called by %s()',
                               quiet, bootstrap_server, called_by)

                installed = self.launcher.strategy.isinstalled()
                if not installed and not bootstrap_server:
                    if not quiet:
                        scala = self.launcher.config.get('scala-version')
                        msg = feedback["prompt_server_install"].format(scala_version=scala)
                        self.editor.raw_message(msg)
                    return False

                try:
                    self.ensime = self.launcher.launch()
                except InvalidJavaPathError:
                    self.editor.message('invalid_java')  # TODO: also disable plugin

            return bool(self.ensime)

        def ready_to_connect():
            if not self.ws and self.ensime.is_ready():
                self.connect_ensime_server()
            return True

        # True if ensime is up and connection is ok, otherwise False
        return self.running and lazy_initialize_ensime() and ready_to_connect()

    def _display_ws_warning(self):
        warning = "A WS exception happened, 'ensime-vim' has been disabled. " +\
            "For more information, have a look at the logs in `.ensime_cache`"
        self.editor.raw_message(warning)

    def send(self, msg):
        """Send something to the ensime server."""
        def send_it(msg):
            with catch(Exception, self.log.error):
                asyncio.run_coroutine_threadsafe(self.ws.send(msg + "\n"), self.ws_loop).result(10)
            # TODO: returns future, handle errors

        def reconnect(e):
            self.log.error('send error, reconnecting...', exc_info=True)
            self.connect_ensime_server()
            if self.ws:
                send_it(msg)

        self.log.debug('send: in')
        if self.running and self.ws:
            with catch(Exception, reconnect):
                self.log.debug('send: sending JSON on WebSocket')
                send_it(msg)

    def connect_ensime_server(self):
        """Start initial connection with the server."""
        self.log.debug('connect_ensime_server: in')
        server_v2 = isinstance(self, EnsimeClientV2)

        def disable_completely(e):
            if e:
                self.log.error('connection error: %s', e, exc_info=True)
            self.shutdown_server()
            self._display_ws_warning()

        if self.running and self.number_try_connection:
            self.number_try_connection -= 1
            if not self.ensime_server:
                port = self.ensime.http_port()
                uri = "websocket" if server_v2 else "jerky"
                self.ensime_server = gconfig["ensime_server"].format(port, uri)
            with catch(Exception, disable_completely):
                # Use the default timeout (no timeout).
                async def connect():
                    options = {"subprotocols": ["jerky"]} if server_v2 else {}
                    self.log.debug("About to connect to %s with options %s",
                                self.ensime_server, options)
                    self.ws = await websockets.client.connect(self.ensime_server, **options)
                    return True
                gotws = asyncio.run_coroutine_threadsafe(connect(), self.ws_loop).result(10)
            if gotws:
                self.send_request({"typehint": "ConnectionInfoReq"})
        else:
            # If it hits this, number_try_connection is 0
            disable_completely(None)

    def shutdown_server(self):
        """Shut down server if it is alive."""
        self.log.debug('shutdown_server: in')
        if self.ensime and self.toggle_teardown:
            self.ensime.stop()

    def teardown(self):
        """Tear down the server or keep it alive."""
        self.log.debug('teardown: in')
        self.running = False
        self.shutdown_server()
        shutil.rmtree(self.tmp_diff_folder, ignore_errors=True)

    def send_at_position(self, what, useSelection, where="range"):
        """Ask the server to perform an operation on a range (sometimes named point)

        `what` is used as the prefix for the typehint.

        If `useSelection` is `False` the range is calculated based on the word under de
        cursor. Current selection start and end is used as the range otherwise.

        `where` defines the name of the property holding the range info within the request.
        Default value is 'range' but 'point' is sometimes used
        """
        self.log.debug('send_at_position: in')
        b, e = self.editor.selection_pos() if useSelection else self.editor.word_under_cursor_pos()
        self.log.debug('useSelection: {}, beg: {}, end: {}'.format(useSelection, b, e))
        beg = self.get_position(b[0], b[1])
        end = self.get_position(e[0], e[1])
        self.send_request(
            {"typehint": what + "AtPointReq",
             "file": self.editor.path(),
             where: {"from": beg, "to": end}})

    # TODO: Should these be in Editor? They're translating to/from ENSIME's
    # coordinate scheme so it's debatable.

    def set_position(self, decl_pos):
        """Set editor position from ENSIME declPos data."""
        if decl_pos["typehint"] == "LineSourcePosition":
            self.editor.set_cursor(decl_pos['line'], 0)
        else:  # OffsetSourcePosition
            point = decl_pos["offset"]
            row, col = self.editor.point2pos(point + 1)
            self.editor.set_cursor(row, col)

    def get_position(self, row, col):
        """Get char position in all the text from row and column."""
        result = col
        self.log.debug('%s %s', row, col)
        lines = self.editor.getlines()[:row - 1]
        result += sum([len(l) + 1 for l in lines])
        self.log.debug(result)
        return result

    def open_decl_for_inspector_symbol(self):
        self.log.debug('open_decl_for_inspector_symbol: in')
        lineno = self.editor.cursor()[0]
        symbol = self.editor.symbol_for_inspector_line(lineno)
        self.symbol_by_name([symbol])
        self.unqueue()

    def symbol_by_name(self, args, range=None):
        self.log.debug('symbol_by_name: in')
        if not args:
            self.editor.raw_message('Must provide a fully-qualifed symbol name')
            return

        self.call_options[self.call_id] = {"split": True,
                                           "vert": True,
                                           "open_definition": True}
        fqn = args[0]
        req = {
            "typehint": "SymbolByNameReq",
            "typeFullName": fqn
        }
        if len(args) == 2:
            req["memberName"] = args[1]
        self.send_request(req)

    def complete(self, row, col):
        self.log.debug('complete: in')
        pos = self.get_position(row, col)
        self.send_request({"point": pos, "maxResults": 100,
                           "typehint": "CompletionsReq",
                           "caseSens": True,
                           "fileInfo": self._file_info(),
                           "reload": False})

    def send_at_point(self, what, row, col):
        """Ask the server to perform an operation at a given point."""
        pos = self.get_position(row, col)
        self.send_request(
            {"typehint": what + "AtPointReq",
             "file": self._file_info(),
             "point": pos})

    def do_toggle_teardown(self, args, range=None):
        self.log.debug('do_toggle_teardown: in')
        self.toggle_teardown = not self.toggle_teardown

    def type_check_cmd(self, args, range=None):
        """Sets the flag to begin buffering typecheck notes & clears any
        stale notes before requesting a typecheck from the server"""
        self.log.debug('type_check_cmd: in')
        self.start_typechecking()
        self.type_check("")
        self.editor.message('typechecking')

    def en_install(self, args, range=None):
        """Bootstrap ENSIME server installation.

        Enabling the bootstrapping actually happens in the execute_with_client
        decorator when this is called, so this function is a no-op endpoint for
        the Vim command.
        TODO: this is confusing...
        """
        self.log.debug('en_install: in')

    def type(self, args, range=None):
        useSelection = 'selection' in args
        self.log.debug('type: in, sel: {}'.format(useSelection))
        self.send_at_position("Type", useSelection)

    def toggle_fulltype(self, args, range=None):
        self.log.debug('toggle_fulltype: in')
        self.full_types_enabled = not self.full_types_enabled

        if self.full_types_enabled:
            self.editor.message("full_types_enabled_on")
        else:
            self.editor.message("full_types_enabled_off")

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
        pos = self.get_position(*self.editor.cursor())
        self.send_request({
            "point": pos + 1,
            "typehint": "SymbolAtPointReq",
            "file": self.editor.path()})

    def inspect_package(self, args):
        pkg = None
        if not args:
            pkg = Util.extract_package_name(self.editor.getlines())
            self.editor.message('package_inspect_current')
        else:
            pkg = args[0]
        self.send_request({
            "typehint": "InspectPackageByPathReq",
            "path": pkg
        })

    def open_declaration(self, args, range=None):
        self.log.debug('open_declaration: in')
        self.symbol_at_point_req(True)

    def open_declaration_split(self, args, range=None):
        self.log.debug('open_declaration: in')
        if "v" in args:
            self.call_options[self.call_id] = {"split": True, "vert": True}
        else:
            self.call_options[self.call_id] = {"split": True}

        self.symbol_at_point_req(True)

    def symbol(self, args, range=None):
        self.log.debug('symbol: in')
        self.symbol_at_point_req(False, True)

    def suggest_import(self, args, range=None):
        self.log.debug('suggest_import: in')
        pos = self.get_position(*self.editor.cursor())
        word = self.editor.current_word()
        req = {"point": pos,
               "maxResults": 10,
               "names": [word],
               "typehint": "ImportSuggestionsReq",
               "file": self.editor.path()}
        self.send_request(req)

    def inspect_type(self, args, range=None):
        self.log.debug('inspect_type: in')
        pos = self.get_position(*self.editor.cursor())
        self.send_request({
            "point": pos,
            "typehint": "InspectTypeAtPointReq",
            "file": self.editor.path(),
            "range": {"from": pos, "to": pos}})

    def doc_uri(self, args, range=None):
        """Request doc of whatever at cursor."""
        self.log.debug('doc_uri: in')
        self.send_at_position("DocUri", False, "point")

    def usages(self):
        """Request usages of whatever at cursor."""
        row, col = self.editor.cursor()
        self.log.debug('usages: in')
        self.call_options[self.call_id] = {
                "word_under_cursor": self.editor.current_word(),
                "false_resp_msg": "Not a valid symbol under the cursor"}
        self.send_at_point("UsesOfSymbol", row, col)

    def doc_browse(self, args, range=None):
        """Browse doc of whatever at cursor."""
        self.log.debug('browse: in')
        self.call_options[self.call_id] = {"browse": True}
        self.send_at_position("DocUri", False, "point")

    def rename(self, new_name, range=None):
        """Request a rename to the server."""
        self.log.debug('rename: in')
        if not new_name:
            new_name = self.editor.ask_input("Rename to:")
        self.editor.write(noautocmd=True)
        b, e = self.editor.word_under_cursor_pos()
        current_file = self.editor.path()
        self.editor.raw_message(current_file)
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
        self.log.debug('inline: in')
        self.editor.write(noautocmd=True)
        b, e = self.editor.word_under_cursor_pos()
        current_file = self.editor.path()
        self.editor.raw_message(current_file)
        self.send_refactor_request(
            "RefactorReq",
            {
                "typehint": "InlineLocalRefactorDesc",
                "start": self.get_position(b[0], b[1]),
                "end": self.get_position(e[0], e[1]) + 1,
                "file": current_file,
            },
            {"interactive": False}
        )

    def organize_imports(self, args, range=None):
        self.editor.write(noautocmd=True)
        current_file = self.editor.path()
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
            name = self.editor.ask_input("Qualified name to import:")
        self.editor.write(noautocmd=True)
        self.send_refactor_request(
            "RefactorReq",
            {
                "typehint": "AddImportRefactorDesc",
                "file": self.editor.path(),
                "qualifiedName": name
            },
            {"interactive": False}
        )

    def symbol_search(self, search_terms):
        """Search for symbols matching a set of keywords"""
        self.log.debug('symbol_search: in')

        if not search_terms:
            self.editor.message('symbol_search_symbol_required')
            return
        req = {
            "typehint": "PublicSymbolSearchReq",
            "keywords": search_terms,
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

    # TODO: preserve cursor position
    def apply_refactor(self, call_id, payload):
        """Apply a refactor depending on its type."""
        supported_refactorings = ["Rename", "InlineLocal", "AddImport", "OrganizeImports"]

        if payload["refactorType"]["typehint"] in supported_refactorings:
            diff_filepath = payload["diff"]
            path = self.editor.path()
            bname = os.path.basename(path)
            target = os.path.join(self.tmp_diff_folder, bname)
            reject_arg = "--reject-file={}.rej".format(target)
            backup_pref = "--prefix={}".format(self.tmp_diff_folder)
            # Patch utility is prepackaged or installed with vim
            cmd = ["patch", reject_arg, backup_pref, path, diff_filepath]
            failed = Popen(cmd, stdout=PIPE, stderr=PIPE).wait()
            if failed:
                self.editor.message("failed_refactoring")
            # Update file and reload highlighting
            self.editor.edit(self.editor.path())
            self.editor.doautocmd('BufReadPre', 'BufRead', 'BufEnter')

    def send_request(self, request):
        """Send a request to the server."""
        self.log.debug('send_request: in')

        message = {'callId': self.call_id, 'req': request}
        self.log.debug('send_request: %s', Pretty(message))
        self.send(json.dumps(message))

        call_id = self.call_id
        self.call_id += 1
        return call_id

    def buffer_leave(self, filename):
        """User is changing of buffer."""
        self.log.debug('buffer_leave: %s', filename)
        # TODO: This is questionable, and we should use location list for
        # single-file errors.
        self.editor.clean_errors()

    def type_check(self, filename):
        """Update type checking when user saves buffer."""
        self.log.debug('type_check: in')
        self.editor.clean_errors()
        self.send_request(
            {"typehint": "TypecheckFilesReq",
             "files": [self.editor.path()]})

    def unqueue(self, timeout=10):
        """Unqueue all the received ensime responses for a given file."""
        with catch(Exception, self.log.error):
            if timeout != 0 or not self.queue.empty():
                if timeout == 0:
                    timeout = 0.01
                resultFuture = asyncio.run_coroutine_threadsafe(self.queue.get(), self.ws_loop)
                try:
                    result = resultFuture.result(timeout)
                    self.log.debug("Unqueued result: " + result)
                    # TODO: catch asyncio.TimeoutError: and cancel future
                    _json = json.loads(result)
                    # Watch out, it may not have callId
                    call_id = _json.get("callId")
                    if _json["payload"]:
                        self.handle_incoming_response(call_id, _json["payload"])
                except asyncio.TimeoutError:
                    self.log.debug("Unqueing failed: timeout: "+str(timeout))
                    resultFuture.cancel()

#        start, now = time.time(), time.time()
#        wait = self.queue.empty() and should_wait
#
#        while (not self.queue.empty() or wait) and (now - start) < timeout:
#            if wait and self.queue.empty():
#                time.sleep(0.25)
#                now = time.time()
#            else:
#                result = self.queue.get(False)
#                self.log.debug('unqueue: result received\n%s', result)
#                if result and result != "nil":
#                    wait = None
#                    # Restart timeout
#                    start, now = time.time(), time.time()
#                    _json = json.loads(result)
#                    # Watch out, it may not have callId
#                    call_id = _json.get("callId")
#                    if _json["payload"]:
#                        self.handle_incoming_response(call_id, _json["payload"])
#                else:
#                    self.log.debug('unqueue: nil or None received')
#
#        if (now - start) >= timeout:
#            self.log.warning('unqueue: no reply from server for %ss', timeout)
#
    def unqueue_and_display(self, filename):
        """Unqueue messages and give feedback to user (if necessary)."""
        if self.running and self.ws:
            self.editor.lazy_display_error(filename)
            self.unqueue(0) # TODO: no wait

    def tick(self, filename):
        """Try to connect and display messages in queue."""
        if self.connection_attempts < 10:
            # Trick to connect ASAP when
            # plugin is  started without
            # user interaction (CursorMove)
            self.setup(True, False)
            self.connection_attempts += 1
        self.unqueue_and_display(filename)

    def vim_enter(self, filename):
        """Set up EnsimeClient when vim enters.

        This is useful to start the EnsimeLauncher as soon as possible."""
        success = self.setup(True, False)
        if success:
            self.editor.message("start_message")

    def complete_func(self, findstart, base):
        """Handle omni completion."""
        self.log.debug('complete_func: in %s %s', findstart, base)

        def detect_row_column_start():
            row, col = self.editor.cursor()
            start = col
            line = self.editor.getline()
            while start > 0 and line[start - 1] not in " .,([{":
                start -= 1
            # Start should be 1 when startcol is zero
            return row, col, start if start else 1

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
                # Unqueing messages until we get suggestions
                self.unqueue(timeout=self.completion_timeout)
                suggestions = self.suggestions or []
                self.log.debug('complete_func: suggestions in')
                for m in suggestions:
                    result.append(m)
                self.suggestions = None
                self.completion_started = False
            return result

    def _file_info(self):
        """Message fragment for ENSIME ``fileInfo`` field, from current file."""
        return {
            'file': self.editor.path(),
            'contents': self.editor.get_file_content(),
        }


class EnsimeClientV1(ProtocolHandlerV1, EnsimeClient):
    """An ENSIME client for the v1 Jerky protocol."""


class EnsimeClientV2(ProtocolHandlerV2, EnsimeClient):
    """An ENSIME client for the v2 Jerky protocol."""
