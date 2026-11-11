"""Application ``pl.local.AiPanel``: background instance controlled through D-Bus actions.

Actions (PLAN §12.1): ``toggle``, ``show``, ``hide``, ``new-chat``, ``quit`` and the
read-only boolean state ``visible``. ``--background`` starts without showing the window.
With ``AI_PANEL_DEBUG=1`` also ``debug-send`` (s), ``debug-click`` (s) and ``debug-dump``
(see ``app/debug.py``).

The GLib main loop doubles as the asyncio loop (``gi.events.GLibEventLoopPolicy``), so
coroutines can be scheduled with ``Gio.Application.create_asyncio_task``.
Importing this module creates no window and needs no display.
"""

import asyncio
import logging
import os
import signal
import sys
from collections.abc import Sequence

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("GLibUnix", "2.0")
from gi.events import GLibEventLoopPolicy  # noqa: E402
from gi.repository import Adw, Gio, GLib, GLibUnix  # noqa: E402

from app import __version__, debug  # noqa: E402
from app.logging_setup import setup_logging  # noqa: E402

log = logging.getLogger(__name__)

APP_ID = "pl.local.AiPanel"
SIMPLE_ACTIONS = ("toggle", "show", "hide", "new-chat", "quit")
STATE_ACTIONS = ("visible",)
DEBUG_ACTIONS = ("debug-send", "debug-click", "debug-dump")
# Upper bound for stopping the agents at quit (SIGTERM, SIGKILL after 3 s in AcpBackend).
SHUTDOWN_TIMEOUT_S = 5.0


class AiPanelApplication(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self._window = None
        self._controller = None
        self._quitting = False
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
        if debug.debug_enabled():
            self._add_debug_actions()

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

    def _add_debug_actions(self) -> None:
        string = GLib.VariantType.new("s")
        for name, parameter, handler in (
            ("debug-send", string, self._on_debug_send),
            ("debug-click", string, self._on_debug_click),
            ("debug-dump", None, self._on_debug_dump),
        ):
            action = Gio.SimpleAction.new(name, parameter)
            action.connect("activate", handler)
            self.add_action(action)
        log.info("debug actions enabled")

    def _on_debug_send(self, _action, parameter: GLib.Variant) -> None:
        if self._window is not None:
            log.debug("debug-send")
            self._window.debug_send(parameter.get_string())

    def _on_debug_click(self, _action, parameter: GLib.Variant) -> None:
        if self._window is not None:
            log.debug("debug-click %r", parameter.get_string()[:200])
            self._window.debug_click(parameter.get_string())

    def _on_debug_dump(self, *_args) -> None:
        if self._window is not None:
            self._window.bridge.request_dump()

    def _write_dump(self, state: dict) -> None:
        window = self._window
        dump = debug.build_dump(
            state,
            visible=window is not None and window.get_visible(),
            uri=window.webview.get_uri() if window is not None else None,
        )
        try:
            path = debug.write_dump(dump)
        except (OSError, ValueError) as exc:
            log.error("writing the debug dump failed: %s", exc)
            return
        log.info("debug dump written to %s", path)

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
        log.info("new chat requested")
        if self._controller is not None:
            self._controller.new_chat()

    def _on_quit(self, *_args) -> None:
        log.info("quit requested")
        self._quit()

    def _quit(self) -> None:
        """Stop the agents first (FR-17: quit kills their processes), then end the loop."""
        if self._quitting:
            return
        self._quitting = True
        if self._controller is None:
            self.quit()
            return
        self.create_asyncio_task(self._shutdown())

    async def _shutdown(self) -> None:
        from app.backends import close_all

        try:
            async with asyncio.timeout(SHUTDOWN_TIMEOUT_S):
                await self._controller.close()
                await close_all()
        except TimeoutError:
            log.warning("agents did not stop within %g s", SHUTDOWN_TIMEOUT_S)
        except Exception:
            log.exception("stopping the agents failed")
        finally:
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

        from app.backends import get_backend
        from app.bridge import Bridge
        from app.config import load_config
        from app.controller import ChatController, default_agent_override
        from app.window import PanelWindow

        config = load_config()
        log.info(
            "configuration %s: %d agent(s), %d error(s)",
            config.path,
            len(config.agents),
            len(config.errors),
        )
        style = self._setup_style(config.chat.theme)
        bridge = Bridge()
        self._controller = ChatController(
            config,
            bridge,
            lambda agent: get_backend(agent, mcp=config.mcp),
            default_agent=default_agent_override(os.environ),
            system_dark=style.get_dark,
        )
        bridge.handler = self._controller
        if debug.debug_enabled():
            bridge.on_dump = self._write_dump
        style.connect("notify::dark", self._on_dark_changed)
        self._window = PanelWindow(self, bridge)
        self._window.connect("notify::visible", self._sync_visible)
        log.info("started %s %s", APP_ID, __version__)

    def _setup_style(self, theme: str) -> Adw.StyleManager:
        """``chat.theme`` forces light or dark for the window too; ``system`` follows GNOME."""
        style = self.get_style_manager()
        scheme = {
            "light": Adw.ColorScheme.FORCE_LIGHT,
            "dark": Adw.ColorScheme.FORCE_DARK,
        }.get(theme, Adw.ColorScheme.DEFAULT)
        style.set_color_scheme(scheme)
        return style

    def _on_dark_changed(self, *_args) -> None:
        if self._controller is not None:
            self._controller.refresh_theme()

    def do_activate(self) -> None:
        first = not self._activated
        self._activated = True
        if first and self._start_hidden:
            log.info("started in background")
            return
        self.show_panel()

    def _on_sigterm(self) -> bool:
        log.info("SIGTERM received, quitting")
        self._quit()
        return GLib.SOURCE_REMOVE


def main(argv: Sequence[str] | None = None) -> int:
    setup_logging()
    args = list(sys.argv if argv is None else argv)
    with GLibEventLoopPolicy():
        app = AiPanelApplication()
        return app.run(args)
