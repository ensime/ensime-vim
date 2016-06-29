import os
import signal
import socket
import subprocess
import time
import shutil
import fnmatch

import sexpdata

from ensime_shared.util import Util, catch


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

join = os.path.join
home = os.environ["HOME"]

# Use a new path that is clearer and more user-friendly
_default_base_dir = join(home, ".config/ensime-vim/")
_old_base_dir = join(home, ".config/classpath_project_ensime")
if os.path.isdir(_old_base_dir):
    shutil.move(_old_base_dir, _default_base_dir)


class EnsimeLauncher(object):

    def __init__(self, vim, config_path, base_dir=_default_base_dir):
        self.vim = vim
        self._config_path = os.path.abspath(config_path)
        self.config = self.parse_config(self._config_path)
        self.base_dir = os.path.abspath(base_dir)
        self.ensime_version = "1.0.0"
        self.sbt_version = "0.13.11"
        self.classpath_file = os.path.join(self.base_dir,
                                           self.config['scala-version'],
                                           'classpath')

    def launch(self):
        cache_dir = self.config['cache-dir'],
        process = EnsimeProcess(cache_dir, None, None, lambda: None)
        if process.is_ready():
            return process

        classpath = self.load_classpath()
        return self.start_process(classpath) if classpath else None

    def load_classpath(self):
        if not os.path.exists(self.classpath_file):
            if not self.generate_classpath():
                return None

        classpath = "{}:{}/lib/tools.jar".format(
            Util.read_file(self.classpath_file), self.config['java-home'])

        # Allow override with a local development server jar, see:
        # http://ensime.github.io/contributing/#manual-qa-testing
        scala_minor = self.config['scala-version'][:4]
        for x in os.listdir(self.base_dir):
            if fnmatch.fnmatch(x, "ensime_" + scala_minor + "*-assembly.jar"):
                classpath = os.path.join(self.base_dir, x) + ":" + classpath

        return classpath

    def start_process(self, classpath):
        cache_dir = self.config['cache-dir']
        java_home = self.config['java-home']
        java_flags = self.config['java-flags']

        Util.mkdir_p(cache_dir)
        log_path = os.path.join(cache_dir, "server.log")
        log = open(log_path, "w")
        null = open("/dev/null", "r")
        args = (
            [os.path.join(java_home, "bin", "java")] +
            ["-cp", classpath] +
            [a for a in java_flags if a != ""] +
            ["-Densime.config={}".format(self._config_path),
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
            with catch(Exception, lambda e: None):
                os.remove(pid_path)
        return EnsimeProcess(cache_dir, process, log_path, on_stop)

    def generate_classpath(self):
        project_dir = os.path.dirname(self.classpath_file)
        Util.mkdir_p(project_dir)
        Util.mkdir_p(os.path.join(project_dir, "project"))
        Util.write_file(
            os.path.join(project_dir, "build.sbt"),
            self.build_sbt())
        Util.write_file(
            os.path.join(project_dir, "project", "build.properties"),
            "sbt.version={}".format(self.sbt_version))
        Util.write_file(
            os.path.join(project_dir, "project", "plugins.sbt"),
            """addSbtPlugin("io.get-coursier" % "sbt-coursier" % "1.0.0-M11")""")

        # Synchronous update of the classpath via sbt
        # see https://github.com/ensime/ensime-vim/issues/29
        cd_cmd = "cd {}".format(project_dir)
        sbt_cmd = "sbt -Dsbt.log.noformat=true -batch saveClasspath"
        inside_nvim = int(self.vim.eval("has('nvim')"))
        if inside_nvim:
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
        src = """
import sbt._
import IO._
import java.io._
scalaVersion := "%(scala_version)"
ivyScala := ivyScala.value map { _.copy(overrideScalaVersion = true) }

// Allows local builds of scala
resolvers += Resolver.mavenLocal
resolvers += Resolver.sonatypeRepo("snapshots")
resolvers += "Typesafe repository" at "http://repo.typesafe.com/typesafe/releases/"
resolvers += "Akka Repo" at "http://repo.akka.io/repository"

// For java support
resolvers += "NetBeans" at "http://bits.netbeans.org/nexus/content/groups/netbeans"

libraryDependencies ++= Seq(
  "org.ensime" %% "ensime" % "%(version)",
  "org.scala-lang" % "scala-compiler" % scalaVersion.value force(),
  "org.scala-lang" % "scala-reflect" % scalaVersion.value force(),
  "org.scala-lang" % "scalap" % scalaVersion.value force()
)

val saveClasspathTask = TaskKey[Unit]("saveClasspath", "Save the classpath to a file")

saveClasspathTask := {
  val managed = (managedClasspath in Runtime).value.map(_.data.getAbsolutePath)
  val unmanaged = (unmanagedClasspath in Runtime).value.map(_.data.getAbsolutePath)
  val out = file("%(classpath_file)")
  write(out, (unmanaged ++ managed).mkString(File.pathSeparator))
}"""
        replace = {
            "scala_version": self.config['scala-version'],
            "version": self.ensime_version,
            "classpath_file": self.classpath_file,
        }
        for k in replace.keys():
            src = src.replace("%(" + k + ")", replace[k])
        return src

    @staticmethod
    def parse_config(path):
        """Parse an .ensime project config file, from S-expressions to dict."""

        def paired(iterable):
            """s -> (s0, s1), (s2, s3), (s4, s5), ..."""
            cursor = iter(iterable)
            return zip(cursor, cursor)

        def unwrap_if_sexp_symbol(datum):
            """
            Convert Symbol(':key') to ':key' (Symbol isn't hashable for dict keys).
            """
            return datum.value() if isinstance(datum, sexpdata.Symbol) else datum

        def sexp2dict(sexps):
            """
            Transforms a nested list structure from sexpdata to dict.

            NOTE: This probably isn't general for all S-expression shapes parsed by
            sexpdata, focused only on .ensime thus far.
            """
            newdict = {}

            # Turn flat list into associative pairs
            for key, value in paired(sexps):
                key = str(unwrap_if_sexp_symbol(key)).lstrip(':')

                # Recursively transform nested lists
                if isinstance(value, list) and value and isinstance(value[0], list):
                    newdict[key] = [sexp2dict(value[0])]
                else:
                    newdict[key] = value

            return newdict

        conf = sexpdata.loads(Util.read_file(path))
        return sexp2dict(conf)

    def reorder_classpath(self, classpath_file):
        """Reorder classpath and put monkeys-jar in the first place."""
        success = False

        with catch((IOError, OSError), lambda e: None):
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
