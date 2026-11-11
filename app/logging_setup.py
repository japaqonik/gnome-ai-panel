"""Logging to ``$XDG_STATE_HOME/gnome-ai-panel/app.log`` (rotated, 1 MB x 3) and stderr.

The level comes from ``AI_PANEL_LOG_LEVEL`` (DEBUG, INFO, WARNING, ERROR; default INFO).
"""

import logging
import logging.handlers
import os
import sys
from pathlib import Path

LOGGER_NAME = "app"
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")
MAX_BYTES = 1024 * 1024
BACKUP_COUNT = 3


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


def setup_logging() -> Path:
    """Configure the ``app`` logger. Safe to call more than once. Returns the log path."""
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
        logger.addHandler(file_handler)

    if not valid:
        logger.warning(
            "AI_PANEL_LOG_LEVEL=%r is not one of %s, using INFO", raw_level, ", ".join(LEVELS)
        )
    return path
