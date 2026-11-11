"""Command line tools: ``python -m app.cli …`` (PLAN §12.3; ``make cli ARGS="…"``).

Commands so far: ``check-config [--config P]``, ``agents [--json]``,
``secret set|delete|has NAME``, ``chat ID PROMPT [--json] [--permission deny|allow]
[--cancel-after S]``, ``test-agent ID`` and ``ui-dump``. No GTK import (``gi`` is loaded only
when a keyring value is needed and by ``ui-dump`` for D-Bus).

``ui-dump`` activates the ``debug-dump`` action of the running app (``AI_PANEL_DEBUG=1``) on
the session bus, waits until the app replaced the dump file and prints it; exit 1 when the
action cannot be called or no dump arrives within 5 s.

Exit codes of ``chat`` and ``test-agent``: 0 = the turn ended with ``Done`` / the test
passed, 2 = agent error, unknown agent ID or unsupported agent type, 130 = Ctrl+C.

``chat`` output: the reply text is streamed as it arrives; thinking, tool calls, permission
requests, usage and config options are lines prefixed with ``[thinking]``, ``[tool]``,
``[permission]``, ``[usage]``, ``[options]``; a stop reason other than ``end_turn`` is printed
as ``[done] <reason>``; errors go to stderr. ``--json`` prints one JSON object per line
(``event_to_dict``) plus ``{"type": "permission_response", ...}`` after each answered
permission request; the last line is the ``done`` or ``error`` event.
"""

import argparse
import asyncio
import contextlib
import getpass
import json
import logging
import math
import os
import re
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any, TextIO

from app import debug, diagnostics, strings
from app.backends import close_all, get_backend
from app.backends.base import (
    Backend,
    BackendError,
    ConfigOptions,
    Done,
    Error,
    Event,
    PermissionOption,
    PermissionRequest,
    TextDelta,
    ThinkingDelta,
    ToolCall,
    ToolUpdate,
    Usage,
    event_to_dict,
)
from app.config import AcpAgent, Agent, Config, ConfigError, load_config
from app.logging_setup import setup_logging
from app.secrets import InteractionRequired, LibsecretStore, SecretError, SecretStore

EXIT_AGENT_ERROR = 2
EXIT_INTERRUPTED = 130
TOOL_SNIPPET_LIMIT = 200

APP_ID = "pl.local.AiPanel"
APP_OBJECT_PATH = "/pl/local/AiPanel"
UI_DUMP_TIMEOUT_S = 5.0
DBUS_CALL_TIMEOUT_MS = 5000

SECRET_VALUE_LIMIT = 64 * 1024
_SECRET_NAME_RE = re.compile(r"[^\x00-\x1f\x7f]{1,256}")


def format_issue(config: Config, issue: ConfigError) -> str:
    """``path: message``; file-level problems use ``file[:line]: message``."""
    if issue.path:
        return f"{issue.path}: {issue.message}"
    location = str(config.path) if issue.line is None else f"{config.path}:{issue.line}"
    return f"{location}: {issue.message}"


def cmd_check_config(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    for issue in config.errors:
        print(format_issue(config, issue))
    for issue in config.warnings:
        print(strings.CLI_WARNING_PREFIX + format_issue(config, issue))
    if config.errors:
        print(strings.CLI_CONFIG_ERRORS.format(count=len(config.errors), file=config.path))
        return 1
    if not config.exists:
        print(strings.CLI_CONFIG_MISSING.format(file=config.path))
    else:
        print(
            strings.CLI_CONFIG_OK.format(
                file=config.path, agents=len(config.agents), mcp=len(config.mcp)
            )
        )
    return 0


def cmd_agents(args: argparse.Namespace) -> int:
    config = load_config()
    # Only valid agents are listed; skipped ones are reported on stderr.
    items = [
        {
            "id": agent.id,
            "type": agent.type,
            "name": agent.name,
            "valid": True,
            "default": agent.id == config.default_agent,
        }
        for agent in config.agents.values()
    ]
    if args.json:
        print(json.dumps(items, ensure_ascii=False, indent=2))
    elif not items:
        print(strings.CLI_NO_AGENTS)
    else:
        for item in items:
            mark = strings.CLI_DEFAULT_MARK if item["default"] else ""
            print(f"{item['id']}\t{item['type']}\t{item['name']}{mark}")
    if config.skipped_agents:
        print(
            strings.CLI_AGENTS_SKIPPED.format(ids=", ".join(config.skipped_agents)),
            file=sys.stderr,
        )
    return 0


def make_store() -> SecretStore:
    """Keyring used by the ``secret`` commands (replaced in tests)."""
    return LibsecretStore()


def print_error(message: str) -> None:
    print(strings.CLI_ERROR_PREFIX + message, file=sys.stderr)


async def terminal_prompt(label: str) -> str | None:
    """``prompt`` source in the terminal: ``getpass`` on a TTY, otherwise an error."""
    if not sys.stdin or not sys.stdin.isatty():
        raise InteractionRequired(strings.SECRET_NEEDS_INTERACTION.format(label=label))
    value = await asyncio.to_thread(getpass.getpass, f"{label}: ")
    return value or None


def read_secret_value(name: str) -> str:
    """Secret from stdin (``getpass`` on a TTY) without trailing newlines."""
    if sys.stdin.isatty():
        value = getpass.getpass(strings.CLI_SECRET_PROMPT.format(name=name))
    else:
        raw = sys.stdin.buffer.read(SECRET_VALUE_LIMIT + 1)
        if len(raw) > SECRET_VALUE_LIMIT:
            raise SecretError(strings.CLI_SECRET_TOO_LONG.format(limit=SECRET_VALUE_LIMIT))
        try:
            value = raw.decode("utf-8")
        except UnicodeDecodeError:
            raise SecretError(strings.CLI_SECRET_NOT_UTF8) from None
    value = value.rstrip("\r\n")
    if not value:
        raise SecretError(strings.CLI_SECRET_EMPTY)
    return value


def cmd_secret(args: argparse.Namespace) -> int:
    name = args.name
    if not _SECRET_NAME_RE.fullmatch(name) or not name.strip():
        print_error(strings.CLI_SECRET_BAD_NAME.format(name=name))
        return 1
    store = make_store()
    try:
        # Checked first, so nobody types a secret that cannot be stored.
        store.ensure_available()
        action = args.secret_command
        if action == "set":
            store.set(name, read_secret_value(name))
            print(strings.CLI_SECRET_SAVED.format(name=name))
            return 0
        if action == "delete":
            if store.delete(name):
                print(strings.CLI_SECRET_DELETED.format(name=name))
                return 0
            print(strings.CLI_SECRET_NOT_FOUND.format(name=name))
            return 1
        if store.has(name):
            print(strings.CLI_SECRET_EXISTS.format(name=name))
            return 0
        print(strings.CLI_SECRET_NOT_FOUND.format(name=name))
        return 1
    except SecretError as exc:
        print_error(str(exc))
        return 1


# -- chat and test-agent -----------------------------------------------------------------------


def setup_cli_logging() -> None:
    """Log file as in the app; stderr only shows errors unless ``AI_PANEL_LOG_LEVEL`` is set
    (the CLI prints its own messages)."""
    stderr_level = None if os.environ.get("AI_PANEL_LOG_LEVEL") else logging.ERROR
    setup_logging(stderr_level=stderr_level)


def find_agent(config: Config, agent_id: str) -> Agent | None:
    """The agent or ``None`` after printing why it cannot be used (unknown / skipped ID with
    the list of available agents, unsupported type)."""
    agent = config.agents.get(agent_id)
    if agent is None:
        if agent_id in config.skipped_agents:
            print_error(strings.CLI_SKIPPED_AGENT.format(id=agent_id))
        else:
            print_error(strings.CLI_UNKNOWN_AGENT.format(id=agent_id))
        if config.agents:
            print(
                strings.CLI_AVAILABLE_AGENTS.format(ids=", ".join(config.agents)), file=sys.stderr
            )
        else:
            print(strings.CLI_NO_AGENTS, file=sys.stderr)
        return None
    if not isinstance(agent, AcpAgent):
        print_error(strings.CLI_UNSUPPORTED_AGENT_TYPE.format(type=agent.type))
        return None
    return agent


def choose_permission(options: list[PermissionOption], policy: str) -> str | None:
    """Option id for ``--permission allow`` (``allow_once`` preferred); ``None`` rejects."""
    if policy != "allow":
        return None
    for wanted in ("allow_once", "allow_always"):
        for option in options:
            if option.kind == wanted:
                return option.id
    return None


def _tool_text(content: Any) -> str | None:
    """First text of an ACP tool ``content`` list, shortened to one line."""
    if not isinstance(content, list):
        return None
    for item in content:
        inner = item.get("content") if isinstance(item, dict) else None
        if isinstance(inner, dict) and isinstance(inner.get("text"), str) and inner["text"]:
            text = " ".join(inner["text"].split())
            if len(text) > TOOL_SNIPPET_LIMIT:
                text = text[: TOOL_SNIPPET_LIMIT - 1] + "…"
            return text
    return None


class TextPrinter:
    """Human-readable stream: reply text as it comes, other events as prefixed lines."""

    def __init__(self, out: TextIO, err: TextIO) -> None:
        self.out = out
        self.err = err
        self._mode: str | None = None  # "text" / "thinking" while a fragment stream runs
        self._line_start = True
        self._tools: dict[str, str] = {}

    def _write(self, text: str) -> None:
        if not text:
            return
        self.out.write(text)
        self.out.flush()
        self._line_start = text.endswith("\n")

    def _end_line(self) -> None:
        if not self._line_start:
            self._write("\n")
        self._mode = None

    def line(self, prefix: str, text: str) -> None:
        self._end_line()
        self._write(f"[{prefix}] {text}\n")

    def _stream(self, mode: str, text: str, prefix: str = "") -> None:
        if self._mode != mode:
            self._end_line()
            self._mode = mode
        for index, part in enumerate(text.split("\n")):
            if index:
                self._write("\n")
            if part:
                if self._line_start and prefix:
                    self._write(prefix)
                self._write(part)

    def event(self, event: Event) -> None:
        match event:
            case TextDelta(text=text):
                self._stream("text", text)
            case ThinkingDelta(text=text):
                self._stream("thinking", text, "[thinking] ")
            case ToolCall():
                title = event.title or strings.CLI_TOOL_UNTITLED.format(id=event.id)
                self._tools[event.id] = title
                details = ", ".join(p for p in (event.kind, event.status) if p)
                self.line("tool", f"{title} ({details})" if details else title)
            case ToolUpdate():
                if event.title:
                    self._tools[event.id] = event.title
                title = self._tools.get(event.id) or strings.CLI_TOOL_UNTITLED.format(id=event.id)
                snippet = _tool_text(event.content)
                if event.status or event.title or snippet:
                    text = f"{title}: {event.status}" if event.status else title
                    self.line("tool", f"{text} – {snippet}" if snippet else text)
            case PermissionRequest():
                title = event.title or strings.CLI_TOOL_UNTITLED.format(id=event.tool_call_id)
                names = ", ".join(f"{o.name} [{o.kind or o.id}]" for o in event.options)
                options = names or strings.CLI_TEST_NONE
                self.line(
                    "permission",
                    strings.CLI_PERMISSION_OPTIONS.format(title=title, options=options),
                )
            case Usage():
                text = strings.CLI_USAGE.format(
                    used="?" if event.used is None else event.used,
                    size="?" if event.size is None else event.size,
                )
                if event.cost_amount is not None:
                    text += strings.CLI_USAGE_COST.format(
                        amount=event.cost_amount, currency=event.cost_currency or ""
                    ).rstrip()
                self.line("usage", text)
            case ConfigOptions(options=options):
                parts = []
                for option in options:
                    label = option.get("name") or option.get("id") or "?"
                    value = option.get("currentValue")
                    parts.append(f"{label}={value}" if value is not None else str(label))
                self.line("options", ", ".join(parts))
            case Done(stop_reason=reason):
                self._end_line()
                if reason != "end_turn":
                    self._write(f"[done] {reason}\n")
            case Error():
                self._end_line()
                print(strings.CLI_ERROR_PREFIX + event.message, file=self.err, flush=True)

    def permission_answer(self, request: PermissionRequest, option_id: str | None) -> None:
        title = request.title or strings.CLI_TOOL_UNTITLED.format(id=request.tool_call_id)
        if option_id is None:
            has_allow = any((o.kind or "").startswith("allow") for o in request.options)
            template = (
                strings.CLI_PERMISSION_DENIED
                if has_allow
                else strings.CLI_PERMISSION_DENIED_NO_ALLOW
            )
            self.line("permission", template.format(title=title))
            return
        name = next((o.name for o in request.options if o.id == option_id), option_id)
        self.line("permission", strings.CLI_PERMISSION_ALLOWED.format(title=title, option=name))


class JsonPrinter:
    """JSON Lines: one ``event_to_dict`` object per line."""

    def __init__(self, out: TextIO) -> None:
        self.out = out

    def _emit(self, obj: dict[str, Any]) -> None:
        self.out.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n")
        self.out.flush()

    def event(self, event: Event) -> None:
        self._emit(event_to_dict(event))

    def permission_answer(self, request: PermissionRequest, option_id: str | None) -> None:
        self._emit(
            {
                "type": "permission_response",
                "request_id": request.request_id,
                "option_id": option_id,
                "allowed": option_id is not None,
            }
        )


async def _cancel_later(backend: Backend, session_id: str, delay: float) -> None:
    await asyncio.sleep(delay)
    await backend.cancel(session_id)


async def run_chat(
    backend: Backend,
    prompt: str,
    printer: TextPrinter | JsonPrinter,
    *,
    permission: str = "deny",
    cancel_after: float | None = None,
) -> int:
    """One turn on a new session; 0 after ``Done``, 2 after ``Error``."""
    try:
        session_id = await backend.new_session()
    except BackendError as exc:
        printer.event(exc.event)
        return EXIT_AGENT_ERROR
    result = EXIT_AGENT_ERROR

    async def consume() -> None:
        nonlocal result
        async for event in backend.send(session_id, [{"type": "text", "text": prompt}]):
            printer.event(event)
            if isinstance(event, PermissionRequest):
                option_id = choose_permission(event.options, permission)
                backend.respond_permission(event.request_id, option_id)
                printer.permission_answer(event, option_id)
            elif isinstance(event, Done):
                result = 0
            elif isinstance(event, Error):
                result = EXIT_AGENT_ERROR

    consumer = asyncio.create_task(consume(), name="cli-chat-turn")
    canceller = None
    try:
        if cancel_after is not None:
            # ``send()`` registers the turn only when the iteration starts; one loop step lets
            # the consumer get that far, so even ``--cancel-after 0`` hits a running turn
            # (``cancel()`` on a session without a turn is a no-op).
            await asyncio.sleep(0)
            canceller = asyncio.create_task(_cancel_later(backend, session_id, cancel_after))
        await consumer
    finally:
        if not consumer.done():
            consumer.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await consumer
        if canceller is not None:
            canceller.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await canceller
    return result


async def _chat_main(args: argparse.Namespace, config: Config, agent: Agent) -> int:
    backend = get_backend(agent, mcp=config.mcp, store=make_store(), prompt_cb=terminal_prompt)
    printer = JsonPrinter(sys.stdout) if args.json else TextPrinter(sys.stdout, sys.stderr)
    try:
        return await run_chat(
            backend,
            args.prompt,
            printer,
            permission=args.permission,
            cancel_after=args.cancel_after,
        )
    finally:
        await close_all()


def cmd_chat(args: argparse.Namespace) -> int:
    config = load_config()
    agent = find_agent(config, args.agent_id)
    if agent is None:
        return EXIT_AGENT_ERROR
    setup_cli_logging()
    try:
        return asyncio.run(_chat_main(args, config, agent))
    except KeyboardInterrupt:
        print(file=sys.stderr)
        print_error(strings.CLI_INTERRUPTED)
        return EXIT_INTERRUPTED


def print_test_result(result: diagnostics.TestResult) -> None:
    if result.agent_info is not None or result.protocol_version is not None:
        print(strings.CLI_TEST_AGENT.format(name=diagnostics.describe_agent(result.agent_info)))
    if result.protocol_version is not None:
        print(strings.CLI_TEST_PROTOCOL.format(version=result.protocol_version))
        methods = ", ".join(str(m.get("name") or m.get("id") or "?") for m in result.auth_methods)
        print(strings.CLI_TEST_AUTH_METHODS.format(methods=methods or strings.CLI_TEST_NONE))
    if result.ok:
        print(strings.CLI_TEST_OK)
    elif result.error is not None:
        print(strings.CLI_TEST_FAILED.format(message=diagnostics.describe_error(result.error)))


def cmd_test_agent(args: argparse.Namespace) -> int:
    config = load_config()
    agent = find_agent(config, args.agent_id)
    if agent is None:
        return EXIT_AGENT_ERROR
    setup_cli_logging()
    try:
        result = asyncio.run(
            diagnostics.test_agent(
                agent, mcp=config.mcp, store=make_store(), prompt_cb=terminal_prompt
            )
        )
    except KeyboardInterrupt:
        print(file=sys.stderr)
        print_error(strings.CLI_INTERRUPTED)
        return EXIT_INTERRUPTED
    print_test_result(result)
    return 0 if result.ok else EXIT_AGENT_ERROR


def activate_app_action(name: str) -> None:
    """Activate the parameterless action ``name`` of the running app over the session bus.

    Raises ``RuntimeError`` with the D-Bus error text. The app is never D-Bus-activated.
    """
    import gi

    gi.require_version("Gio", "2.0")
    from gi.repository import Gio, GLib

    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        bus.call_sync(
            APP_ID,
            APP_OBJECT_PATH,
            "org.gtk.Actions",
            "Activate",
            GLib.Variant("(sava{sv})", (name, [], {})),
            None,
            Gio.DBusCallFlags.NO_AUTO_START,
            DBUS_CALL_TIMEOUT_MS,
            None,
        )
    except GLib.Error as exc:
        raise RuntimeError(exc.message) from None


def _file_stamp(path: Path) -> tuple[int, int, int] | None:
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_ino, st.st_mtime_ns, st.st_size)


def cmd_ui_dump(args: argparse.Namespace) -> int:
    path = debug.dump_path()
    before = _file_stamp(path)
    try:
        activate_app_action("debug-dump")
    except RuntimeError as exc:
        print_error(strings.CLI_UI_DUMP_NO_APP.format(reason=exc))
        return 1
    deadline = time.monotonic() + args.timeout
    while True:
        stamp = _file_stamp(path)
        # The app replaces the file atomically, so a new stamp means a complete new dump.
        if stamp is not None and stamp != before:
            try:
                text = path.read_text(encoding="utf-8")
                json.loads(text)
            except (OSError, ValueError):
                pass
            else:
                sys.stdout.write(text if text.endswith("\n") else text + "\n")
                return 0
        if time.monotonic() >= deadline:
            print_error(strings.CLI_UI_DUMP_TIMEOUT.format(file=path, seconds=args.timeout))
            return 1
        time.sleep(0.05)


def seconds(value: str) -> float:
    try:
        number = float(value)
    except ValueError:
        number = math.nan
    if not math.isfinite(number) or number < 0:
        raise argparse.ArgumentTypeError(strings.CLI_BAD_SECONDS.format(value=value))
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description=strings.CLI_DESCRIPTION)
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check-config", help=strings.CLI_HELP_CHECK_CONFIG)
    check.add_argument("--config", type=Path, default=None, help=strings.CLI_HELP_CONFIG_PATH)
    check.set_defaults(func=cmd_check_config)

    agents = sub.add_parser("agents", help=strings.CLI_HELP_AGENTS)
    agents.add_argument("--json", action="store_true", help=strings.CLI_HELP_JSON)
    agents.set_defaults(func=cmd_agents)

    secret = sub.add_parser("secret", help=strings.CLI_HELP_SECRET)
    secret_sub = secret.add_subparsers(dest="secret_command", required=True)
    for command, help_text in (
        ("set", strings.CLI_HELP_SECRET_SET),
        ("delete", strings.CLI_HELP_SECRET_DELETE),
        ("has", strings.CLI_HELP_SECRET_HAS),
    ):
        item = secret_sub.add_parser(command, help=help_text)
        item.add_argument("name", metavar="NAME", help=strings.CLI_HELP_SECRET_NAME)
        item.set_defaults(func=cmd_secret)

    chat = sub.add_parser("chat", help=strings.CLI_HELP_CHAT)
    chat.add_argument("agent_id", metavar="ID", help=strings.CLI_HELP_AGENT_ID)
    chat.add_argument("prompt", metavar="PROMPT", help=strings.CLI_HELP_PROMPT)
    chat.add_argument("--json", action="store_true", help=strings.CLI_HELP_CHAT_JSON)
    chat.add_argument(
        "--permission", choices=("deny", "allow"), default="deny", help=strings.CLI_HELP_PERMISSION
    )
    chat.add_argument(
        "--cancel-after",
        type=seconds,
        default=None,
        metavar="S",
        help=strings.CLI_HELP_CANCEL_AFTER,
    )
    chat.set_defaults(func=cmd_chat)

    test = sub.add_parser("test-agent", help=strings.CLI_HELP_TEST_AGENT)
    test.add_argument("agent_id", metavar="ID", help=strings.CLI_HELP_AGENT_ID)
    test.set_defaults(func=cmd_test_agent)

    ui_dump = sub.add_parser("ui-dump", help=strings.CLI_HELP_UI_DUMP)
    ui_dump.set_defaults(func=cmd_ui_dump, timeout=UI_DUMP_TIMEOUT_S)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
