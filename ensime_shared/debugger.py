from ensime_shared.config import feedback

class DebuggerClient(object):
    """This is the implementation of the Ensime debugger client, it must be mixed in
       with the EnsimeClient to be useful."""


# Response Handlers
    def handle_debug_output(self, call_id, payload):
        """Handle responses `DebugOutputEvent`."""
        self.raw_message(payload["body"].encode("ascii", "ignore"))

    def handle_debug_break(self, call_id, payload):
        """Handle responses `DebugBreakEvent`."""
        self.raw_message(feedback["notify_break"])
        self.debug_thread_id = payload["threadId"]

    def handle_debug_backtrace(self, call_id, payload):
        """Handle responses `DebugBacktrace`."""
        frames = payload["frames"]
        self.vim.command(":split backtrace.json")
        to_json = json.dumps(frames, indent=2).split("\n")
        self.vim.current.buffer[:] = to_json

# API Call Build/Send
    def set_break(self, args, range=None):
        self.log("set_break: in")
        req = {"line": self.cursor()[0],
               "maxResults": 10,
               "typehint": "DebugSetBreakReq",
               "file": self.path()}
        self.send_request(req)

    def clear_breaks(self, args, range=None):
        self.log("clear_breaks: in")
        self.send_request({"typehint": "DebugClearAllBreakReq"})

    def debug_start(self, args, range=None):
        self.log("debug_start: in")
        if len(args) > 1:
            self.send_request({
                "typehint": "DebugAttachReq",
                "hostname": args[0],
                "port" :    args[1]})
        else:
            self.send_request({
                "typehint": "DebugAttachReq",
                "hostname": "localhost",
                "port" :    "5005"})

    def debug_continue(self, args, range=None):
        self.log("debug_continue: in")
        self.send_request({
            "typehint": "DebugContinueReq",
            "threadId": self.debug_thread_id})

    def debug_step(self, args, range=None):
        self.log("debug_step: in") 
        self.send_request({
            "typehint":"DebugStepReq",
            "threadId":self.debug_thread_id})
 
    def debug_step_out(self, args, range=None):
        self.log("debug_step_out: in") 
        self.send_request({
            "typehint":"DebugStepOutReq",
            "threadId":self.debug_thread_id})
 
    def debug_next(self, args, range=None):
        self.log("debug_next: in") 
        self.send_request({
            "typehint":"DebugNextReq",
            "threadId":self.debug_thread_id})

    def debug_locate_name(self, args, range=None):
        self.log("debug_locate_name: in")
        self.send_request({
            "typehint":"DebugLocateNameReq",
            "threadId":self.debug_thread_id,
            "name":args[0]})
       
    def backtrace(self, args, range=None):
        self.log("backtrace: in")
        self.send_request({
            "typehint": "DebugBacktraceReq",
            "threadId": self.debug_thread_id,
            "index": 0, "count": 100})

    def backtrace(self, args, range=None):
        self.log("backtrace: in")
        self.send_request({
            "typehint": "DebugBacktraceReq",
            "threadId": self.debug_thread_id,
            "index": 0, "count": 100})

