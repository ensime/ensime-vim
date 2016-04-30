import unittest
import sys
import os


def fakemodule_autocmd(arg):
    return arg


class fakemodule(object):

    @staticmethod
    def plugin(arg):
        return arg

    @staticmethod
    def autocmd(arg, **kwargs):
        return fakemodule_autocmd

    @staticmethod
    def command(arg, **kwargs):
        return fakemodule_autocmd

    @staticmethod
    def function(arg, **kwargs):
        return fakemodule_autocmd

sys.modules["neovim"] = fakemodule
sys.path.insert(0, os.path.dirname(__file__) + '/../rplugin/python')
from ensime import Ensime
import ensime_launcher
from mock import MagicMock


class TestVimBuffer:

    def __init__(self):
        self.name = __file__


class TestVimWindow:

    def __init__(self):
        self.cursor = [0, 0]


class TestVimCurrent:

    def __init__(self):
        self.window = TestVimWindow()
        self.buffer = TestVimBuffer()


class TestVim:

    def __init__(self):
        self.current = TestVimCurrent()

    def command(self, what):
        return None

    def eval(self, what):
        return "/tmp"


class TestEnsime(unittest.TestCase):

    def setUp(self):
        vim = TestVim()
        self.vim = vim
        vim.command = MagicMock()
        self.ensime = Ensime(vim)
        self.poll = None

    def test_util(self):
        path = "/tmp/my/little/dir"
        test_file = path + "/test"
        if os.path.exists(test_file):
            os.remove(test_file)
        if os.path.exists(path):
            os.rmdir(path)
        ensime_launcher.Util.mkdir_p(path)
        assert(os.path.exists(path))
        if os.path.exists(test_file):
            os.remove(test_file)
        ensime_launcher.Util.write_file(test_file, "blah")
        assert(os.path.exists(test_file))
        os.remove(test_file)
        os.rmdir(path)

    def do_test_setup_ws(self):
        launcher = ensime_launcher.EnsimeLauncher(TestVim())
        from ensime import EnsimeClient, Ensime
        client = EnsimeClient(TestVim(), launcher, "spec/conf")
        client.setup()

        def false_method(what):
            return False
        client.module_exists = false_method
        client.setup()
        ensime = Ensime(TestVim())
        assert(ensime.client_status("spec/conf") == "ready")

    def test_ensime_process(self):
        a = self

        class FakeProcess:

            def __init__(self):
                self.pid = 1

            def poll(self):
                return a.poll
        process = ensime_launcher.EnsimeProcess(
            "/tmp/", FakeProcess(), "/tmp/log", None)
        assert(process.is_running())
        self.poll = True
        assert(not process.is_ready())
        self.poll = None
        assert(not process.is_ready())
        import socket
        old_socket = socket.socket

        class FakeSocket:

            def __init__(self, a=None, b=None):
                None

            def connect(self, a):
                None

            def send(self, a):
                None

            def recv(self, a):
                None

            def settimeout(self, t):
                None

            def setsockopt(self, *t):
                None

            def close(self):
                None
        socket.socket = FakeSocket
        import websocket

        def noop(a=None):
            None
        websocket.create_connection = noop
        ensime_launcher.Util.write_file("/tmp/http", "42")
        assert(process.is_ready())
        self.do_test_setup_ws()
        socket.socket = old_socket
        assert(not process.aborted())
        stop_exception = False
        try:
            process.stop()
        except:
            stop_exception = True
        assert(stop_exception)

    def test_ensime_launcher(self):
        launcher = ensime_launcher.EnsimeLauncher(TestVim())
        conf_path = "/tmp/myconf"
        ensime_launcher.Util.write_file(
            conf_path,
            "blah 42 :scala-version test :java-home /usr :cache-dir /tmp "
            ":java-flags none")
        conf = launcher.parse_conf(conf_path)
        assert(conf['blah'] == '42')
        test_dir = os.environ['HOME'] + \
            "/.config/classpath_project_ensime/test"
        ensime_launcher.Util.mkdir_p(test_dir)
        assert(launcher.classpath_project_dir("test") == test_dir)
        assert(launcher.build_sbt("test", "file") is not None)
        ensime_launcher.Util.write_file(test_dir + "/classpath", "")
        launcher.launch(conf_path)
        launcher.generate_classpath("test", "classpath")
        try:
            launcher.load_classpath("42", "")
        except:
            None

    def test_ensime_init_path(self):
        from ensime import EnsimeInitPath
        assert(EnsimeInitPath() is None)
        original_abspath = os.path.abspath

        def new_abspath(path):
            return '/autoload/ensime.vim.py'
        os.path.abspath = new_abspath
        assert(EnsimeInitPath() is None)
        os.path.abspath = original_abspath

    def test_error(self):
        from ensime import Error
        error = Error("/tmp", "message", 1, 2, 4)
        assert(error.includes("/tmp", [1, 3]))

    def test_ensime_client(self):
        self.test_ensime_launcher()
        from ensime import EnsimeClient
        launcher = ensime_launcher.EnsimeLauncher(TestVim())
        client = EnsimeClient(TestVim(), launcher, "spec/conf")
        assert(not client.module_exists("unexisting_module"))
        assert(client.module_exists("os"))
        client.teardown("/tmp/")
        assert(client.path_start_size("/tmp") is None)
        assert(client.unqueue("/tmp") is None)
        client.queue.put(None)
        assert(client.unqueue("/tmp") is None)
        client.queue.put('{"payload":{"typehint":"blah"}}')
        assert(client.unqueue("/tmp") is None)
        client.setup()
        assert(client.complete() is None)
        notes = [{"line": 0, "col": 0, "beg": 0,
                  "end": 1, "msg": "msg", "file": "file"}]
        client.handle_new_scala_notes_event(notes)
        ensime_launcher.Util.write_file("/tmp/http", "42")
        for typehint in ["NewScalaNotesEvent",
                         "SymbolInfo",
                         "IndexerReadyEvent",
                         "AnalyzerReadyEvent",
                         "BasicTypeInfo",
                         "StringResponse",
                         "CompletionInfoList"]:
            client.handle_payload({
                "typehint": typehint,
                "notes": notes,
                "declPos": {"file": "none"},
                "fullName": "none",
                "text": "none",
                "completions": []})
        client.open_definition = True
        client.handle_payload({
            "typehint": "SymbolInfo",
            "notes": notes,
            "declPos": {"file": "none"},
            "fullName": "none",
            "text": "none",
            "completions": []})
        assert(client.ensime.http_port() == 42)

        class FakeSocket:

            def __init__(self):
                self.first = True

            def recv(self, n):
                if self.first:
                    self.first = False
                    return 'n'
                else:
                    return ''

        client.read_line(FakeSocket())
        assert(client.complete_func('1', "") == 0)
        client.vim.current.window.cursor[1] = 2
        assert(client.complete_func('1', "") == 1)
        client.vim.current.window.cursor[1] = 0
        client.suggests = ["a"]
        assert(client.complete_func(0, "") == ['a'])
        client.suggests = None
        client.complete_timeout = 0.1
        print(client.complete_func(0, ""))
        client.handle_string_response({"text": "lol"})
        client.browse = True
        old_get = os.environ.get

        def new_get(blah):
            return "echo"
        os.environ.get = new_get
        client.handle_string_response({"text": "lol"})
        os.environ.get = old_get
        assert(client.type_check("/tmp") is None)
        assert(client.on_cursor_hold("/tmp") is None)
        assert(client.cursor_moved("/tmp") is None)
        assert(client.get_error_at([0, 0]) is None)
        from ensime import Error
        error = Error("/tmp", "a", 0, 0, 10)
        client.errors.append(error)
        assert(client.get_error_at([0, 0]) == error)
        assert(client.display_error_if_necessary("/tmp") is None)
        client.tell_module_missing("module")
        assert(client.doc_browse(None) is None)
        assert(client.type_check_cmd([]) is None)
        assert(client.type([]) is None)
        assert(client.symbol_at_point_req(None) is None)
        assert(client.symbol(None) is None)
        assert(client.open_declaration(None) is None)
        assert(client.do_no_teardown(None) is None)
        client.ws = True
        assert(client.cursor_moved("") is None)

        class FakeWS:

            def recv(self):
                return ""

            def send(self, blah):
                None
        client.ws = FakeWS()
        client.x = 0

        def once():
            client.x = client.x + 1
            return client.x <= 1
        assert(client.unqueue_poll(once, 0) is None)
        assert(client.send("blah") is None)

    def test_ensime(self):
        self.test_ensime_launcher()
        assert(self.ensime.client_status("spec/conf", False) == "unloaded")
        assert(self.ensime.client_status("spec/conf") == "startup")
        old_poll = self.ensime.client_for(
            "spec/conf", True).ensime.process.poll

        def fake_poll():
            return "a"
        _ensime = self.ensime.client_for("spec/conf", True).ensime
        _ensime.process.poll = fake_poll
        assert(self.ensime.client_status("spec/conf") == "aborted")
        old_aborted = _ensime.aborted

        def fake_aborted():
            return False
        _ensime.aborted = fake_aborted
        assert(self.ensime.client_status("spec/conf") == "stopped")
        _ensime.aborted = old_aborted
        self.ensime.client_for(
            "spec/conf",
            True).ensime.process.poll = old_poll
        assert(self.ensime.find_config_path("/tmp/") is None)
        assert(len(self.ensime.client_keys()) == 1)
        assert(self.ensime.with_current_client(lambda c: None) is None)
        old_current_client = self.ensime.current_client

        class FakeClient:

            def symbol(self, a, b):
                None

        def fake_current_client():
            return FakeClient()
        self.ensime.current_client = fake_current_client
        assert(self.ensime.with_current_client(lambda c: None) is None)
        self.ensime.com_en_symbol([])
        old_teardown = self.ensime.teardown
        self.ensime.teardown = fake_current_client
        self.ensime.au_vimleave("")
        self.ensime.current_client = old_current_client
        self.ensime.teardown = old_teardown

        assert(self.ensime.teardown() is None)
        for com in [
                "en_no_teardown",
                "en_type_check",
                "en_type",
                "en_declaration",
                "en_doc_uri",
                "en_doc_browse",
                "en_clients"]:
            assert(getattr(self.ensime, 'com_' + com)([]) is None)
        for au in ["buf_write_post", "cursor_hold", "cursor_moved"]:
            assert(getattr(self.ensime, 'au_' + au)("") is None)
        assert(self.ensime.fun_en_complete_func(["a", "b"], None) == [])
        ensime_launcher.Util.write_file(
            "/tmp/.ensime",
            "blah 42 :scala-version test :java-home /usr :cache-dir /tmp "
            ":java-flags none")
        assert(self.ensime.current_client() is not None)
        os.remove("/tmp/.ensime")


#    def test_init(self):
#        self.vim.command.assert_called_once_with(
#            "highlight EnError ctermbg=red")
#    def test_get_cache_port(self):
#        with self.assertRaises(IOError):
#            self.ensime.current_client().get_cache_port("42")
#    def test_path_start_size(self):
#        self.vim.command = MagicMock()
#        self.ensime.current_client().path_start_size("blah")
#        assert((('normal e',), {}) in self.vim.command.call_args_list)
#        assert((('normal b',), {}) in self.vim.command.call_args_list)

if __name__ == '__main__':
    unittest.main()
