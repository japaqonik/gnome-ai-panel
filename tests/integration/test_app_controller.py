"""The application process with a configuration: agent choice, ``new-chat`` and ``quit`` (S3-T3)."""

import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.gui

FAKE_CONFIG = Path(__file__).resolve().parents[1] / "data" / "config_fake.toml"


def _wait_log(app, text: str, timeout: float = 10.0) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        log = app.log.read_text(errors="replace") if app.log.exists() else ""
        if text in log:
            return log
        time.sleep(0.05)
    pytest.fail(f"{text!r} not in the log:\n{log}")


def test_config_and_default_agent_override(app_process, private_bus) -> None:
    private_bus.env["AI_PANEL_CONFIG"] = str(FAKE_CONFIG)
    private_bus.env["AI_PANEL_DEFAULT_AGENT"] = "fake-slow"
    app = app_process("--background")
    log = _wait_log(app, "agent: fake-slow")
    assert f"configuration {FAKE_CONFIG}" in log

    app.action("new-chat")
    _wait_log(app, "new chat")

    app.action("quit")
    assert app.proc.wait(timeout=10) == 0


def test_unknown_override_falls_back_to_default_agent(app_process, private_bus) -> None:
    private_bus.env["AI_PANEL_CONFIG"] = str(FAKE_CONFIG)
    private_bus.env["AI_PANEL_DEFAULT_AGENT"] = "nope"
    app = app_process("--background")
    log = _wait_log(app, "agent: fake-echo")
    assert "AI_PANEL_DEFAULT_AGENT='nope' is not a valid agent" in log


def test_without_config_no_agent(app_process, private_bus, tmp_path) -> None:
    private_bus.env["AI_PANEL_CONFIG"] = str(tmp_path / "missing.toml")
    app = app_process("--background")
    _wait_log(app, "no valid agent configured")
