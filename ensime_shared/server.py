# coding: utf-8

from .launcher import EnsimeLauncher

URI_TEMPLATE = 'ws://127.0.0.1:{port}/{path}'


class Server(object):
    """Facade representing an ENSIME server process."""

    def __init__(self, config, server_v2=False):
        self._config = config
        self._server_v2 = server_v2  # TODO: drop this attribute after #355
        self._launcher = EnsimeLauncher(None, config)
        self._process = None

    @property
    def config(self):
        """ProjectConfig: Project configuration for the server instance."""
        return self._config

    @property
    def address(self):
        """Optional[str]: Address where server is listening for WebSocket connections."""
        if not self.isrunning():
            return
        path = 'websocket' if self._server_v2 else 'jerky'
        return URI_TEMPLATE.format(port=self.port, path=path)

    @property
    def port(self):  # TODO: memoize
        """HTTP port where server is listening for WebSocket connections."""
        return self._process.http_port()

    def install(self):
        """Install server based on project configuration, if necessary.

        Returns:
            TODO
        """
        if not self.isinstalled():
            return self._launcher.strategy.install()

    def isinstalled(self):
        """Whether the server is currently installed.

        Returns:
            bool
        """
        return self._launcher.strategy.isinstalled()

    def isrunning(self):
        """Whether the server is running and accepting connections.

        Returns:
            bool
        """
        return self._process and self._process.is_ready()

    def start(self):
        """Start the server process.

        Returns:
            bool: TODO whether process successfully started
        """
        if not self._process:
            self._process = self._launcher.launch()
        return bool(self._process)

    def stop(self):
        """Stop server process.

        Returns:
            Optional[bool]: TODO whether server was stopped, or None if it was
                not running.
        """
        if self._process:
            self._process.stop()  # TODO: make this return bool
            self._process = None
            return True
