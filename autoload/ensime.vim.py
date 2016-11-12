# coding: utf-8

import inspect
import os
import sys

import vim


def ensime_init_path():
    path = os.path.abspath(inspect.getfile(inspect.currentframe()))
    expected_nvim_path_end = os.path.join('rplugin', 'python', 'ensime.py')
    expected_vim_path_end = os.path.join('autoload', 'ensime.vim.py')
    if path.endswith(expected_nvim_path_end):  # nvim rplugin
        sys.path.append(os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(path)))))
    elif path.endswith(expected_vim_path_end):  # vim plugin
        sys.path.append(os.path.join(
            os.path.dirname(os.path.dirname(path))))

ensime_init_path()

from ensime_shared.ensime import Ensime  # noqa: E402
ensime_plugin = Ensime(vim)
