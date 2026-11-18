"""Application logging for the DynaLoop namespace."""

import logging
import sys
from pathlib import Path

from dynaloop.infrastructure.config import Settings

DEFAULT_LOG_PATH = Path.home() / ".dynaloop" / "logs" / "dynaloop.log"
_MANAGED_HANDLER_ATTRIBUTE = "_dynaloop_managed_handler"
_CONFIGURATION_ATTRIBUTE = "_dynaloop_logging_configuration"
_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


class LoggingError(RuntimeError):
    """Raised when DynaLoop logging handlers cannot be initialized."""


def configure_logging(
    settings: Settings | None = None,
    *,
    console: bool = True,
    log_file: str | Path | None = DEFAULT_LOG_PATH,
) -> logging.Logger:
    """Configure DynaLoop console and optional file logging without touching root."""
    settings = settings or Settings()
    level = settings.log_level.upper()
    try:
        file_path = Path(log_file).expanduser().resolve() if log_file is not None else None
    except (OSError, RuntimeError) as exc:
        raise LoggingError(f"Unable to resolve log file path '{log_file}': {exc}") from exc
    configuration = (
        level,
        console,
        str(file_path) if file_path is not None else None,
        id(sys.stderr) if console else None,
    )

    logger = logging.getLogger("dynaloop")

    expected_handler_count = int(console) + int(file_path is not None)
    managed_handlers = [
        handler
        for handler in logger.handlers
        if getattr(handler, _MANAGED_HANDLER_ATTRIBUTE, False)
    ]
    if (
        getattr(logger, _CONFIGURATION_ATTRIBUTE, None) == configuration
        and len(managed_handlers) == expected_handler_count
    ):
        logger.setLevel(level)
        logger.propagate = False
        return logger

    formatter = logging.Formatter(_FORMAT, datefmt=_DATE_FORMAT)
    new_handlers: list[logging.Handler] = []
    try:
        if console:
            console_handler = logging.StreamHandler(sys.stderr)
            console_handler.setFormatter(formatter)
            setattr(console_handler, _MANAGED_HANDLER_ATTRIBUTE, True)
            new_handlers.append(console_handler)

        if file_path is not None:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(file_path, encoding="utf-8")
            file_handler.setFormatter(formatter)
            setattr(file_handler, _MANAGED_HANDLER_ATTRIBUTE, True)
            new_handlers.append(file_handler)
    except OSError as exc:
        for handler in new_handlers:
            handler.close()
        raise LoggingError(f"Unable to initialize log file '{file_path}': {exc}") from exc

    logger.setLevel(level)
    logger.propagate = False
    for handler in managed_handlers:
        logger.removeHandler(handler)
        handler.close()
    for handler in new_handlers:
        logger.addHandler(handler)

    setattr(logger, _CONFIGURATION_ATTRIBUTE, configuration)
    return logger


def get_logger(name: str) -> logging.Logger:
    """Return a logger under the DynaLoop namespace for the named module."""
    if not name or not name.strip():
        raise ValueError("Logger name must not be empty.")
    return logging.getLogger(f"dynaloop.{name}")
