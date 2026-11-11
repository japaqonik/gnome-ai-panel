"""Value sources (FR-21, PLAN §13): ``keyring``, ``env``, ``command``, ``prompt``, ``literal``.

``resolve()`` turns one ``ValueSource`` from ``app/config.py`` into a string, ``None`` (no
value: unset variable, missing keyring item, cancelled prompt) or raises ``SecretError``.
``resolve_env()`` does this for every ``env`` entry of an agent or MCP server; entries without
a value are skipped (INFO log with the variable name only).

Rules for secret values:

- they are never logged and never part of an error message (``str(error)``);
- every resolved keyring/command/prompt value (and env/literal values of variables whose name
  looks secret) is registered with the log redaction filter (``app/logging_setup.py``);
- ``command`` runs without a shell (``shlex.split``), with stdin closed, stderr discarded and
  a timeout; the error for a failing command contains the program name and exit code only.

Keyring: libsecret through GI (``Secret-1``), schema ``pl.local.AiPanel.Secret`` with the
attribute ``name``. ``gi`` is imported lazily, so importing this module does not load GI.
The Secret Service is only used when ``org.freedesktop.secrets`` already has an owner on the
session bus; it is never D-Bus-activated by us. Activation would start a keyring daemon with
whatever environment the bus has (in tests: the developer's real home).
"""

import asyncio
import contextlib
import logging
import os
import shlex
import signal
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from app import strings
from app.config import SECRET_NAME_RE, Command, Env, Keyring, Literal, Prompt, ValueSource
from app.logging_setup import register_secret

log = logging.getLogger(__name__)

SCHEMA_NAME = "pl.local.AiPanel.Secret"
SCHEMA_ATTRIBUTE = "name"
SECRETS_BUS_NAME = "org.freedesktop.secrets"
DBUS_TIMEOUT_MS = 5000
COMMAND_OUTPUT_LIMIT = 1024 * 1024

# Called with the label to show; returns the value or None when the user cancels.
type PromptCallback = Callable[[str], Awaitable[str | None]]


class SecretError(Exception):
    """A value could not be resolved. The message never contains the value."""


class SecretServiceUnavailable(SecretError):
    """No Secret Service on the session bus (or no session bus)."""


class InteractionRequired(SecretError):
    """A ``prompt`` source was used where nobody can answer (no TTY, no UI)."""


# -- stores --------------------------------------------------------------------------------


class SecretStore(Protocol):
    def ensure_available(self) -> None:
        """Raise ``SecretServiceUnavailable`` when the store cannot be used."""

    def get(self, name: str) -> str | None: ...

    def set(self, name: str, value: str) -> None: ...

    def delete(self, name: str) -> bool:
        """Return False when there was nothing to delete."""
        ...

    def has(self, name: str) -> bool: ...


@dataclass
class MemoryStore:
    """In-memory store for tests."""

    items: dict[str, str] = field(default_factory=dict)

    def ensure_available(self) -> None:
        return None

    def get(self, name: str) -> str | None:
        return self.items.get(name)

    def set(self, name: str, value: str) -> None:
        self.items[name] = value

    def delete(self, name: str) -> bool:
        return self.items.pop(name, None) is not None

    def has(self, name: str) -> bool:
        return name in self.items


class LibsecretStore:
    """Secret Service (GNOME Keyring) through libsecret. Methods are blocking; call them from
    a worker thread inside the event loop (``resolve()`` does)."""

    def __init__(self) -> None:
        self._secret: Any = None
        self._schema: Any = None

    def _modules(self) -> tuple[Any, Any, Any]:
        import gi

        gi.require_version("Secret", "1")
        from gi.repository import Gio, GLib, Secret

        return Gio, GLib, Secret

    def ensure_available(self) -> None:
        try:
            gio, glib, secret = self._modules()
        except (ImportError, ValueError) as exc:
            raise SecretServiceUnavailable(strings.SECRET_NO_SERVICE.format(reason=exc)) from None
        try:
            bus = gio.bus_get_sync(gio.BusType.SESSION, None)
            reply = bus.call_sync(
                "org.freedesktop.DBus",
                "/org/freedesktop/DBus",
                "org.freedesktop.DBus",
                "NameHasOwner",
                glib.Variant("(s)", (SECRETS_BUS_NAME,)),
                glib.VariantType("(b)"),
                gio.DBusCallFlags.NONE,
                DBUS_TIMEOUT_MS,
                None,
            )
        except glib.Error:
            raise SecretServiceUnavailable(
                strings.SECRET_NO_SERVICE.format(reason=strings.SECRET_NO_BUS)
            ) from None
        if not reply.unpack()[0]:
            raise SecretServiceUnavailable(
                strings.SECRET_NO_SERVICE.format(reason=strings.SECRET_NOT_RUNNING)
            )
        if self._schema is None:
            self._secret = secret
            self._schema = secret.Schema.new(
                SCHEMA_NAME,
                secret.SchemaFlags.NONE,
                {SCHEMA_ATTRIBUTE: secret.SchemaAttributeType.STRING},
            )

    def _call(self, func_name: str, *args: Any) -> Any:
        self.ensure_available()
        _, glib, _ = self._modules()
        try:
            return getattr(self._secret, func_name)(self._schema, *args)
        except glib.Error as exc:
            # GLib error messages come from the service and do not contain the value.
            raise SecretError(strings.SECRET_SERVICE_ERROR.format(reason=exc.message)) from None

    def get(self, name: str) -> str | None:
        return self._call("password_lookup_sync", {SCHEMA_ATTRIBUTE: name}, None)

    def set(self, name: str, value: str) -> None:
        self.ensure_available()
        label = strings.SECRET_ITEM_LABEL.format(name=name)
        ok = self._call(
            "password_store_sync",
            {SCHEMA_ATTRIBUTE: name},
            self._secret.COLLECTION_DEFAULT,
            label,
            value,
            None,
        )
        if not ok:
            raise SecretError(strings.SECRET_SERVICE_ERROR.format(reason="store"))

    def delete(self, name: str) -> bool:
        return bool(self._call("password_clear_sync", {SCHEMA_ATTRIBUTE: name}, None))

    def has(self, name: str) -> bool:
        self.ensure_available()
        items = self._call(
            "password_search_sync", {SCHEMA_ATTRIBUTE: name}, self._secret.SearchFlags.ALL, None
        )
        return bool(items)


# -- resolving -----------------------------------------------------------------------------


async def resolve(
    source: ValueSource,
    *,
    store: SecretStore | None,
    prompt_cb: PromptCallback | None,
    name: str | None = None,
) -> str | None:
    """Value of ``source`` or ``None`` when it has none. ``name`` is the variable name (used
    for the default prompt label). Raises ``SecretError``."""
    match source:
        case Literal(value=value):
            return value
        case Env(name=var):
            return os.environ.get(var)
        case Keyring(name=key):
            if store is None:
                raise SecretServiceUnavailable(
                    strings.SECRET_NO_SERVICE.format(reason=strings.SECRET_NOT_RUNNING)
                )
            value = await asyncio.to_thread(store.get, key)
        case Command(cmd=cmd, timeout_s=timeout):
            value = await run_command(cmd, timeout)
        case Prompt(label=label):
            text = label or strings.SECRET_PROMPT_LABEL.format(name=name or "?")
            if prompt_cb is None:
                raise InteractionRequired(strings.SECRET_NEEDS_INTERACTION.format(label=text))
            value = await prompt_cb(text) or None  # empty answer counts as no value
        case _:
            raise TypeError(f"unknown value source {type(source).__name__}")
    register_secret(value)
    return value


async def run_command(cmd: str, timeout_s: float) -> str:
    """stdout of ``cmd`` (no shell) without trailing newlines. Raises ``SecretError``."""
    try:
        argv = shlex.split(cmd)
    except ValueError as exc:
        raise SecretError(strings.CFG_BAD_COMMAND_LINE.format(reason=exc)) from None
    if not argv:
        raise SecretError(strings.SECRET_CMD_EMPTY)
    program = argv[0]
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,  # own process group: a timeout kills the children too
        )
    except OSError as exc:
        reason = exc.strerror or type(exc).__name__
        raise SecretError(strings.SECRET_CMD_START.format(program=program, reason=reason)) from None

    try:
        async with asyncio.timeout(timeout_s):
            stdout = await _read_limited(proc, program)
            code = await proc.wait()
    except TimeoutError:
        await _kill(proc)
        raise SecretError(
            strings.SECRET_CMD_TIMEOUT.format(program=program, timeout=timeout_s)
        ) from None
    except BaseException:
        await _kill(proc)
        raise

    if code != 0:
        raise SecretError(strings.SECRET_CMD_FAILED.format(program=program, code=code))
    try:
        text = stdout.decode("utf-8")
    except UnicodeDecodeError:
        raise SecretError(strings.SECRET_CMD_NOT_UTF8.format(program=program)) from None
    return text.rstrip("\r\n")


async def _read_limited(proc: asyncio.subprocess.Process, program: str) -> bytes:
    if proc.stdout is None:  # cannot happen: stdout=PIPE
        raise RuntimeError("stdout is not a pipe")
    data = await proc.stdout.read(COMMAND_OUTPUT_LIMIT + 1)
    while len(data) <= COMMAND_OUTPUT_LIMIT:
        chunk = await proc.stdout.read(COMMAND_OUTPUT_LIMIT + 1 - len(data))
        if not chunk:
            return data
        data += chunk
    await _kill(proc)
    raise SecretError(
        strings.SECRET_CMD_TOO_LONG.format(program=program, limit=COMMAND_OUTPUT_LIMIT)
    )


async def _kill(proc: asyncio.subprocess.Process) -> None:
    # Signal the whole process group even when the leader has already exited: a background
    # child may still hold stdout. The group id stays reserved while any member is alive.
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(proc.pid, signal.SIGKILL)
    with contextlib.suppress(ProcessLookupError):
        await proc.wait()


class _HasEnv(Protocol):
    env: dict[str, ValueSource]


async def resolve_env(
    entry: _HasEnv,
    *,
    store: SecretStore | None,
    prompt_cb: PromptCallback | None,
) -> dict[str, str]:
    """Resolved ``env`` of an agent or MCP server. Variables without a value are left out.
    Raises ``SecretError`` naming the variable (never its value)."""
    result: dict[str, str] = {}
    for var, source in entry.env.items():
        try:
            value = await resolve(source, store=store, prompt_cb=prompt_cb, name=var)
        except SecretError as exc:
            raise type(exc)(strings.SECRET_VAR_ERROR.format(name=var, reason=exc)) from None
        if value is None:
            log.info("%s: no value from source %r, variable skipped", var, _source_kind(source))
            continue
        if isinstance(source, Env | Literal) and SECRET_NAME_RE.search(var):
            register_secret(value)
        result[var] = value
    return result


def _source_kind(source: ValueSource) -> str:
    return type(source).__name__.lower()
