"""Undecorated panel window hosting the chat UI in a WebKit web view."""

import logging
import os
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("WebKit", "6.0")
from gi.repository import Adw, WebKit  # noqa: E402

from app.bridge import Bridge  # noqa: E402

log = logging.getLogger(__name__)

UI_DIR = Path(__file__).resolve().parent / "ui"
INDEX_HTML = UI_DIR / "index.html"
DEFAULT_WIDTH = 480
DEFAULT_HEIGHT = 900


class PanelWindow(Adw.ApplicationWindow):
    """The panel. Closing it only hides it; the application keeps running."""

    def __init__(self, application: Adw.Application, bridge: Bridge) -> None:
        super().__init__(application=application, title="AI Panel")
        self.set_decorated(False)
        self.set_default_size(DEFAULT_WIDTH, DEFAULT_HEIGHT)
        self.set_hide_on_close(True)

        self.bridge = bridge
        self.webview = WebKit.WebView()
        settings = self.webview.get_settings()
        settings.set_enable_developer_extras(os.environ.get("AI_PANEL_DEBUG") == "1")
        bridge.attach(self.webview.get_user_content_manager())
        self.set_content(self.webview)

        uri = INDEX_HTML.as_uri()
        log.debug("loading %s", uri)
        self.webview.load_uri(uri)
