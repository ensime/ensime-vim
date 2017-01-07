import os
import sys

import mock
import pytest

# pytest expects the project modules to be importable from whereever you run
# it, preferring that you do `pip install --editable .` -- we don't want to be
# a distributable Python package so this is easier than maintaining a useless
# setup.py.
parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, parent)


@pytest.fixture
def vim():
    """A wide-open mock vim object.

    We'll just have to be careful since we can't import a real vim object to
    use autospec and guarantee that we're calling real APIs.
    """
    def vimeval(expr):
        # Default Editor.isneovim to False.
        if expr == "has('nvim')":
            return False
        else:
            return mock.DEFAULT

    attrs = {'eval.side_effect': vimeval}
    return mock.NonCallableMock(name='mockvim', **attrs)


@pytest.fixture
def neovim():
    """Hopefully this doesn't need to diverge much from the above..."""
    def vimeval(expr):
        if expr == "has('nvim')":
            return True
        else:
            return mock.DEFAULT

    attrs = {'eval.side_effect': vimeval}
    return mock.NonCallableMock(name='mockneovim', **attrs)
