# coding: utf-8


class TypecheckHandler(object):

    def __init__(self):
        self.currently_buffering_typechecks = False
        self.buffered_notes = []
        super(TypecheckHandler, self).__init__()

    def buffer_typechecks(self, call_id, payload):
        """Adds typecheck events to the buffer"""
        if self.currently_buffering_typechecks:
            for note in payload['notes']:
                self.buffered_notes.append(note)

    def start_typechecking(self):
        self.log.info('Readying typecheck...')
        self.currently_buffering_typechecks = True
        if self.currently_buffering_typechecks:
            self.buffered_notes = []

    def handle_typecheck_complete(self, call_id, payload):
        """Handles ``NewScalaNotesEvent```.

        Calls editor to display/highlight line notes and clears notes buffer.
        """
        self.log.debug('handle_typecheck_complete: in')
        if not self.currently_buffering_typechecks:
            self.log.debug('Completed typecheck was not requested by user, not displaying notes')
            return

        self.editor.display_notes(self.buffered_notes)
        self.currently_buffering_typechecks = False
        self.buffered_notes = []
