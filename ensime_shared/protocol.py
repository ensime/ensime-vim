# coding: utf-8

import json
import webbrowser

from ensime_shared.config import commands, feedback, gconfig
from ensime_shared.symbol_format import completion_to_suggest
from ensime_shared.util import catch, Pretty


class ProtocolHandler(object):
    """Mixin for common behavior of handling ENSIME protocol responses.

    Actual handler implementations are abstract and should be implemented by a
    subclass. Requires facilities of an ``EnsimeClient``.
    """

    def __init__(self):
        self.handlers = {}
        self.register_responses_handlers()

    def register_responses_handlers(self):
        """Register handlers for responses from the server.

        A handler must accept only one parameter: `payload`.
        """
        self.handlers["SymbolInfo"] = self.handle_symbol_info
        self.handlers["IndexerReadyEvent"] = self.handle_indexer_ready
        self.handlers["AnalyzerReadyEvent"] = self.handle_analyzer_ready
        self.handlers["NewScalaNotesEvent"] = self.buffer_typechecks
        self.handlers["BasicTypeInfo"] = self.show_type
        self.handlers["ArrowTypeInfo"] = self.show_type
        self.handlers["FullTypeCheckCompleteEvent"] = self.handle_typecheck_complete
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

    def handle_incoming_response(self, call_id, payload):
        """Get a registered handler for a given response and execute it."""
        self.log.debug('handle_incoming_response: in [typehint: %s, call ID: %s]',
                       payload['typehint'], call_id)  # We already log the full JSON response

        typehint = payload["typehint"]
        handler = self.handlers.get(typehint)

        def feature_not_supported(m):
            msg = feedback["handler_not_implemented"]
            self.raw_message(msg.format(typehint, self.launcher.ensime_version))

        if handler:
            with catch(NotImplementedError, feature_not_supported):
                handler(call_id, payload)
        else:
            self.log.warning('Response has not been handled: %s', Pretty(payload))

    def handle_indexer_ready(self, call_id, payload):
        raise NotImplementedError()

    def handle_analyzer_ready(self, call_id, payload):
        raise NotImplementedError()

    def handle_debug_vm_error(self, call_id, payload):
        raise NotImplementedError()

    def handle_import_suggestions(self, call_id, payload):
        raise NotImplementedError()

    def handle_package_info(self, call_id, payload):
        raise NotImplementedError()

    def handle_symbol_search(self, call_id, payload):
        raise NotImplementedError()

    def handle_symbol_info(self, call_id, payload):
        raise NotImplementedError()

    def handle_string_response(self, call_id, payload):
        raise NotImplementedError()

    def handle_completion_info_list(self, call_id, payload):
        raise NotImplementedError()

    def handle_type_inspect(self, call_id, payload):
        raise NotImplementedError()

    def show_type(self, call_id, payload):
        raise NotImplementedError()


class ProtocolHandlerV1(ProtocolHandler):
    """Implements response handlers for the v1 ENSIME Jerky protocol."""

    def handle_indexer_ready(self, call_id, payload):
        self.message("indexer_ready")

    def handle_analyzer_ready(self, call_id, payload):
        self.message("analyzer_ready")

    def handle_debug_vm_error(self, call_id, payload):
        msg = "Error. Check ensime-vim log for details."
        self.vim.command(commands['display_message'].format(msg))

    def handle_import_suggestions(self, call_id, payload):
        imports = list()
        for suggestions in payload['symLists']:
            for suggestion in suggestions:
                imports.append(suggestion['name'].replace('$', '.'))
        imports = list(sorted(set(imports)))

        if not imports:
            msg = "No import suggestions found."
            self.vim.command(commands['display_message'].format(msg))
            return

        choices = ["{0}. {1}".format(*choice) for choice in enumerate(imports, start=1)]
        menu = json.dumps(['Select class to import:'] + choices)
        command = commands['select_item_list'].format(menu)
        chosen_import = int(self.vim.eval(command))

        if chosen_import > 0:
            self.add_import(imports[chosen_import - 1])

    def handle_package_info(self, call_id, payload):
        package = payload["fullName"]

        def add(member, indentLevel):
            indent = "  " * indentLevel
            t = member["declAs"]["typehint"] if member["typehint"] == "BasicTypeInfo" else ""
            line = "{}{}: {}".format(indent, t, member["name"])
            self.vim.command(commands["append_line"].format("\'$\'", str(line)))
            if indentLevel < 4:
                for m in member["members"]:
                    add(m, indentLevel + 1)

        # Create a new buffer 45 columns wide
        cmd = commands["new_vertical_scratch"].format(str(45), "package_info")
        self.vim.command(cmd)
        self.vim.command(commands["set_filetype"].format("package_info"))
        self.vim.command(commands["append_line"].format("\'$\'", str(package)))
        for member in payload["members"]:
            add(member, 1)

    def handle_symbol_search(self, call_id, payload):
        """Handler for symbol search results"""
        self.log.debug('handle_symbol_search: in %s', Pretty(payload))

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
        with catch(KeyError, lambda e: self.message("unknown_symbol")):
            decl_pos = payload["declPos"]
            f = decl_pos.get("file")
            call_options = self.call_options[call_id]
            self.log.debug('handle_symbol_info: call_options %s', call_options)
            display = call_options.get("display")
            if display and f:
                self.vim.command(commands["display_message"].format(f))

            open_definition = call_options.get("open_definition")
            if open_definition and f:
                self.clean_errors()
                self.vim_command("doautocmd_bufleave")
                split = call_options.get("split")
                vert = call_options.get("vert")
                key = ""
                if split:
                    key = "vert_split_window" if vert else "split_window"
                else:
                    key = "edit_file"
                self.vim.command(commands[key].format(f))
                self.vim_command("doautocmd_bufreadenter")
                self.set_position(decl_pos)
                del self.call_options[call_id]

    def handle_string_response(self, call_id, payload):
        """Handler for response `StringResponse`.

        This is the response for the following requests:
          1. `DocUriAtPointReq` or `DocUriForSymbolReq`
          2. `DebugToStringReq`
          3. `FormatOneSourceReq`
        """
        self.log.debug('handle_string_response: in [typehint: %s, call ID: %s]',
                       payload['typehint'], call_id)

        if self.en_format_source_id:  # User requested :EnFormatSource
            self._format_source_file(payload['text'])
            self.en_format_source_id = None
            return

        # :EnDocBrowse or :EnDocUri
        url = payload['text']
        if not url.startswith('http'):
            port = self.ensime.http_port()
            url = gconfig['localhost'].format(port, url)

        options = self.call_options.get(call_id)
        if options and options.get('browse'):
            self._browse_doc(url)
            del self.call_options[call_id]
        else:
            # TODO: make this return value of a Vim function synchronously, how?
            self.log.debug('EnDocUri %s', url)
            return url

    def _format_source_file(self, newtext):
        self.vim.current.buffer[:] = [  # FIXME: should assure original buffer
            line.encode('utf-8')
            for line in newtext.split('\n')
        ]

    def _browse_doc(self, url):
        self.log.debug('_browse_doc: %s', url)
        try:
            if webbrowser.open(url):
                self.log.info('opened %s', url)
        except webbrowser.Error:
            self.log.exception('_browse_doc: webbrowser error')
            self.raw_message(feedback["manual_doc"].format(url))

    def handle_completion_info_list(self, call_id, payload):
        """Handler for a completion response."""
        self.log.debug('handle_completion_info_list: in')
        # filter out completions without `typeInfo` field to avoid server bug. See #324
        completions = [c for c in payload["completions"] if "typeInfo" in c]
        self.suggestions = [completion_to_suggest(c) for c in completions]
        self.log.debug('handle_completion_info_list: %s', Pretty(self.suggestions))

    def handle_type_inspect(self, call_id, payload):
        """Handler for responses `TypeInspectInfo`."""
        style = 'fullName' if self.full_types_enabled else 'name'
        interfaces = payload.get("interfaces")
        ts = [i["type"][style] for i in interfaces]
        prefix = "( " + ", ".join(ts) + " ) => "
        self.raw_message(prefix + payload["type"][style])

    # TODO @ktonga reuse completion suggestion formatting logic
    def show_type(self, call_id, payload):
        """Show type of a variable or scala type."""
        if self.full_types_enabled:
            tpe = payload['fullName']
        else:
            tpe = payload['name']

        self.log.info('Displayed type %s', tpe)
        self.raw_message(tpe)


class ProtocolHandlerV2(ProtocolHandlerV1):
    """Implements response handlers for the v2 ENSIME Jerky protocol."""
