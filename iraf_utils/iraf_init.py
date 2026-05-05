import sys
from utils.signal_redirect import TextRedirector


def init_iraf(log_func):
    """
    Load the standard IRAF spectroscopy package stack.

    Redirects stdout/stderr through `log_func` during the import/load phase
    so that IRAF banner text is routed to the GUI log rather than the console.

    Parameters
    ----------
    log_func : callable
        A function that accepts a single string argument (typically gui.log).
    """
    from pyraf import iraf

    old_stdout = sys.stdout
    old_stderr = sys.stderr
    sys.stdout = TextRedirector(log_func)
    sys.stderr = TextRedirector(log_func)

    try:
        log_func("\nInitializing IRAF packages...")
        iraf.imutil(_doprint=0)
        iraf.noao(_doprint=0)
        iraf.imred(_doprint=0)
        iraf.ccdred(_doprint=0)
        iraf.specred(_doprint=0)
        log_func("IRAF packages initialized.")
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr
