"""
Shared test setup such as setup/teardown hooks and fixtures.

This file is loaded automatically by Lettuce, see:
    http://lettuce.it/reference/terrain.html
"""

import os
import shutil
import sys
import tempfile
from contextlib import contextmanager
from os import path

import neovim
from lettuce import after, before, world

DEBUG = os.environ.get('DEBUG')
LISTEN_ADDRESS = os.environ.get('NVIM_LISTEN_ADDRESS')

FEATURESROOT = path.dirname(path.abspath(__file__))

neovim.setup_logging()


# TODO: Will we need a @before.each_feature that nukes .ensime_cache, etc.?
@before.all
def setup_test_environment():
    world.project_path = path.join(tempfile.mkdtemp(), 'testproject')
    world.bootstrap_projects_path = tempfile.mkdtemp()

    resources = path.realpath(path.join(FEATURESROOT, '..', 'resources'))
    shutil.copytree(path.join(resources, 'testproject'), world.project_path)
    world.vimrc = path.join(resources, 'vimrc')


@after.all
def teardown_test_environment(_total):
    if DEBUG:
        print('-' * 80)
        print('Project: ' + world.project_path)
        print('Bootstraps: ' + world.bootstrap_projects_path)
        print('Left for inspection.')
        print('-' * 80)
    else:
        world.vim.quit()  # Implicitly shut server down
        shutil.rmtree(world.project_path)
        shutil.rmtree(world.bootstrap_projects_path)


@before.each_scenario
def reset_vim(_scenario):
    # Boilerplate to set up embedded Neovim test instance, by default, allowing
    # separate process optionally.
    if LISTEN_ADDRESS:
        world.vim = neovim.attach('socket', path=LISTEN_ADDRESS)
    else:
        embed_cmd = ['nvim', '-u', world.vimrc, '-i', 'NONE', '--embed']
        world.vim = neovim.attach('child', argv=embed_cmd)

    world.vim.input(CLEANUP_FUNC.format(vimrc=world.vimrc))
    world.vim.command('call BeforeEachTest()')
    assert len(world.vim.tabpages) == 1
    assert len(world.vim.windows) == 1
    assert len(world.vim.buffers) == 1


@world.absorb
@contextmanager
def project_directory():
    """Change to the temp test project directory, and yield its path."""
    currentdir = os.getcwd()
    project = world.project_path
    try:
        os.chdir(project)
        world.vim.command('cd ' + project)
        yield world.project_path
    finally:
        os.chdir(currentdir)

# Cribbed from neovim/python-client, amended to NOT clear stuff like
# autocommands that would break our plugin. There's no way to reload remote
# plugins currently, the remote#host#LoadRemotePlugins() vimscript function
# throws an error if you re-load an already-registered plugin.
#
# I asked in Neovim Gitter, maybe this will be doable in the future.
CLEANUP_FUNC = """:silent function! BeforeEachTest()
  set all&
  tabnew
  let curbufnum = eval(bufnr('%'))
  redir => buflist
  silent ls!
  redir END
  let bufnums = []
  for buf in split(buflist, '\\n')
    let bufnum = eval(split(buf, '[ u]')[0])
    if bufnum != curbufnum
      call add(bufnums, bufnum)
    endif
  endfor
  if len(bufnums) > 0
    exe 'silent bwipeout! '.join(bufnums, ' ')
  endif
  silent tabonly
  for k in keys(g:)
    exe 'unlet g:'.k
  endfor
  filetype plugin indent off
  mapclear
  mapclear!
  abclear

  source {vimrc}
endfunction
"""
