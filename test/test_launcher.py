# coding: utf-8

import pytest
from mock import patch
from py import path

from ensime_shared.config import ProjectConfig
from ensime_shared.errors import LaunchError
from ensime_shared.launcher import (AssemblyJar, DotEnsimeLauncher,
                                    EnsimeLauncher, SbtBootstrap)

CONFROOT = path.local(__file__).dirpath() / 'resources'


def test_determines_launch_strategy(tmpdir, vim):
    base_dir = tmpdir.strpath
    bootstrap_conf = config('test-bootstrap.conf')

    launcher = EnsimeLauncher(vim, config('test-server-jars.conf'), base_dir)
    assert isinstance(launcher.strategy, DotEnsimeLauncher)

    launcher = EnsimeLauncher(vim, bootstrap_conf, base_dir)
    assert isinstance(launcher.strategy, SbtBootstrap)

    create_stub_assembly_jar(base_dir, bootstrap_conf)
    launcher = EnsimeLauncher(vim, bootstrap_conf, base_dir)
    assert isinstance(launcher.strategy, AssemblyJar)


class TestAssemblyJarStrategy:
    @pytest.fixture
    def strategy(self, tmpdir):
        return AssemblyJar(config('test-bootstrap.conf'), base_dir=tmpdir.strpath)

    @pytest.fixture
    def assemblyjar(self, strategy):
        create_stub_assembly_jar(strategy.base_dir, strategy.config)

    def test_isinstalled_if_jar_file_present(self, strategy):
        assert not strategy.isinstalled()
        self.assemblyjar(strategy)
        assert strategy.isinstalled()

    def test_isinstalled_when_base_dir_does_not_exist(self, tmpdir):
        bogus = tmpdir / 'nonexisting'
        strategy = AssemblyJar(config('test-bootstrap.conf'), base_dir=bogus.strpath)
        assert not strategy.isinstalled()

    def test_launch_constructs_classpath(self, strategy, assemblyjar):
        assert strategy.isinstalled()
        with patch.object(strategy, '_start_process', autospec=True) as start:
            strategy.launch()

        assert start.call_count == 1
        args, _kwargs = start.call_args
        classpath = args[0].split(':')
        assert classpath == [strategy.jar_path,
                             strategy.toolsjar,
                             ] + strategy.config['scala-compiler-jars']

    def test_launch_raises_when_not_installed(self, strategy):
        assert not strategy.isinstalled()
        with pytest.raises(LaunchError) as excinfo:
            strategy.launch()
        assert 'assembly jar not found' in str(excinfo.value)


class TestDotEnsimeStrategy:
    @pytest.fixture
    def strategy(self):
        return DotEnsimeLauncher(config('test-server-jars.conf'))

    def test_adds_server_jars_to_classpath(self, strategy):
        server_jars = strategy.config['ensime-server-jars']
        assert all([jar in strategy.classpath for jar in server_jars])

    def test_isinstalled_if_jars_present(self, strategy):
        assert not strategy.isinstalled()
        # Stub the existence of the server+compiler jars
        with patch('os.path.exists', return_value=True):
            assert strategy.isinstalled()

    def test_launch_constructs_classpath(self, strategy):
        with patch.object(strategy, '_start_process', autospec=True) as start:
            with patch.object(strategy, 'isinstalled', return_value=True):
                strategy.launch()

        assert start.call_count == 1
        args, _kwargs = start.call_args
        classpath = args[0].split(':')
        assert classpath == strategy.classpath

    def test_launch_raises_when_not_installed(self, strategy):
        assert not strategy.isinstalled()
        with pytest.raises(LaunchError) as excinfo:
            strategy.launch()
        assert 'Some jars reported by .ensime do not exist' in str(excinfo.value)


class TestSbtBootstrapStrategy:
    """
    Minimally tested because unit testing this would be obnoxious and brittle...
    """

    @pytest.fixture
    def strategy(self, tmpdir, vim):
        conf = config('test-bootstrap.conf')
        return SbtBootstrap(vim, conf, base_dir=tmpdir.strpath)

    def test_isinstalled_if_classpath_file_present(self, strategy):
        assert not strategy.isinstalled()

    def test_launch_raises_when_not_installed(self, strategy):
        assert not strategy.isinstalled()
        with pytest.raises(LaunchError) as excinfo:
            strategy.launch()
        assert 'Bootstrap classpath file does not exist' in str(excinfo.value)


# -----------------------------------------------------------------------
# -                               Helpers                               -
# -----------------------------------------------------------------------

def config(conffile):
    return ProjectConfig(CONFROOT.join(conffile).strpath)


def create_stub_assembly_jar(indir, projectconfig):
    """Touches assembly jar file path in indir and returns the path."""
    scala_minor = projectconfig['scala-version'][:4]
    name = 'ensime_{}-assembly.jar'.format(scala_minor)
    return path.local(indir).ensure(name).realpath
