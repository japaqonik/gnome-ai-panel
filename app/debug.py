"""Debug support (PLAN §12.1): the UI state dump and the scripts of the debug actions.

The actions ``debug-send``, ``debug-click`` and ``debug-dump`` exist only with
``AI_PANEL_DEBUG=1``. ``debug-dump`` asks the page for its state (``request_dump``), the page
answers with ``dump {state}`` and ``write_dump`` stores it in
``$XDG_STATE_HOME/gnome-ai-panel/debug-dump.json``; ``python -m app.cli ui-dump`` triggers
the action and prints that file. No GTK import.
"""

import json
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from app.logging_setup import state_dir

DEBUG_ENV = "AI_PANEL_DEBUG"
DUMP_FILE_NAME = "debug-dump.json"

# Keys of the dump the page may provide (PLAN §12.1); anything else is dropped. ``visible``,
# ``pinned`` (no pinning yet: always false) and ``uri`` (of the web view) come from Python.
PAGE_KEYS = (
    "screen",
    "agent",
    "badge",
    "messages",
    "permission_dialog",
    "banner",
    "theme",
    "busy",
)


def debug_enabled(environ: Mapping[str, str] | None = None) -> bool:
    return (os.environ if environ is None else environ).get(DEBUG_ENV) == "1"


def dump_path() -> Path:
    return state_dir() / DUMP_FILE_NAME


def build_dump(state: Mapping[str, Any], *, visible: bool, uri: str | None) -> dict[str, Any]:
    """The dump document: the page's known keys plus what only Python knows."""
    dump: dict[str, Any] = {"visible": visible}
    for key in PAGE_KEYS:
        if key in state:
            dump[key] = state[key]
    dump["pinned"] = False
    dump["uri"] = uri
    return dump


def write_dump(dump: Mapping[str, Any], path: Path | None = None) -> Path:
    """Write ``dump`` atomically (replace, mode 0600: it holds the conversation)."""
    target = dump_path() if path is None else path
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    data = json.dumps(dump, ensure_ascii=False, indent=2, allow_nan=False, default=str)
    fd, tmp = tempfile.mkstemp(prefix=".debug-dump-", suffix=".json", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(data + "\n")
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return target


def js_string(value: str) -> str:
    """``value`` as a JavaScript string literal that cannot break out of a script."""
    return (
        json.dumps(value, ensure_ascii=True)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )


def send_script(text: str) -> str:
    """Types ``text`` into the prompt and submits it the way the send button does.

    The page's own send path runs (``requestSubmit`` → ``submit``), so its busy check and the
    send → done/error contract hold: while a turn runs the page keeps the text and sends
    nothing, as when the user presses Enter.
    """
    return (
        "(() => {"
        " const prompt = document.getElementById('prompt');"
        " const form = document.getElementById('composer');"
        " if (!prompt || !form || form.closest('[hidden]')) return false;"
        f" prompt.value = {js_string(text)};"
        " prompt.dispatchEvent(new Event('input', {bubbles: true}));"
        " form.requestSubmit();"
        " return true;"
        "})()"
    )


def click_script(selector: str) -> str:
    """Clicks the first element matching the CSS ``selector``; ``false`` when none (or the
    selector is invalid)."""
    return (
        "(() => {"
        " let node;"
        f" try {{ node = document.querySelector({js_string(selector)}); }}"
        " catch { return false; }"
        " if (!node) return false;"
        " node.click();"
        " return true;"
        "})()"
    )
