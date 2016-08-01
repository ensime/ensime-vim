import os
import shutil
import subprocess
from os import path

import psutil
from lettuce import step, world

from ensime_shared.config import ProjectConfig


@step('no server bootstrap project exists')
def recreate_boostrap_project_path(step):
    bootstraps = world.bootstrap_projects_path
    shutil.rmtree(bootstraps)
    os.mkdir(bootstraps)


@step('I have installed ENSIME server')
def install_ensime(step):
    """Rely on the existing test environment state to save some time..."""
    # step.given('no server bootstrap project exists')
    # step.given('invoke server installation')
    pass


@step('have created a valid .ensime project config')
def set_valid_dot_ensime(step):
    with world.project_directory() as here:
        failed = subprocess.call(['sbt', 'ensimeConfig'])
        assert not bool(failed), \
            'sbt ensimeConfig exited with status {}'.format(failed)

        dotensime = path.join(here, '.ensime')
        config = ProjectConfig.parse(dotensime)
        assert config.get('scala-version') == '2.11.8'


@step('I edit a Scala file')
def edit_scala_file(step):
    world.vim.command('edit src/main/scala/Main.scala')


@step('invoke server installation')
def run_en_install(step):
    world.vim.command('EnInstall')


@step('ENSIME should be installed')
def server_is_installed(step):
    # TODO: use bootstrap_projects_path when that works
    classpath_path = path.expanduser('~/.config/ensime-vim/2.11.8/classpath')
    assert path.exists(path.realpath(classpath_path))


@step('the server should be started')
def server_is_started(step):
    pid_path = path.join(world.project_path, '.ensime_cache', 'server.pid')
    assert path.exists(path.realpath(pid_path))

    with open(pid_path) as pidfile:
        pid = int(pidfile.read().strip())

    assert psutil.pid_exists(pid)
    proc = psutil.Process(pid)
    assert 'ensime' in ' '.join(proc.cmdline()), proc.cmdline()
