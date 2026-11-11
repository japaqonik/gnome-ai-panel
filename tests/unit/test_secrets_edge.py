"""Extra edge cases of app/secrets.py and the log redaction filter (added by the tester)."""

import asyncio
import logging
import os
import time
from pathlib import Path

import pytest
from gi.events import GLibEventLoopPolicy

from app.config import AcpAgent, Command, Env, Keyring, Literal, Prompt
from app.logging_setup import REDACTED, REDACTOR, SecretRedactor
from app.secrets import (
    InteractionRequired,
    MemoryStore,
    SecretError,
    SecretServiceUnavailable,
    resolve,
    resolve_env,
    run_command,
)

SECRET = "edge-s3cr3t-987"


@pytest.fixture(autouse=True)
def clean_redactor():
    REDACTOR.clear()
    yield
    REDACTOR.clear()


def agent(**env) -> AcpAgent:
    return AcpAgent(id="a", name="a", command="x", cwd="/tmp", env=env)  # noqa: S108


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # A zombie still answers kill(0); treat it as dead.
    try:
        state = Path(f"/proc/{pid}/stat").read_text().split(")")[-1].split()[0]
    except OSError:
        return False
    return state != "Z"


# -- command ---------------------------------------------------------------------------------


async def test_timeout_when_parent_exits_but_child_keeps_stdout(tmp_path) -> None:
    """The parent exits at once, a background child holds stdout open: the timeout must
    still fire and the child must not survive."""
    pidfile = tmp_path / "pid"
    cmd = f"sh -c 'sleep 30 & echo $! > {pidfile}; exit 0'"
    start = time.monotonic()
    with pytest.raises(SecretError):
        await resolve(Command(cmd, timeout_s=0.5), store=None, prompt_cb=None)
    assert time.monotonic() - start < 3
    pid = int(pidfile.read_text())
    await asyncio.sleep(0.3)
    alive = _alive(pid)
    if alive:
        os.kill(pid, 9)
    assert not alive, "background child of a timed-out command was left running"


async def test_unbalanced_quote_is_error_without_command_text() -> None:
    with pytest.raises(SecretError) as info:
        await run_command(f"printf '{SECRET}", 5)
    assert SECRET not in str(info.value)


async def test_nonzero_exit_code_in_message() -> None:
    with pytest.raises(SecretError) as info:
        await run_command("sh -c 'exit 7'", 5)
    assert "7" in str(info.value)
    assert "sh" in str(info.value)


async def test_stdout_crlf_and_only_trailing_trimmed() -> None:
    assert await run_command(r"printf '  a b \r\n\n'", 5) == "  a b "


async def test_command_output_exactly_at_limit(monkeypatch) -> None:
    import app.secrets as s

    monkeypatch.setattr(s, "COMMAND_OUTPUT_LIMIT", 8)
    assert await run_command("printf 12345678", 5) == "12345678"
    with pytest.raises(SecretError):
        await run_command("printf 123456789", 5)


def test_command_on_glib_event_loop() -> None:
    """The app runs asyncio on the GLib loop; command sources must work there too."""

    async def job() -> tuple[str, float]:
        value = await run_command("printf glib-ok", 5)
        start = time.monotonic()
        with pytest.raises(SecretError):
            await run_command("sleep 20", 0.5)
        return value, time.monotonic() - start

    with GLibEventLoopPolicy() as policy:
        loop = policy.new_event_loop()
        try:
            value, elapsed = loop.run_until_complete(asyncio.wait_for(job(), 20))
        finally:
            loop.close()
    assert value == "glib-ok"
    assert elapsed < 3


# -- keyring / prompt ------------------------------------------------------------------------


async def test_keyring_unavailable_store_error_propagates_from_resolve_env() -> None:
    class Down(MemoryStore):
        def get(self, name: str) -> str | None:
            raise SecretServiceUnavailable("brak usługi Secret Service (keyring): test")

    with pytest.raises(SecretServiceUnavailable) as info:
        await resolve_env(agent(API_KEY=Keyring("k")), store=Down(), prompt_cb=None)
    assert "API_KEY" in str(info.value)


async def test_prompt_without_callback_in_resolve_env_names_variable() -> None:
    with pytest.raises(InteractionRequired) as info:
        await resolve_env(agent(TOKEN=Prompt(None)), store=None, prompt_cb=None)
    assert "TOKEN" in str(info.value)
    assert "wymaga interakcji" in str(info.value)


async def test_resolve_env_order_and_partial(monkeypatch) -> None:
    monkeypatch.delenv("AI_PANEL_EDGE_UNSET", raising=False)
    store = MemoryStore({"k": SECRET})
    env = await resolve_env(
        agent(
            A=Literal("1"),
            B=Env("AI_PANEL_EDGE_UNSET"),
            C=Keyring("k"),
            D=Keyring("missing"),
            E=Command("printf e", timeout_s=5),
        ),
        store=store,
        prompt_cb=None,
    )
    assert env == {"A": "1", "C": SECRET, "E": "e"}


# -- redaction -------------------------------------------------------------------------------


def _capture(redactor: SecretRedactor) -> tuple[logging.Logger, list[str]]:
    lines: list[str] = []

    class ListHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            lines.append(self.format(record))

    handler = ListHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler.addFilter(redactor)
    logger = logging.getLogger("app.test_edge_redaction")
    logger.handlers[:] = [handler]
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    return logger, lines


async def test_redaction_in_dict_args_and_exception() -> None:
    value = await resolve(Command(f"printf {SECRET}", timeout_s=5), store=None, prompt_cb=None)
    assert value == SECRET
    logger, lines = _capture(REDACTOR)
    logger.info("env %s", {"API_KEY": SECRET})
    try:
        raise RuntimeError(f"bad {SECRET}")
    except RuntimeError:
        logger.exception("failed")
    text = "\n".join(lines)
    assert SECRET not in text
    assert REDACTED in text


def test_redaction_same_record_through_two_handlers() -> None:
    """The filter mutates the record; a second handler must still get a sane message."""
    redactor = SecretRedactor()
    redactor.register(SECRET)
    logger, lines = _capture(redactor)
    second: list[str] = []

    class H(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            second.append(self.format(record))

    h = H()
    h.setFormatter(logging.Formatter("%(message)s"))
    h.addFilter(redactor)
    logger.addHandler(h)
    logger.warning("v=%s n=%d", SECRET, 5)
    assert lines == [f"v={REDACTED} n=5"]
    assert second == [f"v={REDACTED} n=5"]


def test_redactor_boundary_length() -> None:
    r = SecretRedactor()
    r.register("abc")
    r.register("abcd")
    assert r.redact("xx abcd abc") == f"xx {REDACTED} abc"


# -- process group cleanup on the other error paths (attempt 2) -------------------------------


async def _wait_for_pidfile(pidfile: Path, timeout: float = 3.0) -> int:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        text = pidfile.read_text().strip() if pidfile.exists() else ""
        if text:
            return int(text)
        await asyncio.sleep(0.02)
    raise AssertionError("command did not write its pid file")


def _assert_dead(pid: int, what: str) -> None:
    alive = _alive(pid)
    if alive:
        os.kill(pid, 9)
    assert not alive, what


async def test_output_overflow_kills_background_child(tmp_path, monkeypatch) -> None:
    """Too much output: the error path must kill the whole group, not just the leader."""
    from app import secrets

    monkeypatch.setattr(secrets, "COMMAND_OUTPUT_LIMIT", 1000)
    pidfile = tmp_path / "pid"
    cmd = f"sh -c 'sleep 30 & echo $! > {pidfile}; head -c 5000 /dev/zero; wait'"
    with pytest.raises(SecretError, match="1000"):
        await resolve(Command(cmd, timeout_s=5), store=None, prompt_cb=None)
    pid = await _wait_for_pidfile(pidfile)
    await asyncio.sleep(0.3)
    _assert_dead(pid, "background child survived the output-limit error")


async def test_cancellation_kills_process_group(tmp_path) -> None:
    """Cancelling the resolving task (e.g. the user closes the chat) must not leak processes."""
    pidfile = tmp_path / "pid"
    cmd = f"sh -c 'sleep 30 & echo $! > {pidfile}; wait'"
    task = asyncio.ensure_future(run_command(cmd, 10))
    pid = await _wait_for_pidfile(pidfile)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0.3)
    _assert_dead(pid, "background child survived cancellation")


async def test_timeout_error_does_not_contain_output(tmp_path) -> None:
    """Partial output written before the timeout must not leak into the error."""
    cmd = f"sh -c 'printf {SECRET}; sleep 30'"
    with pytest.raises(SecretError) as info:
        await resolve(Command(cmd, timeout_s=0.5), store=None, prompt_cb=None)
    assert SECRET not in str(info.value)
    assert "sh" in str(info.value)


async def test_prompt_value_is_redacted_after_resolve() -> None:
    async def answer(_label: str) -> str:
        return SECRET

    handler_records: list[str] = []

    class Collect(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            handler_records.append(record.getMessage())

    handler = Collect()
    handler.addFilter(REDACTOR)
    logger = logging.getLogger("app.test_edge_prompt")
    logger.addHandler(handler)
    try:
        value = await resolve(Prompt(label="Key"), store=None, prompt_cb=answer)
        assert value == SECRET
        logger.warning("got %s", value)
    finally:
        logger.removeHandler(handler)
    assert handler_records == [f"got {REDACTED}"]
