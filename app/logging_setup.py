"""Logging to ``$XDG_STATE_HOME/gnome-ai-panel/app.log`` (rotated, 1 MB x 3) and stderr.

The level comes from ``AI_PANEL_LOG_LEVEL`` (DEBUG, INFO, WARNING, ERROR; default INFO).
"""

import logging
import logging.handlers
import os
import sys
import threading
from pathlib import Path

LOGGER_NAME = "app"
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")
MAX_BYTES = 1024 * 1024
BACKUP_COUNT = 3

REDACTED = "[redacted]"
# Shorter values are not redacted: replacing every "ab" in the log would make it unreadable
# and such values are no real protection anyway.
MIN_SECRET_LENGTH = 4


class SecretRedactor(logging.Filter):
    """Replaces known secret values in log records with ``REDACTED``.

    Attach it to handlers (handler filters see records of child loggers too). Values are
    added with ``register()`` by ``app/secrets.py`` whenever a secret is resolved.
    """

    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self._values: tuple[str, ...] = ()

    def register(self, value: str | None) -> None:
        if not value or len(value) < MIN_SECRET_LENGTH:
            return
        with self._lock:
            if value in self._values:
                return
            # Longest first, so a secret containing another one is replaced as a whole.
            self._values = tuple(sorted((*self._values, value), key=len, reverse=True))

    def clear(self) -> None:
        with self._lock:
            self._values = ()

    def redact(self, text: str) -> str:
        for value in self._values:
            if value in text:
                text = text.replace(value, REDACTED)
        return text

    def filter(self, record: logging.LogRecord) -> bool:
        if not self._values:
            return True
        try:
            message = record.getMessage()
        except Exception:  # a broken format string must not hide the record
            message = str(record.msg)
        record.msg = self.redact(message)
        record.args = None
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = self.redact(record.exc_text)
        if record.stack_info:
            record.stack_info = self.redact(record.stack_info)
        return True


REDACTOR = SecretRedactor()


def register_secret(value: str | None) -> None:
    """Never write ``value`` to the log (handlers set up by ``setup_logging``)."""
    REDACTOR.register(value)


def state_dir() -> Path:
    """Directory for the log file and other runtime state (created on demand)."""
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "gnome-ai-panel"


def log_path() -> Path:
    return state_dir() / "app.log"


def parse_level(value: str | None) -> tuple[int, bool]:
    """Return ``(level, valid)``. Unknown or empty values fall back to INFO."""
    name = (value or "").strip().upper()
    if not name:
        return logging.INFO, True
    if name in LEVELS:
        return getattr(logging, name), True
    return logging.INFO, False


def setup_logging(stderr_level: int | None = None) -> Path:
    """Configure the ``app`` logger. Safe to call more than once. Returns the log path.

    ``stderr_level`` raises the threshold of the stderr handler only (the CLI keeps its
    terminal output clean this way); the log file always uses the configured level.
    """
    raw_level = os.environ.get("AI_PANEL_LOG_LEVEL")
    level, valid = parse_level(raw_level)

    logger = logging.getLogger(LOGGER_NAME)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    logger.setLevel(level)
    logger.propagate = False

    formatter = logging.Formatter(LOG_FORMAT)

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(formatter)
    if stderr_level is not None:
        stderr_handler.setLevel(stderr_level)
    stderr_handler.addFilter(REDACTOR)
    logger.addHandler(stderr_handler)

    path = log_path()
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            path, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
        )
    except OSError as exc:
        logger.warning("cannot open log file %s: %s", path, exc)
    else:
        file_handler.setFormatter(formatter)
        file_handler.addFilter(REDACTOR)
        logger.addHandler(file_handler)

    if not valid:
        logger.warning(
            "AI_PANEL_LOG_LEVEL=%r is not one of %s, using INFO", raw_level, ", ".join(LEVELS)
        )
    return path
