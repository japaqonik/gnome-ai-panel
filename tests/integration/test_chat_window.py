"""The chat window end to end in one process: page → bridge → controller → fake ACP agent.

The prompt is typed into the real page (WebKitGTK under Xvfb) and the reply is read back
from its DOM. The asyncio loop is the GLib loop (``GLibEventLoopPolicy``), so GTK, WebKit and
the agent subprocess all run while the test awaits.
"""

import asyncio
import json
import os
from pathlib import Path

import pytest

if not os.environ.get("DISPLAY"):
    pytest.skip("needs a display (run through make test-py)", allow_module_level=True)

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("WebKit", "6.0")
from gi.events import GLibEventLoopPolicy  # noqa: E402
from gi.repository import Adw, GLib  # noqa: E402

from app import backends  # noqa: E402
from app.bridge import Bridge  # noqa: E402
from app.config import load_config  # noqa: E402
from app.controller import ChatController  # noqa: E402

pytestmark = [pytest.mark.gui, pytest.mark.filterwarnings("ignore::DeprecationWarning")]

FAKE_CONFIG = Path(__file__).resolve().parents[1] / "data" / "config_fake.toml"


async def _js(webview, script: str):
    loop = asyncio.get_running_loop()
    future = loop.create_future()

    def done(view, result, _data=None):
        try:
            value = view.evaluate_javascript_finish(result)
            future.set_result(json.loads(value.to_json(0)) if value is not None else None)
        except Exception as exc:
            future.set_exception(exc)

    webview.evaluate_javascript(f"JSON.parse(JSON.stringify({script}))", -1, None, None, None, done)
    return await future


async def _until(webview, script: str, timeout: float = 15.0):
    async with asyncio.timeout(timeout):
        while True:
            try:
                value = await _js(webview, script)
            except GLib.Error:  # the page is still loading
                value = None
            if value:
                return value
            await asyncio.sleep(0.05)


STATE = """(() => ({
    screen: document.getElementById('chat').hidden ? 'empty' : 'chat',
    agent: document.getElementById('agent-name').textContent,
    busy: !document.getElementById('stop').hidden,
    messages: [...document.querySelectorAll('.message')].map(n => ({
        role: n.dataset.role, text: n.textContent, kind: n.dataset.kind ?? null})),
}))()"""

SEND = """(() => {
    const prompt = document.getElementById('prompt');
    prompt.value = %s;
    prompt.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true}));
    return true;
})()"""


class RecordingBridge(Bridge):
    def __init__(self) -> None:
        super().__init__()
        self.dispatched: list[dict] = []

    def dispatch(self, event: dict) -> None:
        self.dispatched.append(event)
        super().dispatch(event)


def _run(scenario, monkeypatch, *, agent: str | None = None, config_path=FAKE_CONFIG):
    monkeypatch.setenv("AI_PANEL_CONFIG", str(config_path))
    Adw.init()
    from app.window import PanelWindow

    config = load_config()
    app = Adw.Application(application_id=None)
    bridge = RecordingBridge()
    controller = ChatController(
        config, bridge, lambda a: backends.get_backend(a, mcp=config.mcp), default_agent=agent
    )
    bridge.handler = controller
    window = PanelWindow(app, bridge)
    # Rendering of streamed text runs in requestAnimationFrame, which needs a mapped window.
    window.present()

    async def main():
        try:
            async with asyncio.timeout(60):
                return await scenario(window.webview, bridge)
        finally:
            await controller.close()
            await backends.close_all()

    with GLibEventLoopPolicy() as policy:
        loop = policy.get_event_loop()
        try:
            return loop.run_until_complete(main())
        finally:
            window.destroy()


def test_turn_through_the_real_page(isolated_env, monkeypatch) -> None:
    async def scenario(webview, bridge):
        await _until(webview, "!document.getElementById('chat').hidden")
        await _js(webview, SEND % json.dumps("Cześć </script> \u2028"))
        await _until(
            webview,
            "document.querySelector('.message--assistant')?.textContent.includes('Echo:')"
            " && document.getElementById('stop').hidden",
        )
        return await _js(webview, STATE)

    state = _run(scenario, monkeypatch)
    assert state["screen"] == "chat"
    assert state["agent"] == "fake-echo"
    assert state["busy"] is False
    roles = [m["role"] for m in state["messages"]]
    assert roles == ["user", "assistant"]
    assert state["messages"][0]["text"] == "Cześć </script> \u2028"
    assert "Echo: Cześć" in state["messages"][1]["text"]


def test_cancel_from_page_ends_slow_turn(isolated_env, monkeypatch) -> None:
    async def scenario(webview, bridge):
        await _until(webview, "!document.getElementById('chat').hidden")
        await _js(webview, SEND % json.dumps("długo"))
        await _until(webview, "document.querySelector('.message--assistant')?.textContent")
        await _js(webview, "(() => { document.getElementById('stop').click(); return true; })()")
        await _js(webview, "(() => { document.getElementById('stop').click(); return true; })()")
        await _until(webview, "document.querySelector('[data-status=cancelled]') !== null")
        await asyncio.sleep(0.5)  # chunks after done would show up here
        return await _js(webview, STATE), list(bridge.dispatched)

    state, dispatched = _run(scenario, monkeypatch, agent="fake-slow")
    assert state["busy"] is False
    terminal = [e for e in dispatched if e["type"] in ("done", "error")]
    assert terminal == [{"type": "done", "stop_reason": "cancelled"}]
    end = dispatched.index(terminal[0])
    assert all(e["type"] != "text_delta" for e in dispatched[end:])
    assert state["messages"][-1]["role"] == "assistant"


def test_no_agents_shows_empty_screen(isolated_env, monkeypatch, tmp_path) -> None:
    async def scenario(webview, bridge):
        # init arrives on ready; with no agents the chat stays hidden and the empty state shows.
        async with asyncio.timeout(15):
            while not bridge.dispatched:
                await asyncio.sleep(0.05)
        await asyncio.sleep(0.2)
        return bridge.dispatched, await _js(webview, STATE)

    dispatched, state = _run(scenario, monkeypatch, config_path=tmp_path / "missing.toml")
    assert dispatched[0]["type"] == "init"
    assert dispatched[0]["agents"] == []
    assert state["screen"] == "empty"


def test_missing_agent_command_shows_error(isolated_env, monkeypatch) -> None:
    async def scenario(webview, bridge):
        await _until(webview, "!document.getElementById('chat').hidden")
        await _js(webview, SEND % json.dumps("x"))
        await _until(webview, "document.querySelector('.message--error') !== null")
        return await _js(webview, STATE)

    state = _run(scenario, monkeypatch, agent="fake-missing")
    assert state["busy"] is False
    assert state["messages"][-1]["role"] == "error"
    assert state["messages"][-1]["kind"] == "spawn"
