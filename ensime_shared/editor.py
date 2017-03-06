# coding: utf-8
from os import path

from .config import feedback
from .errors import Error


class Editor(object):

    def __init__(self, driver):
        self._vim = driver
        self._isneovim = bool(int(self._vim.eval("has('nvim')")))

        # Old API
        self._errors = []   # Line error structs reported from ENSIME notes

        # Vim highlight matches for errors, for clearing
        # TODO: this seems unneeded, clearmatches()
        self._matches = []

    def append(self, text, afterline=None):
        """Append text to the current buffer.

        Args:
            text (str or Sequence[str]): One or many lines of text to append.
            afterline (Optional[int]):
                Line number to append after. If 0, text is prepended before the
                first line; if ``None``, at end of the buffer.
        """
        if afterline:
            self._vim.current.buffer.append(text, afterline)
        else:
            self._vim.current.buffer.append(text)

    @property
    def isneovim(self):
        """bool: Whether the underlying editor is Neovim. Use this sparingly."""
        return self._isneovim

    # TODO: make this read-only property-like?
    def current_word(self):
        """Get the current word under the cursor."""
        return self._vim.eval('expand("<cword>")')

    def doautocmd(self, *autocmds):
        """Invoke Vim autocommands on-demand.

        Args:
            *autocmds (str): Names of autocommands to trigger.
                See ``:h autocmd-events``.
        """
        self._vim.command('doautocmd ' + ','.join(autocmds))

    def edit(self, fpath):
        """Edit a file with path ``fpath``, in the current window."""
        self._vim.command('edit ' + fpath)

    def getline(self, lnum=None):
        """Get a line from the current buffer.

        Args:
            lnum (Optional[str]): Number of the line to get, current if ``None``.

        Todo:
            - Give this more behavior of Vim ``getline()``?
            - ``buffer[index]`` is zero-based, this is probably too confusing
        """
        return self._vim.current.buffer[lnum] if lnum else self._vim.current.line

    def getlines(self, bufnr=None):
        """Get all lines of a buffer as a list.

        Args:
            bufnr (Optional[int]): A Vim buffer number, current if ``None``.

        Returns:
            List[str]
        """
        buf = self._vim.buffers[bufnr] if bufnr else self._vim.current.buffer
        return buf[:]

    def goto(self, offset):
        """Go to a specific byte offset in the current buffer.

        Operation is added to the jump list.
        """
        self._vim.command('goto {}'.format(offset))

    def point2pos(self, point):
        """Converts a point or offset in a file to a (row, col) position."""
        row = self._vim.eval('byte2line({})'.format(point))
        col = self._vim.eval('{} - line2byte({})'.format(point, row))
        return (int(row), int(col))

    def menu(self, prompt, choices):
        """Presents a selection menu and returns the user's choice.

        Args:
            prompt (str): Text to ask the user what to select.
            choices (Sequence[str]): Values for the user to select from.

        Returns:
            The value selected by the user, or ``None``.

        Todo:
            Nice opportunity to provide a hook for Unite.vim, etc. here.
        """
        menu = [prompt] + [
            "{0}. {1}".format(*choice) for choice in enumerate(choices, start=1)
        ]
        command = 'inputlist({})'.format(repr(menu))
        choice = int(self._vim.eval(command))

        # Vim returns weird stuff if user clicks outside choices with mouse
        if not 0 < choice < len(menu):
            return

        return choices[choice - 1]

    def is_buffer_ensime_compatible(self):
        """Return True if the current buffer is supported by Ensime."""
        current_filetype = self._vim.eval('&filetype')
        return current_filetype in ['scala', 'java']

    def set_buffer_options(self, options, bufnr=None):
        """Set buffer-local options for a buffer, defaulting to current.

        Args:
            options (dict):
                Options to set, with keys being Vim option names. For Boolean
                options, use a :class:`bool` value as expected, e.g.
                ``{'buflisted': False}`` for ``setlocal nobuflisted``.
            bufnr (Optional[int]):
                A Vim buffer number, as you might get from VimL ``bufnr('%')``
                or Python ``vim.current.buffer.number``. If ``None``, options
                are set on the current buffer.
        """
        buf = self._vim.buffers[bufnr] if bufnr else self._vim.current.buffer

        # Special case handling for filetype, see doc on ``set_filetype``
        filetype = options.pop('filetype', None)
        if filetype:
            self.set_filetype(filetype)

        for opt, value in options.items():
            buf.options[opt] = value

    # TODO: make this a R/W property?
    def set_filetype(self, filetype, bufnr=None):
        """Set filetype for a buffer.

        Note: it's a quirk of Vim's Python API that using the buffer.options
        dictionary to set filetype does not trigger ``FileType`` autocommands,
        hence this implementation executes as a command instead.

        Args:
            filetype (str): The filetype to set.
            bufnr (Optional[int]): A Vim buffer number, current if ``None``.
        """
        if bufnr:
            self._vim.command(str(bufnr) + 'bufdo set filetype=' + filetype)
        else:
            self._vim.command('set filetype=' + filetype)

    def split_window(self, fpath, vertical=False, size=None, bufopts=None):
        """Open file in a new split window.

        Args:
            fpath (str): Path of the file to open. If ``None``, a new empty
                split is created.
            vertical (bool): Whether to open a vertical split.
            size (Optional[int]): The height (or width) to set for the new window.
            bufopts (Optional[dict]): Buffer-local options to set in the split window.
                See :func:`.set_buffer_options`.
        """
        command = 'split {}'.format(fpath) if fpath else 'new'
        if vertical:
            command = 'v' + command
        if size:
            command = str(size) + command

        self._vim.command(command)

        if bufopts:
            self.set_buffer_options(bufopts)

    def write(self, noautocmd=False):
        """Writes the file of the current buffer.

        Args:
            noautocmd (bool): If true, write will skip autocommands.

        Todo:
            We should consider whether ``SourceFileInfo`` can replace most
            usage of noautocmd. See #298
        """
        cmd = 'noautocmd write' if noautocmd else 'write'
        self._vim.command(cmd)

    # -----------------------------------------------------------------------
    # -                               OLD API                               -
    # -----------------------------------------------------------------------

    # TODO: honestly, just move most of this to VimL files like
    # ftplugin/scala/ensime.vim, custom/dotted filetypes & syntax
    def initialize(self):
        """Sets up initial ensime-vim editor settings."""
        # TODO: This seems wrong, the user setting value is never used anywhere.
        if 'EnErrorStyle' not in self._vim.vars:
            self._vim.vars['EnErrorStyle'] = 'EnError'
        self._vim.command('highlight EnErrorStyle ctermbg=red gui=underline')

        # TODO: this SHOULD be a buffer-local setting only, and since it should
        # apply to all Scala files, ftplugin is the ideal place to set it. I'm
        # not even sure how this is currently working when only set once.
        self._vim.command('set omnifunc=EnCompleteFunc')

        # TODO: custom filetype ftplugin
        self._vim.command(
            'autocmd FileType package_info nnoremap <buffer> <Space> :call EnPackageDecl()<CR>')
        self._vim.command('autocmd FileType package_info setlocal splitright')

    # TODO: make this a R/W property?
    def cursor(self):
        """Get the cursor position in the current window as a ``(row, column)``
        tuple.
        """
        return self._vim.current.window.cursor

    def set_cursor(self, row, col):
        """Set cursor position to given row and column in the current window.

        Operation is not added to the jump list.
        """
        self._vim.current.window.cursor = (row, col)

    # TODO: don't displace user's cursor; can something like ``getpos()`` do this?
    def word_under_cursor_pos(self):
        """Return start and end positions of the cursor respectively."""
        self._vim.command('normal e')
        end = self.cursor()
        self._vim.command('normal b')
        beg = self.cursor()
        return beg, end

    def selection_pos(self):
        """Return start and end positions of the visual selection respectively."""
        buff = self._vim.current.buffer
        beg = buff.mark('<')
        end = buff.mark('>')
        return beg, end

    def path(self):
        """Return the current path."""
        return self._vim.current.buffer.name

    def get_file_content(self):
        """Get content of file."""
        return "\n".join(self._vim.current.buffer)

    # This is used only once, maybe just make a higher-level API or inline it
    def width(self):
        """Return the width of the window."""
        return self._vim.current.window.width

    def ask_input(self, prompt):
        """Prompt user for input and return the entered value."""
        self._vim.command('call inputsave()')
        self._vim.command('let user_input = input("{} ")'.format(prompt))
        self._vim.command('call inputrestore()')
        response = self._vim.eval('user_input')
        self._vim.command('unlet user_input')
        return response

    def to_quickfix_item(self, file_name, line_number, message, tpe):
        return {"filename": file_name,
                "lnum": line_number,
                "text": message,
                "type": tpe}

    def write_quickfix_list(self, qflist):
        self._vim.command('call setqflist({!s})'.format(qflist))
        self._vim.command('copen')

    def lazy_display_error(self, filename):
        """Display error when user is over it."""
        position = self.cursor()
        error = self.get_error_at(position)
        if error:
            report = error.get_truncated_message(position, self.width() - 1)
            self.raw_message(report)

    def get_error_at(self, cursor):
        """Return error at position `cursor`."""
        for error in self._errors:
            if error.includes(self._vim.eval("expand('%:p')"), cursor):
                return error
        return None

    def clean_errors(self):
        """Clean errors and unhighlight them in vim."""
        self._vim.eval('clearmatches()')
        self._errors = []
        self._matches = []
        # Reset Syntastic notes - TODO: bufdo?
        self._vim.current.buffer.vars['ensime_notes'] = []

    def message(self, key):
        """Display a message already defined in `feedback`."""
        msg = '[ensime] ' + feedback[key]
        self.raw_message(msg)

    def raw_message(self, message, silent=False):
        """Display a message in the Vim status line."""
        vim = self._vim
        cmd = 'echo "{}"'.format(message.replace('"', '\\"'))
        if silent:
            cmd = 'silent ' + cmd

        if self.isneovim:
            vim.async_call(vim.command, cmd)
        else:
            vim.command(cmd)

    def symbol_for_inspector_line(self, lineno):
        """Given a line number for the Package Inspector window, returns the
        fully-qualified name for the symbol on that line.
        """
        def indent(line):
            n = 0
            for char in line:
                if char == ' ':
                    n += 1
                else:
                    break
            return n / 2

        lines = self._vim.current.buffer[:lineno]
        i = indent(lines[-1])
        fqn = [lines[-1].split()[-1]]

        for line in reversed(lines):
            if indent(line) == i - 1:
                i -= 1
                fqn.insert(0, line.split()[-1])

        return ".".join(fqn)

    def display_notes(self, notes):
        """Renders "notes" reported by ENSIME, such as typecheck errors."""

        # TODO: this can probably be a cached property like isneovim
        hassyntastic = bool(int(self._vim.eval('exists(":SyntasticCheck")')))

        if hassyntastic:
            self.__display_notes_with_syntastic(notes)
        else:
            self.__display_notes(notes)

        self._vim.command('redraw!')

    def __display_notes_with_syntastic(self, notes):

        def is_note_correct(note):  # Server bug? See #200
            return note['beg'] != -1 and note['end'] != -1

        current_file = self.path()
        loclist = list({
            'bufnr': self._vim.current.buffer.number,
            'lnum': note['line'],
            'col': note['col'],
            'text': note['msg'],
            'len': note['end'] - note['beg'] + 1,
            'type': note['severity']['typehint'][4:5],
            'valid': 1
        } for note in notes
            if current_file == path.abspath(note['file'])
            and is_note_correct(note)
        )

        if loclist:
            bufvars = self._vim.current.buffer.vars
            if not bufvars.get('ensime_notes'):
                bufvars['ensime_notes'] = []

            bufvars['ensime_notes'] += loclist
            self._vim.command('silent! SyntasticCheck ensime')

    def __display_notes(self, notes):
        current_file = self.path()
        highlight_cmd = r"matchadd('EnErrorStyle', '\%{}l\%>{}c\%<{}c')"

        for note in notes:
            l = note['line']
            c = note['col'] - 1
            e = note['col'] + (note['end'] - note['beg'] + 1)

            if current_file == path.abspath(note['file']):
                error = Error(note['file'], note['msg'], l, c, e)
                match = self._vim.eval(highlight_cmd.format(l, c, e))
                self._errors.append(error)
                self._matches.append(match)
                # add_match_msg = "added match {} at line {} column {} error {}"
                # self.log.debug(add_match_msg.format(match, l, c, e))
