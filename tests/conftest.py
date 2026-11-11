"""Shared pytest fixtures.

Tests must never touch the user's real home, config, keyring or session bus.
``isolated_env`` points HOME and every XDG base directory into ``tmp_path``.
"""

import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

XDG_DIRS = {
    "XDG_CONFIG_HOME": "config",
    "XDG_DATA_HOME": "data",
    "XDG_STATE_HOME": "state",
    "XDG_CACHE_HOME": "cache",
}

# Variables of the application that could leak the developer's setup into tests.
APP_VARS = ("AI_PANEL_CONFIG", "AI_PANEL_DEFAULT_AGENT", "AI_PANEL_DEBUG", "AI_PANEL_URI_LOG")


@pytest.fixture
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """Redirect HOME and XDG_* to fresh directories under ``tmp_path``.

    Returns a mapping of variable name to the created directory.
    """
    home = tmp_path / "home"
    home.mkdir()
    paths: dict[str, Path] = {"HOME": home}
    monkeypatch.setenv("HOME", str(home))
    for var, name in XDG_DIRS.items():
        path = home / name
        path.mkdir(mode=0o700)
        paths[var] = path
        monkeypatch.setenv(var, str(path))
    for var in APP_VARS:
        monkeypatch.delenv(var, raising=False)
    return paths


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT


def pytest_report_header(config: pytest.Config) -> str:
    return f"display: {os.environ.get('DISPLAY', '-')}"
