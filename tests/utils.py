import logging


class _NoLogHandler(logging.Handler):
    """Log handler that asserts if anything is logged."""

    LOGGING_FORMAT = '%(levelname)s: %(message)s'

    def __init__(self, logger):
        logging.Handler.__init__(self)
        self.setFormatter(logging.Formatter(self.LOGGING_FORMAT))
        self.logger = logger

    def __enter__(self):
        self.logger.addHandler(self)

    def __exit__(self, exc_type, exc_value, traceback):
        self.logger.removeHandler(self)

    def emit(self, record):
        message = self.format(record)
        assert False, 'Unexpected logging: %s' % message

def no_log(logger):
    """Return a context manager that asserts if anything is emitted
    on the given logger.
    """
    return _NoLogHandler(logger)
