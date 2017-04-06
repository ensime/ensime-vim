# coding: utf-8

import errno
import os
import shutil
import signal
import socket
import subprocess
import time

from abc import ABCMeta, abstractmethod
from fnmatch import fnmatch
from string import Template

from ensime_shared.config import BOOTSTRAPS_ROOT
from ensime_shared.errors import InvalidJavaPathError, LaunchError
from ensime_shared.util import catch, Util


class EnsimeProcess(object):

    def __init__(self, cache_dir, process, log_path, cleanup):
        self.log_path = log_path
        self.cache_dir = cache_dir
        self.process = process
        self.__stopped_manually = False
        self.__cleanup = cleanup

    def stop(self):
        if self.process is None:
            return
        os.kill(self.process.pid, signal.SIGTERM)
        self.__cleanup()
        self.__stopped_manually = True

    def aborted(self):
        return not (self.__stopped_manually or self.is_running())

    def is_running(self):
        # What? If there's no process, it's running? This is mad confusing.
        return self.process is None or self.process.poll() is None

    def is_ready(self):
        if not self.is_running():
            return False
        try:
            port = self.http_port()
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect(("127.0.0.1", port))
            s.close()
            return True
        except:
            return False

    def http_port(self):
        return int(Util.read_file(os.path.join(self.cache_dir, "http")))


class EnsimeLauncher(object):
    """Launches ENSIME processes, installing the server if needed."""

    def __init__(self, vim, config, base_dir=BOOTSTRAPS_ROOT):
        self.config = config

        # If an ENSIME assembly jar is in place, it takes launch precedence
        assembly = AssemblyJar(config, base_dir)

        if assembly.isinstalled():
            self.strategy = assembly
        elif self.config.get('ensime-server-jars'):
            self.strategy = DotEnsimeLauncher(config)
        else:
            self.strategy = SbtBootstrap(vim, config, base_dir)

        self._remove_legacy_bootstrap()

    # Design musing: we could return a Boolean success value then encapsulate
    # and expose more lifecycle control through EnsimeLauncher, instead of
    # pushing up an EnsimeProcess and leaving callers with the responsibilities
    # of dealing with that. EnsimeClient needs a bunch of (worthwhile) refactoring
    # before this could happen, though.
    def launch(self):
        # This is legacy -- what is it really accomplishing?
        cache_dir = self.config['cache-dir'],
        process = EnsimeProcess(cache_dir, None, None, lambda: None)
        if process.is_ready():
            return process

        if not self.strategy.isinstalled():
            if not self.strategy.install():  # TODO: This should be an exception
                return None

        return self.strategy.launch()

    @staticmethod
    def _remove_legacy_bootstrap():
        """Remove bootstrap projects from old path, they'd be really stale by now."""
        home = os.environ['HOME']
        old_base_dir = os.path.join(home, '.config', 'classpath_project_ensime')
        if os.path.isdir(old_base_dir):
            shutil.rmtree(old_base_dir, ignore_errors=True)


class LaunchStrategy:
    """A strategy for how to install and launch the ENSIME server.

    Newer build tool versions like sbt-ensime since 1.12.0 may support
    installing the server and publishing the jar locations in ``.ensime``
    so that clients don't need to handle installation. Strategies exist to
    support older versions and build tools that haven't caught up to this.

    Args:
        config (ProjectConfig): Configuration for the server instance's project.
    """
    __metaclass__ = ABCMeta

    def __init__(self, config):
        self.config = config

    @abstractmethod
    def isinstalled(self):
        """Whether ENSIME has been installed satisfactorily for the launcher."""
        raise NotImplementedError

    @abstractmethod
    def install(self):
        """Installs ENSIME server if needed.

        Returns:
            bool: Whether the installation completed successfully.
        """
        raise NotImplementedError

    @abstractmethod
    def launch(self):
        """Launches a server instance for the configured project.

        Returns:
            EnsimeProcess: A process handle for the launched server.

        Raises:
            LaunchError: If server can't be launched according to the strategy.
        """
        raise NotImplementedError

    def _start_process(self, classpath):
        """Given a classpath prepared for running ENSIME, spawns a server process
        in a way that is otherwise agnostic to how the strategy installs ENSIME.

        Args:
            classpath (list of str): list of paths to jars or directories
            (Within this function the list is joined with a system dependent
            path separator to create a single string argument to suitable to 
            pass to ``java -cp`` as a classpath)

        Returns:
            EnsimeProcess: A process handle for the launched server.
        """
        cache_dir = self.config['cache-dir']
        java_flags = self.config['java-flags']

        Util.mkdir_p(cache_dir)
        log_path = os.path.join(cache_dir, "server.log")
        log = open(log_path, "w")
        null = open(os.devnull, "r")
        java = os.path.join(self.config['java-home'], 'bin', 'java' if os.name != 'nt' else 'java.exe')

        if not os.path.exists(java):
            raise InvalidJavaPathError(errno.ENOENT, 'No such file or directory', java)
        elif not os.access(java, os.X_OK):
            raise InvalidJavaPathError(errno.EACCES, 'Permission denied', java)

        args = (
            [java, "-cp", (':' if os.name != 'nt' else ';').join(classpath)] +
            [a for a in java_flags if a] +
            ["-Densime.config={}".format(self.config.filepath),
             "org.ensime.server.Server"])
        process = subprocess.Popen(
            args,
            stdin=null,
            stdout=log,
            stderr=subprocess.STDOUT)
        pid_path = os.path.join(cache_dir, "server.pid")
        Util.write_file(pid_path, str(process.pid))

        def on_stop():
            log.close()
            null.close()
            with catch(Exception):
                os.remove(pid_path)

        return EnsimeProcess(cache_dir, process, log_path, on_stop)


class AssemblyJar(LaunchStrategy):
    """Launches an ENSIME assembly jar if found in ``~/.config/ensime-vim`` (or
    base_dir). This is intended for ad hoc local development builds, or behind-
    the-firewall corporate installs. See:

    http://ensime.github.io/contributing/#manual-qa-testing
    """

    def __init__(self, config, base_dir):
        super(AssemblyJar, self).__init__(config)
        self.base_dir = os.path.realpath(base_dir)
        self.jar_path = None
        self.toolsjar = os.path.join(config['java-home'], 'lib', 'tools.jar')

    def isinstalled(self):
        if not os.path.exists(self.base_dir):
            return False
        scala_minor = self.config['scala-version'][:4]
        for fname in os.listdir(self.base_dir):
            if fnmatch(fname, "ensime_" + scala_minor + "*-assembly.jar"):
                self.jar_path = os.path.join(self.base_dir, fname)
                return True

        return False

    def install(self):
        # Nothing to do for this strategy, server is built in the jar
        return True

    def launch(self):
        if not self.isinstalled():
            raise LaunchError('ENSIME assembly jar not found in {}'.format(self.base_dir))

        classpath = [self.jar_path, self.toolsjar] + self.config['scala-compiler-jars']
        return self._start_process(classpath)


class DotEnsimeLauncher(LaunchStrategy):
    """Launches a pre-installed ENSIME via jar paths in ``.ensime``."""

    def __init__(self, config):
        super(DotEnsimeLauncher, self).__init__(config)
        server_jars = self.config['ensime-server-jars']
        compiler_jars = self.config['scala-compiler-jars']

        # Order is important so that monkeys takes precedence
        self.classpath = server_jars + compiler_jars

    def isinstalled(self):
        return all([os.path.exists(jar) for jar in self.classpath])

    def install(self):
        # Nothing to do, the build tool has done it if we're in this strategy
        return True

    def launch(self):
        if not self.isinstalled():
            raise LaunchError('Some jars reported by .ensime do not exist: {}'
                              .format(self.classpath))
        return self._start_process(self.classpath)


class SbtBootstrap(LaunchStrategy):
    """Install ENSIME via sbt with a bootstrap project.

    This strategy is intended for versions of sbt-ensime prior to 1.12.0
    and other build tools that don't install ENSIME & report its jar paths.

    Support for this installation method will be dropped after users and build
    tools have some time to catch up. Consider it deprecated.
    """
    ENSIME_V1 = '1.0.1'
    SBT_VERSION = '0.13.13'
    SBT_COURSIER_COORDS = ('io.get-coursier', 'sbt-coursier', '1.0.0-M15')

    def __init__(self, vim, config, base_dir):
        super(SbtBootstrap, self).__init__(config)
        self.vim = vim
        self.ensime_version = self.ENSIME_V1
        self.scala_minor = self.config['scala-version'][:4]
        self.base_dir = os.path.realpath(base_dir)
        self.toolsjar = os.path.join(self.config['java-home'], 'lib', 'tools.jar')
        self.classpath_file = os.path.join(self.base_dir,
                                           self.scala_minor,
                                           self.ensime_version,
                                           'classpath')

    def launch(self):
        if not self.isinstalled():
            raise LaunchError('Bootstrap classpath file does not exist at {}'
                              .format(self.classpath_file))

        classpath = Util.read_file(self.classpath_file) + ':' + self.toolsjar
        return self._start_process(classpath)

    # TODO: should maybe check if the build.sbt matches spec (versions, etc.)
    def isinstalled(self):
        return os.path.exists(self.classpath_file)

    def install(self):
        """Installs ENSIME server with a bootstrap sbt project and generates its classpath."""
        project_dir = os.path.dirname(self.classpath_file)
        sbt_plugin = """addSbtPlugin("{0}" % "{1}" % "{2}")"""

        Util.mkdir_p(project_dir)
        Util.mkdir_p(os.path.join(project_dir, "project"))
        Util.write_file(
            os.path.join(project_dir, "build.sbt"),
            self.build_sbt())
        Util.write_file(
            os.path.join(project_dir, "project", "build.properties"),
            "sbt.version={}".format(self.SBT_VERSION))
        Util.write_file(
            os.path.join(project_dir, "project", "plugins.sbt"),
            sbt_plugin.format(*self.SBT_COURSIER_COORDS))

        # Synchronous update of the classpath via sbt
        # see https://github.com/ensime/ensime-vim/issues/29
        cd_cmd = "cd {}".format(project_dir)
        sbt_cmd = "sbt -Dsbt.log.noformat=true -batch saveClasspath"

        if int(self.vim.eval("has('nvim')")):
            import tempfile
            import re
            tmp_dir = tempfile.gettempdir()
            flag_file = "{}/ensime-vim-classpath.flag".format(tmp_dir)
            self.vim.command("echo 'Waiting for generation of classpath...'")
            if re.match(".+fish$", self.vim.eval("&shell")):
                sbt_cmd += "; echo $status > {}".format(flag_file)
                self.vim.command("terminal {}; and {}".format(cd_cmd, sbt_cmd))
            else:
                sbt_cmd += "; echo $? > {}".format(flag_file)
                self.vim.command("terminal ({} && {})".format(cd_cmd, sbt_cmd))

            # Block execution when sbt is run
            waiting_for_flag = True
            while waiting_for_flag:
                waiting_for_flag = not os.path.isfile(flag_file)
                if not waiting_for_flag:
                    with open(flag_file, "r") as f:
                        rtcode = f.readline()
                    os.remove(flag_file)
                    if rtcode and int(rtcode) != 0:  # error
                        self.vim.command(
                            "echo 'Something wrong happened, check the "
                            "execution log...'")
                        return None
                else:
                    time.sleep(0.2)
        else:
            self.vim.command("!({} && {})".format(cd_cmd, sbt_cmd))

        success = self.reorder_classpath(self.classpath_file)
        if not success:
            self.vim.command("echo 'Classpath ordering failed.'")

        return True

    def build_sbt(self):
        src = r"""
import sbt._
import IO._
import java.io._
scalaVersion := "$scala_version"
ivyScala := ivyScala.value map { _.copy(overrideScalaVersion = true) }

// Allows local builds of scala
resolvers += Resolver.mavenLocal
resolvers += Resolver.sonatypeRepo("snapshots")
resolvers += "Typesafe repository" at "http://repo.typesafe.com/typesafe/releases/"
resolvers += "Akka Repo" at "http://repo.akka.io/repository"

// For java support
resolvers += "NetBeans" at "http://bits.netbeans.org/nexus/content/groups/netbeans"

libraryDependencies ++= Seq(
  "org.ensime" %% "ensime" % "$version",
  "org.scala-lang" % "scala-compiler" % scalaVersion.value force(),
  "org.scala-lang" % "scala-reflect" % scalaVersion.value force(),
  "org.scala-lang" % "scalap" % scalaVersion.value force()
)

val saveClasspathTask = TaskKey[Unit]("saveClasspath", "Save the classpath to a file")

saveClasspathTask := {
  val managed = (managedClasspath in Runtime).value.map(_.data.getAbsolutePath)
  val unmanaged = (unmanagedClasspath in Runtime).value.map(_.data.getAbsolutePath)
  val out = file("$classpath_file")
  write(out, (unmanaged ++ managed).mkString(File.pathSeparator))
}"""
        replace = {
            "scala_version": self.config['scala-version'],
            "version": self.ensime_version,
            "classpath_file": self.classpath_file,
        }

        return Template(src).substitute(replace)

    def reorder_classpath(self, classpath_file):
        """Reorder classpath and put monkeys-jar in the first place."""
        success = False

        with catch((IOError, OSError)):
            with open(classpath_file, "r") as f:
                classpath = f.readline()

            # Proceed if classpath is non-empty
            if classpath:
                units = classpath.split(":")
                reordered_units = []
                for unit in units:
                    if "monkeys" in unit:
                        reordered_units.insert(0, unit)
                    else:
                        reordered_units.append(unit)
                reordered_classpath = ":".join(reordered_units)

                with open(classpath_file, "w") as f:
                    f.write(reordered_classpath)

            success = True

        return success
