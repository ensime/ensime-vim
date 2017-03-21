REFRESH_TIMER = 1000


class Ticker(object):

    def __init__(self, _vim):
        self._vim = _vim
        self.has_timers = bool(int(self._vim.eval("has('timers')")))

        if self.has_timers:
            self._timer = None
            self._start_refresh_timer()

    def tick(self, client):
        filename = client.editor.path()

        # XXX is this necessary ?
        if not client.editor.is_buffer_ensime_compatible():
            return

        client.tick(filename)

        if not self.has_timers:
            self._repeat_cursor_hold()

    def _repeat_cursor_hold(self):
        self._vim.options['updatetime'] = REFRESH_TIMER
        self._vim.command('call feedkeys("f\e")')

    def _start_refresh_timer(self):
        """Start the Vim timer. """
        if not self._timer:
            self._timer = self._vim.eval(
                "timer_start({}, 'EnTick', {{'repeat': -1}})"
                .format(REFRESH_TIMER)
            )
