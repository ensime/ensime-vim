# coding: utf-8

import pytest
from mock import call, sentinel

from ensime_shared.editor import Editor


@pytest.fixture
def editor(vim):
    return Editor(vim)


def test_append(editor, vim):
    editor.append('new')
    editor.append('new', sentinel.lineno)

    buffer = vim.current.buffer
    assert buffer.mock_calls == [
        call.append('new'),
        call.append('new', sentinel.lineno),
    ]


def test_isneovim(editor, neovim):
    assert not editor.isneovim
    assert Editor(neovim).isneovim


def test_current_word(editor, vim):
    editor.current_word()
    vim.eval.assert_called_with('expand("<cword>")')


def test_doautocmd(editor, vim):
    editor.doautocmd('BufLeave')
    editor.doautocmd('BufReadPre', 'BufRead', 'BufEnter')

    assert vim.mock_calls == [
        call.command('doautocmd BufLeave'),
        call.command('doautocmd BufReadPre,BufRead,BufEnter'),
    ]


def test_edit(editor, vim):
    editor.edit('foo.scala')
    vim.command.assert_called_with('edit foo.scala')


def test_getlines(editor, vim):
    # The buffer objects behave like sequences
    lines = ['line 1', 'line2', 'line3']
    vim.current.buffer = lines[:]

    assert editor.getlines() == lines


class TestMenu:
    prompt = 'Choose one:'
    choices = ['one', 'two', 'three']

    def test_choice(self, editor, vim):
        # Stub the user's inputlist choice
        vim.eval.return_value = 2

        choice = editor.menu(self.prompt, self.choices)
        assert choice == 'two'
        positional = vim.eval.call_args[0]
        assert 'inputlist' in positional[0]

    def test_none(self, editor, vim):
        vim.eval.return_value = 0
        choice = editor.menu(self.prompt, self.choices)
        assert choice is None


def test_set_filetype(editor, vim):
    editor.set_filetype('package_info')
    editor.set_filetype('package_info', 3)

    assert vim.mock_calls == [
        call.command('set filetype=package_info'),
        call.command('3bufdo set filetype=package_info'),
    ]


def test_set_buffer_options(editor, vim):
    # Stub Buffer object's mapping API for options, see `:h python-buffer`
    setlocal = {}
    vim.current.buffer.options = setlocal

    opts = {'buftype': 'nofile', 'buflisted': False}
    editor.set_buffer_options(opts)
    assert setlocal == opts


class TestSplitWindow:
    def test_creates_empty_splits(self, editor, vim):
        editor.split_window(None)
        editor.split_window(None, vertical=True)

        assert vim.mock_calls == [call.command('new'), call.command('vnew')]

    def test_creates_file_splits(self, editor, vim):
        editor.split_window('foo.scala')
        editor.split_window('foo.scala', vertical=True)

        assert vim.mock_calls == [
            call.command('split foo.scala'),
            call.command('vsplit foo.scala'),
        ]

    def test_can_size_splits(self, editor, vim):
        editor.split_window('foo.scala', size=50)
        vim.command.assert_called_once_with('50split foo.scala')

    def test_sets_buffer_options(self, editor, mocker):
        # Stub actual implementation, it's already tested
        editor.set_buffer_options = mocker.stub()

        editor.split_window('foo.scala', bufopts=sentinel.bufopts)
        editor.set_buffer_options.assert_called_once_with(sentinel.bufopts)


def test_write(editor, vim):
    editor.write()
    editor.write(noautocmd=True)

    assert vim.mock_calls == [
        call.command('write'),
        call.command('noautocmd write'),
    ]
