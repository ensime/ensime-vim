# coding: utf-8
"""
The ``debugger`` module presents debugger functionality by handling the ENSIME
debugging protocol.
"""

import json
import os
import tempfile

from ensime_shared.config import feedback


class DebuggerClient(object):
    """Client handlers for ENSIME debugging protocol.

    Must be mixed into an ``EnsimeClient``.
    """

    # -------------------------------------------------------------------------
    # Response Handlers
    # -------------------------------------------------------------------------

    def handle_debug_output(self, call_id, payload):
        """Handle responses `DebugOutputEvent`."""
        self.editor.raw_message(payload["body"].encode("ascii", "ignore"))

    def handle_debug_break(self, call_id, payload):
        """Handle responses `DebugBreakEvent`."""
        line = payload['line']
        config = self.launcher.config  # TODO: make an attribute of client
        path = os.path.relpath(payload['file'], config['root-dir'])

        self.editor.raw_message(feedback['notify_break'].format(line, path))
        self.debug_thread_id = payload["threadId"]

    # TODO: This leaves a lot to be desired...
    def handle_debug_backtrace(self, call_id, payload):
        """Handle responses `DebugBacktrace`."""
        frames = payload["frames"]
        fd, path = tempfile.mkstemp('.json', text=True, dir=self.tmp_diff_folder)
        tmpfile = os.fdopen(fd, 'w')

        tmpfile.write(json.dumps(frames, indent=2))
        opts = {'readonly': True, 'bufhidden': 'wipe',
                'buflisted': False, 'swapfile': False}
        self.editor.split_window(path, size=20, bufopts=opts)
        tmpfile.close()

    # -------------------------------------------------------------------------
    # API Call Build/Send
    # -------------------------------------------------------------------------

    def debug_set_break(self, args, range=None):
        self.log.debug('debug_set_break: in')
        req = {"line": self.editor.cursor()[0],
               "maxResults": 10,
               "typehint": "DebugSetBreakReq",
               "file": self.editor.path()}
        self.send_request(req)

    def debug_clear_breaks(self, args, range=None):
        self.log.debug('debug_clear_breaks: in')
        self.send_request({"typehint": "DebugClearAllBreaksReq"})

    def debug_start(self, args, range=None):
        self.log.debug('debug_start: in')
        if len(args) > 1:
            self.send_request({
                "typehint": "DebugAttachReq",
                "hostname": args[0],
                "port": args[1]})
        else:
            self.send_request({
                "typehint": "DebugAttachReq",
                "hostname": "localhost",
                "port": "5005"})

    def debug_continue(self, args, range=None):
        self.log.debug('debug_continue: in')
        self.send_request({
            "typehint": "DebugContinueReq",
            "threadId": self.debug_thread_id})

    def debug_backtrace(self, args, range=None):
        self.log.debug('debug_backtrace: in')
        self.send_request({
            "typehint": "DebugBacktraceReq",
            "threadId": self.debug_thread_id,
            "index": 0, "count": 100})

    def debug_step(self, args, range=None):
        self.log.debug('debug_step: in')
        self.send_request({
            "typehint": "DebugStepReq",
            "threadId": self.debug_thread_id})

    def debug_step_out(self, args, range=None):
        self.log.debug('debug_step_out: in')
        self.send_request({
            "typehint": "DebugStepOutReq",
            "threadId": self.debug_thread_id})

    def debug_next(self, args, range=None):
        self.log.debug('debug_next: in')
        self.send_request({
            "typehint": "DebugNextReq",
            "threadId": self.debug_thread_id})
