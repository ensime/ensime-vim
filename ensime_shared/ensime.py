# coding: utf-8

import os

from .client import EnsimeClientV1, EnsimeClientV2
from .config import ProjectConfig
from .editor import Editor
from .launcher import EnsimeLauncher
from .ticker import Ticker


def execute_with_client(quiet=False,
                        bootstrap_server=False,
                        create_client=True):
    """Decorator that gets a client and performs an operation on it."""
    def wrapper(f):

        def wrapper2(self, *args, **kwargs):
            client = self.current_client(
                quiet=quiet,
                bootstrap_server=bootstrap_server,
                create_client=create_client)
            if client and client.running:
                return f(self, client, *args, **kwargs)
        return wrapper2

    return wrapper


class Ensime(object):
    """Base class representing the Vim plugin itself. Bridges Vim as a UI and
    event layer into the Python core.

    There is normally one instance of ``Ensime`` per Vim session. It manages
    potentially multiple ``EnsimeClient`` instances if the user edits more than
    one ENSIME project.

    Args:
        vim: The ``vim`` module/singleton from the Vim Python API.

    Attributes:
        clients (Mapping[str, EnsimeClient]):
            Active client instances, keyed by the filesystem path to the
            ``.ensime`` configuration for their respective projects.
    """

    def __init__(self, vim):
        # NOTE: The vim object cannot be used within the constructor due to
        # race condition of autocommand handlers being invoked as they're being
        # defined.
        self._vim = vim
        self._ticker = None
        self.clients = {}

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

    def current_client(self, quiet, bootstrap_server, create_client):
        """Return the client for current file in the editor."""
        current_file = self._vim.current.buffer.name
        config_path = ProjectConfig.find_from(current_file)
        if config_path:
            return self.client_for(
                config_path,
                quiet=quiet,
                bootstrap_server=bootstrap_server,
                create_client=create_client)

    def client_for(self, config_path, quiet=False, bootstrap_server=False,
                   create_client=False):
        """Get a cached client for a project, otherwise create one."""
        client = None
        abs_path = os.path.abspath(config_path)
        if abs_path in self.clients:
            client = self.clients[abs_path]
        elif create_client:
            client = self.create_client(config_path)
            if client.setup(quiet=quiet, bootstrap_server=bootstrap_server):
                self.clients[abs_path] = client
        return client

    def create_client(self, config_path):
        """Create an :class:`EnsimeClient` for a project, given its config file path.

        This will launch the ENSIME server for the project as a side effect.
        """
        config = ProjectConfig(config_path)
        editor = Editor(self._vim)
        launcher = EnsimeLauncher(self._vim, config)

        if self.using_server_v2:
            client = EnsimeClientV2(editor, launcher)
        else:
            client = EnsimeClientV1(editor, launcher)

        self._create_ticker()

        return client

    def _create_ticker(self):
        """Create and start the periodic ticker."""
        if not self._ticker:
            self._ticker = Ticker(self._vim)


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
            self._ticker.tick(client)

    @execute_with_client()
    def com_en_toggle_teardown(self, client, args, range=None):
        client.do_toggle_teardown(None, None)

    @execute_with_client()
    def com_en_type_check(self, client, args, range=None):
        client.type_check_cmd(None)

    @execute_with_client()
    def com_en_type(self, client, args, range=None):
        client.type(args)

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

    @execute_with_client(bootstrap_server=True)
    def com_en_install(self, client, args, range=None):
        client.en_install(args, range)

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

    @execute_with_client(quiet=True)
    def au_vim_enter(self, client, filename):
        client.vim_enter(filename)

    @execute_with_client()
    def au_vim_leave(self, client, filename):
        self.teardown()

    @execute_with_client()
    def au_cursor_hold(self, client, filename):
        self.tick_clients()

    @execute_with_client()
    def au_cursor_moved(self, client, filename):
        self.tick_clients()

    def fun_en_tick(self, timer):
        self.tick_clients()

    @execute_with_client()
    def au_buf_enter(self, client, filename):
        # Only set up to trigger the creation of a client
        pass

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
