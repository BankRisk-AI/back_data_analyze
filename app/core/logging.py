"""Application-wide console logging configuration and logger facade."""
from __future__ import annotations

import logging
import sys


LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
_HANDLER_MARKER = "_eba_console_handler"


def configure_logging(level: int = logging.INFO) -> None:
    """Configure one console handler for application and third-party loggers."""
    root = logging.getLogger()
    root.setLevel(level)
    if not any(getattr(handler, _HANDLER_MARKER, False) for handler in root.handlers):
        handler = logging.StreamHandler(sys.stderr)
        setattr(handler, _HANDLER_MARKER, True)
        handler.setFormatter(logging.Formatter(LOG_FORMAT))
        root.addHandler(handler)


class LoggerService:
    """Small reusable facade over Python's standard logger."""

    def __init__(self, module: str) -> None:
        self._logger = logging.getLogger(module)

    def debug(self, message: str, *args: object, **kwargs: object) -> None:
        self._logger.debug(message, *args, **kwargs)

    def info(self, message: str, *args: object, **kwargs: object) -> None:
        self._logger.info(message, *args, **kwargs)

    def warning(self, message: str, *args: object, **kwargs: object) -> None:
        self._logger.warning(message, *args, **kwargs)

    def error(self, message: str, *args: object, **kwargs: object) -> None:
        self._logger.error(message, *args, **kwargs)

    def critical(self, message: str, *args: object, **kwargs: object) -> None:
        self._logger.critical(message, *args, **kwargs)

    def exception(self, message: str, *args: object, **kwargs: object) -> None:
        self._logger.exception(message, *args, **kwargs)


def get_logger(module: str) -> LoggerService:
    return LoggerService(module)
