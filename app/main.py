"""Application ``pl.local.AiPanel``: background instance controlled through D-Bus actions.

Actions (PLAN §12.1): ``toggle``, ``show``, ``hide``, ``new-chat``, ``quit`` and the
read-only boolean state ``visible``. ``--background`` starts without showing the window.

The GLib main loop doubles as the asyncio loop (``gi.events.GLibEventLoopPolicy``), so
coroutines can be scheduled with ``Gio.Application.create_asyncio_task``.
Importing this module creates no window and needs no display.
"""

import logging
import signal
import sys
from collections.abc import Sequence

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("GLibUnix", "2.0")
from gi.events import GLibEventLoopPolicy  # noqa: E402
from gi.repository import Adw, Gio, GLib, GLibUnix  # noqa: E402

from app import __version__  # noqa: E402
from app.logging_setup import setup_logging  # noqa: E402

log = logging.getLogger(__name__)

APP_ID = "pl.local.AiPanel"
SIMPLE_ACTIONS = ("toggle", "show", "hide", "new-chat", "quit")
STATE_ACTIONS = ("visible",)


class AiPanelApplication(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self._window = None
        self._start_hidden = False
        self._activated = False
        self.add_main_option(
            "background",
            0,
            GLib.OptionFlags.NONE,
            GLib.OptionArg.NONE,
            "Start without showing the window",
            None,
        )
        self._add_actions()

    # -- actions ---------------------------------------------------------------------------

    def _add_actions(self) -> None:
        handlers = {
            "toggle": self._on_toggle,
            "show": self._on_show,
            "hide": self._on_hide,
            "new-chat": self._on_new_chat,
            "quit": self._on_quit,
        }
        for name in SIMPLE_ACTIONS:
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", handlers[name])
            self.add_action(action)

        # Read-only: the state follows the window. Activation and SetState are ignored.
        visible = Gio.SimpleAction.new_stateful("visible", None, GLib.Variant("b", False))
        visible.connect("activate", self._on_readonly_action)
        visible.connect("change-state", self._on_readonly_action)
        self.add_action(visible)

    def _on_toggle(self, *_args) -> None:
        if self._window is not None and self._window.get_visible():
            self.hide_panel()
        else:
            self.show_panel()

    def _on_show(self, *_args) -> None:
        self.show_panel()

    def _on_hide(self, *_args) -> None:
        self.hide_panel()

    def _on_new_chat(self, *_args) -> None:
        # Conversations arrive with the controller (S3); until then the action is a no-op.
        log.info("new chat requested")

    def _on_quit(self, *_args) -> None:
        log.info("quit requested")
        self.quit()

    def _on_readonly_action(self, action: Gio.SimpleAction, _value) -> None:
        log.debug("ignoring attempt to change read-only action %r", action.get_name())

    def _sync_visible(self, *_args) -> None:
        visible = self._window is not None and self._window.get_visible()
        action = self.lookup_action("visible")
        if action.get_state().get_boolean() != visible:
            action.set_state(GLib.Variant("b", visible))
            log.debug("visible=%s", visible)

    def show_panel(self) -> None:
        if self._window is None:
            return
        self._window.present()

    def hide_panel(self) -> None:
        if self._window is None:
            return
        self._window.set_visible(False)

    # -- lifecycle -------------------------------------------------------------------------

    def do_handle_local_options(self, options: GLib.VariantDict) -> int:
        if options.contains("background"):
            self.register(None)
            if self.get_is_remote():
                # Another instance is running; --background must not show its window.
                return 0
            self._start_hidden = True
        return -1

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        # Keep running with the window hidden; only the quit action ends the process.
        self.hold()
        GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, self._on_sigterm)

        from app.bridge import Bridge
        from app.window import PanelWindow

        self._window = PanelWindow(self, Bridge())
        self._window.connect("notify::visible", self._sync_visible)
        log.info("started %s %s", APP_ID, __version__)

    def do_activate(self) -> None:
        first = not self._activated
        self._activated = True
        if first and self._start_hidden:
            log.info("started in background")
            return
        self.show_panel()

    def _on_sigterm(self) -> bool:
        log.info("SIGTERM received, quitting")
        self.quit()
        return GLib.SOURCE_REMOVE


def main(argv: Sequence[str] | None = None) -> int:
    setup_logging()
    args = list(sys.argv if argv is None else argv)
    with GLibEventLoopPolicy():
        app = AiPanelApplication()
        return app.run(args)
