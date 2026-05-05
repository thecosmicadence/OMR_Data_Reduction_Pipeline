class TextRedirector:
    """
    Redirects writes to ``sys.stdout`` / ``sys.stderr`` through a GUI log function.

    Buffers incomplete lines and flushes them when a newline is received.

    Parameters
    ----------
    log_func : callable
        A function that accepts a single string argument (e.g. ``gui.log``).
    """

    def __init__(self, log_func):
        self.log_func = log_func
        self._buffer = ""

    def write(self, text):
        self._buffer += text
        if "\n" in self._buffer:
            lines = self._buffer.split("\n")
            for line in lines[:-1]:
                self.log_func(line)
            self._buffer = lines[-1]

    def flush(self):
        if self._buffer:
            self.log_func(self._buffer)
            self._buffer = ""
