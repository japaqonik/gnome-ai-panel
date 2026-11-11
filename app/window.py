"""Undecorated panel window hosting the chat UI in a WebKit web view.

Navigation policy (``app/links.py``): the web view only ever shows ``app/ui/index.html``;
``http``/``https``/``mailto`` links open outside the app (``Gtk.UriLauncher``), anything else
is blocked, and so are new windows. With ``AI_PANEL_URI_LOG`` set the URIs are appended to
that file instead of being launched (tests).
"""

import logging
import os
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("WebKit", "6.0")
from gi.repository import Adw, Gtk, WebKit  # noqa: E402

from app import debug, links  # noqa: E402
from app.bridge import Bridge  # noqa: E402

log = logging.getLogger(__name__)

UI_DIR = Path(__file__).resolve().parent / "ui"
INDEX_HTML = UI_DIR / "index.html"
DEFAULT_WIDTH = 480
DEFAULT_HEIGHT = 900
URI_LOG_ENV = "AI_PANEL_URI_LOG"


class PanelWindow(Adw.ApplicationWindow):
    """The panel. Closing it only hides it; the application keeps running."""

    def __init__(self, application: Adw.Application, bridge: Bridge) -> None:
        super().__init__(application=application, title="AI Panel")
        self.set_decorated(False)
        self.set_default_size(DEFAULT_WIDTH, DEFAULT_HEIGHT)
        self.set_hide_on_close(True)

        self.debug = debug.debug_enabled()
        self.index_uri = INDEX_HTML.as_uri()
        self.bridge = bridge
        self.webview = WebKit.WebView()
        settings = self.webview.get_settings()
        settings.set_enable_developer_extras(self.debug)
        settings.set_javascript_can_open_windows_automatically(False)
        self._hidden_menu_actions = {
            getattr(WebKit.ContextMenuAction, name)
            for name in links.hidden_menu_actions(self.debug)
        }
        self.webview.connect("decide-policy", self._on_decide_policy)
        self.webview.connect("context-menu", self._on_context_menu)
        bridge.attach(self.webview)
        self.set_content(self.webview)

        log.debug("loading %s", self.index_uri)
        self.webview.load_uri(self.index_uri)

    # -- navigation ------------------------------------------------------------------------

    def _on_decide_policy(
        self,
        _webview: WebKit.WebView,
        decision: WebKit.PolicyDecision,
        decision_type: WebKit.PolicyDecisionType,
    ) -> bool:
        if decision_type == WebKit.PolicyDecisionType.RESPONSE:
            return False  # the navigation itself was already checked
        new_window = decision_type == WebKit.PolicyDecisionType.NEW_WINDOW_ACTION
        action = decision.get_navigation_action()
        uri = action.get_request().get_uri()
        verdict = links.decide(uri, self.index_uri, new_window=new_window)
        if verdict is links.Decision.ALLOW:
            decision.use()
            return True
        decision.ignore()
        if verdict is links.Decision.LAUNCH:
            self.open_external(uri)
        else:
            log.warning("navigation blocked: %s", _short(uri))
        return True

    def open_external(self, uri: str) -> None:
        """Open ``uri`` in the default application; only ``http``/``https``/``mailto``."""
        if not links.is_external(uri):
            log.warning("not opening %s: scheme not allowed", _short(uri))
            return
        uri_log = os.environ.get(URI_LOG_ENV)
        if uri_log:
            try:
                with open(uri_log, "a", encoding="utf-8") as handle:
                    handle.write(uri + "\n")
            except OSError as exc:
                log.error("cannot write %s: %s", URI_LOG_ENV, exc.strerror or exc)
            else:
                log.info("link logged to %s instead of launching", URI_LOG_ENV)
            return
        log.info("opening link in the default application")
        Gtk.UriLauncher.new(uri).launch(self, None, self._on_launched, None)

    @staticmethod
    def _on_launched(launcher: Gtk.UriLauncher, result, _data) -> None:
        try:
            launcher.launch_finish(result)
        except Exception as exc:  # GLib.Error: no handler, cancelled by the user
            log.warning("opening the link failed: %s", getattr(exc, "message", exc))

    def _on_context_menu(self, _webview, menu: WebKit.ContextMenu, _hit_test) -> bool:
        for item in list(menu.get_items()):
            if item.get_stock_action() in self._hidden_menu_actions:
                menu.remove(item)
        # Drop separators left at the edges or doubled by the removals.
        items = list(menu.get_items())
        previous_separator = True
        for item in items:
            if item.is_separator() and previous_separator:
                menu.remove(item)
                continue
            previous_separator = item.is_separator()
        remaining = list(menu.get_items())
        if remaining and remaining[-1].is_separator():
            menu.remove(remaining[-1])
        return not menu.get_items()  # True = no menu at all

    # -- debug actions (AI_PANEL_DEBUG=1) --------------------------------------------------

    def debug_send(self, text: str) -> None:
        self.bridge.run_script(debug.send_script(text), "debug-send")

    def debug_click(self, selector: str) -> None:
        self.bridge.run_script(debug.click_script(selector), "debug-click")


def _short(uri: str | None, limit: int = 120) -> str:
    text = repr(uri or "")
    return text if len(text) <= limit else text[: limit - 1] + "…"
