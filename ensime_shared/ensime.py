# coding: utf-8
"""
The Python core of the ensime-vim plugin, which bridges between ENSIME
client/server communication and Vim as the UI, event, and scripting layer.
"""

import os

from .client import EnsimeClientV1, EnsimeClientV2
from .config import feedback, ProjectConfig
from .editor import Editor
from .errors import InvalidJavaPathError
from .server import Server
from .ticker import Ticker


def execute_with_client():
    """Decorator that injects a client instance as the first parameter of the
    wrapped function.

    The client is associated with the project for the file in the currently
    active Vim buffer, and will be ``None`` if the file isn't in an ``.ensime``
    project.
    """
    def wrapper(f):

        def wrapper2(self, *args, **kwargs):
            client = self.current_client()
            if client:
                return f(self, client, *args, **kwargs)
        return wrapper2

    return wrapper


class Ensime(object):
    """Base class representing the Vim plugin itself. Dispatches commands/events
    from Vim to be serviced by an ENSIME client.

    There is normally one instance of ``Ensime`` per Vim session. It manages
    potentially multiple ``EnsimeClient`` instances if the user edits more than
    one ENSIME project.

    Args:
        vim: The ``vim`` module/singleton from the Vim Python API.

    Attributes:
        clients (Mapping[str, EnsimeClient]):
            Active client instances, keyed by the filesystem path to the
            ``.ensime`` configuration for their respective projects.

        servers (Mapping[str, Server]):
            Active server processes, keyed by the filesystem path to the
            ``.ensime`` configuration for their respective projects.
    """

    def __init__(self, vim):
        # NOTE: The vim object cannot be used within the constructor due to
        # race condition of autocommand handlers being invoked as they're being
        # defined.
        self._vim = vim
        self._editor = Editor(vim)
        self._ticker = None
        self.clients = {}
        self.servers = {}

    @property
    def using_server_v2(self):
        """bool: Whether user has configured the plugin to use ENSIME v2 protocol."""
        return bool(self.get_setting('server_v2', 1))

    def get_setting(self, key, default):
        """Returns the value of a Vim variable ``g:ensime_{key}``
        if it is set, and ``default`` otherwise.
        """
        gkey = "ensime_{}".format(key)
        return self._vim.vars.get(gkey, default)

    def client_status(self, config_path):
        """Get status of client for a project, given path to its config."""
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
        for server in self.servers.values():
            server.stop()

    def current_client(self):
        """Get the client for current file in the editor.

        Returns:
            Optional[EnsimeClient]
        """
        config = self.current_project_config()
        if config:
            return self.client_for(config.filepath)

    def current_project_config(self):
        """Get the project configuration for the current file in the editor.

        Returns:
            Optional[ProjectConfig]
        """
        current_file = self._vim.current.buffer.name
        config_path = ProjectConfig.find_from(current_file)
        if config_path:
            return ProjectConfig(config_path)

    def client_for(self, config_path):
        """Get a cached client for a project, otherwise create one."""
        key = os.path.realpath(config_path)
        return self.clients.get(key) or self.create_client(config_path)

    def create_client(self, config_path):
        """Create an :class:`EnsimeClient` for a project, given its config file path.

        If a client already exists for the project, it will be shut down and
        recreated. Use :meth:`client_for` to avoid this.
        """
        key = os.path.realpath(config_path)
        if key in self.clients:
            self.clients[key].teardown()

        config = ProjectConfig(config_path)

        if self.using_server_v2:
            client = EnsimeClientV2(self._editor, config)
        else:
            client = EnsimeClientV1(self._editor, config)

        self.clients[key] = client
        self._create_ticker()
        return client

    def _create_ticker(self):
        """Create and start the periodic ticker."""
        if not self._ticker:
            self._ticker = Ticker(self._vim)

    def server(self, config):
        """Get server instance for a project, creating it if needed."""
        # Could do a defaultdict subclass with __missing__ override?
        server = self.servers.get(config.filepath)
        if not server:
            server = Server(config, self.using_server_v2)
            self.servers[config.filepath] = server
        return server

    def start_server(self, config):
        """Start an ENSIME server process for project with given config.

        If the server isn't installed, prompts the user to install it and returns.
        """
        editor = self._editor
        server = self.server(config)

        if not server.isinstalled():
            scala = config.get('scala-version')
            msg = feedback['prompt_server_install'].format(scala_version=scala)
            editor.raw_message(msg)
            return server

        try:
            if server.start():
                editor.message('start_message')
        except InvalidJavaPathError:
            editor.message('invalid_java')  # TODO: also disable plugin

        return server

    def disable_plugin(self):
        """Disable ensime-vim, in the event of an error we can't usefully
        recover from.

        Todo:
            This is incomplete and unreliable, see:
            https://github.com/ensime/ensime-vim/issues/294

            If used from a secondary thread, this may need to use threadsafe
            Vim calls where available -- see :meth:`Editor.raw_message`.
        """
        for path in self.runtime_paths():
            self._vim.command('set runtimepath-={}'.format(path))

    # Tried making this a @property, with and without memoization, and it made
    # plugin initialization misbehave in Neovim (only). WTF.
    def runtime_paths(self):  # TODO: memoize
        """All the runtime paths of ensime-vim plugin files."""
        runtimepath = self._vim.options['runtimepath']
        plugin = "ensime-vim"
        paths = []

        for path in runtimepath.split(','):
            if plugin in path:
                paths.append(os.path.expanduser(path))

        return paths

    def tick_clients(self):
        """Trigger the periodic tick function in the client."""
        if not self._ticker:
            self._create_ticker()

        for client in self.clients.values():
            self.watchdog_client_server_connection(client)
            self._ticker.tick(client)

    @execute_with_client()
    def com_en_type_check(self, client, args, range=None):
        client.type_check_cmd(None)

    @execute_with_client()
    def com_en_type(self, client, args, range=None):
        client.type(args)

    @execute_with_client()
    def com_en_usages(self, client, args, range=None):
        client.usages()

    @execute_with_client()
    def com_en_toggle_fulltype(self, client, args, range=None):
        client.toggle_fulltype(None)

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
    def com_en_debug_set_break(self, client, args, range=None):
        client.debug_set_break(args, range)

    @execute_with_client()
    def com_en_debug_clear_breaks(self, client, args, range=None):
        client.debug_clear_breaks(args, range)

    @execute_with_client()
    def com_en_debug_start(self, client, args, range=None):
        client.debug_start(args, range)

    def com_en_install(self):
        """Handler for ``:EnInstall`` command."""
        config = self.current_project_config()
        # TODO: message if called from a non-project file
        if config:
            self.server(config).install()

    @execute_with_client()
    def com_en_debug_continue(self, client, args, range=None):
        client.debug_continue(args, range)

    @execute_with_client()
    def com_en_debug_step(self, client, args, range=None):
        client.debug_step(args, range)

    @execute_with_client()
    def com_en_debug_step_out(self, client, args, range=None):
        client.debug_step_out(args, range)

    @execute_with_client()
    def com_en_debug_next(self, client, args, range=None):
        client.debug_next(args, range)

    @execute_with_client()
    def com_en_debug_backtrace(self, client, args, range=None):
        client.debug_backtrace(args, range)

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
        for path in self.clients.keys():
            status = self.client_status(path)
            client.editor.raw_message("{}: {}".format(path, status))

    @execute_with_client()
    def com_en_sym_search(self, client, args, range=None):
        client.symbol_search(args)

    @execute_with_client()
    def com_en_package_inspect(self, client, args, range=None):
        client.inspect_package(args)

    def au_vim_enter(self, filename):
        """Handler for VimEnter autocommand event."""
        dotensime = ProjectConfig.find_from(filename)
        if dotensime:
            self.start_server(ProjectConfig(dotensime))

    def au_vim_leave(self, _filename):
        self.teardown()

    def au_cursor_hold(self, _filename):
        """Handler for CursorHold autocommand event."""
        self.tick_clients()

    def au_cursor_moved(self, _filename):
        """Handler for CursorMoved autocommand event."""
        self.tick_clients()

    def au_buf_enter(self, _filename):
        """Handler for BufEnter autocommand event.

        Used only to trigger creation of a client if needed.
        """
        self.current_client()

    @execute_with_client()
    def au_buf_leave(self, client, filename):
        client.buffer_leave(filename)

    @execute_with_client()
    def fun_en_complete_func(self, client, findstart_and_base, base=None):
        """Invokable function from vim and neovim to perform completion."""
        if isinstance(findstart_and_base, list):
            # Invoked by neovim
            findstart = findstart_and_base[0]
            base = findstart_and_base[1]
        else:
            # Invoked by vim
            findstart = findstart_and_base
        return client.complete_func(findstart, base)

    def fun_en_tick(self, timer):
        """Callback registered with Vim timer for plugin's clock mechanism."""
        self.tick_clients()

    def watchdog_client_server_connection(self, client):
        """Run periodically to check and maintain client, server, and cxn health."""
        if not client.connected and client.connection_attempts < 10:
            config = client.config
            server = self.server(config)
            if not server.isrunning():
                self.start_server(config)
            client.connect(server)
            client.connection_attempts += 1
