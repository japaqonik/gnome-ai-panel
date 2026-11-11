"""Edge cases of logging setup (added by the tester for S1-T2)."""

import logging

import pytest

from app import logging_setup


@pytest.fixture
def app_logger():
    logger = logging.getLogger(logging_setup.LOGGER_NAME)
    yield logger
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()


def test_unwritable_state_dir_falls_back_to_stderr(isolated_env, app_logger, monkeypatch, capsys):
    blocker = isolated_env["XDG_STATE_HOME"] / "gnome-ai-panel"
    blocker.write_text("not a directory")  # mkdir/open will fail with an OSError
    logging_setup.setup_logging()
    assert len(app_logger.handlers) == 1
    assert isinstance(app_logger.handlers[0], logging.StreamHandler)
    app_logger.info("still logging")
    err = capsys.readouterr().err
    assert "cannot open log file" in err
    assert "still logging" in err


@pytest.mark.parametrize("value", ["debug", " Warning ", "ERROR"])
def test_level_is_case_and_space_insensitive(isolated_env, app_logger, monkeypatch, value):
    monkeypatch.setenv("AI_PANEL_LOG_LEVEL", value)
    logging_setup.setup_logging()
    assert app_logger.level == getattr(logging, value.strip().upper())


def test_rotation_parameters(isolated_env, app_logger):
    logging_setup.setup_logging()
    (file_handler,) = [
        h for h in app_logger.handlers if isinstance(h, logging.handlers.RotatingFileHandler)
    ]
    assert file_handler.maxBytes == 1024 * 1024
    assert file_handler.backupCount == 3


def test_messages_do_not_propagate_to_root(isolated_env, app_logger):
    logging_setup.setup_logging()
    assert app_logger.propagate is False
