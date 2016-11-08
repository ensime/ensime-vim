# coding: utf-8

import inspect
import os
import sys

import vim


def ensime_init_path():
    path = os.path.abspath(inspect.getfile(inspect.currentframe()))
    dir_file1 = os.path.split(path)
    path_fn = dir_file1[1]
    dir_file2 = os.path.split(dir_file1[0])
    path_dir1 = dir_file2[1]
    dir_file3 = os.path.split(dir_file2[0])
    path_dir2 = dir_file3[1]
    expected_nvim_path_end = ['rplugin', 'python', 'ensime.py']
    expected_vim_path_end = ['autoload','ensime.vim.py']
    if expected_nvim_path_end == [path_dir2, path_dir1, path_fn]: # nvim rplugin
        sys.path.append(os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(path)))))
    elif expected_vim_path_end == [path_dir1, path_fn]: # vim plugin
        sys.path.append(os.path.join(
            os.path.dirname(os.path.dirname(path))))

ensime_init_path()

from ensime_shared.ensime import Ensime  # noqa: E402
ensime_plugin = Ensime(vim)
