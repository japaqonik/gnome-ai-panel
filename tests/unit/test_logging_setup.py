import logging
import os
import stat
from pathlib import Path

import pytest

from app import logging_setup


@pytest.fixture
def app_logger():
    logger = logging.getLogger(logging_setup.LOGGER_NAME)
    yield logger
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()


@pytest.mark.parametrize(
    ("value", "level", "valid"),
    [
        (None, logging.INFO, True),
        ("", logging.INFO, True),
        ("debug", logging.DEBUG, True),
        (" WARNING ", logging.WARNING, True),
        ("ERROR", logging.ERROR, True),
        ("verbose", logging.INFO, False),
    ],
)
def test_parse_level(value, level, valid) -> None:
    assert logging_setup.parse_level(value) == (level, valid)


def test_log_file_under_xdg_state_home(isolated_env, app_logger, monkeypatch) -> None:
    monkeypatch.setenv("AI_PANEL_LOG_LEVEL", "DEBUG")
    path = logging_setup.setup_logging()
    assert path == isolated_env["XDG_STATE_HOME"] / "gnome-ai-panel" / "app.log"
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700

    logging.getLogger("app.test").debug("hello from test")
    for handler in app_logger.handlers:
        handler.flush()
    assert "DEBUG app.test: hello from test" in path.read_text(encoding="utf-8")
    assert app_logger.level == logging.DEBUG


def test_default_state_dir_without_xdg(isolated_env, monkeypatch) -> None:
    monkeypatch.delenv("XDG_STATE_HOME")
    assert (
        logging_setup.log_path() == Path(os.environ["HOME"]) / ".local/state/gnome-ai-panel/app.log"
    )


def test_invalid_level_warns_and_uses_info(isolated_env, app_logger, monkeypatch, capsys) -> None:
    monkeypatch.setenv("AI_PANEL_LOG_LEVEL", "loud")
    logging_setup.setup_logging()
    assert app_logger.level == logging.INFO
    assert "AI_PANEL_LOG_LEVEL='loud'" in capsys.readouterr().err


def test_setup_twice_does_not_duplicate_handlers(isolated_env, app_logger) -> None:
    logging_setup.setup_logging()
    logging_setup.setup_logging()
    assert len(app_logger.handlers) == 2


def test_info_not_written_below_warning(isolated_env, app_logger, monkeypatch) -> None:
    monkeypatch.setenv("AI_PANEL_LOG_LEVEL", "WARNING")
    path = logging_setup.setup_logging()
    logging.getLogger("app.test").info("quiet")
    for handler in app_logger.handlers:
        handler.flush()
    assert "quiet" not in path.read_text(encoding="utf-8")
