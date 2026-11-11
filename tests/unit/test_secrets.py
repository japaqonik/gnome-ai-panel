"""Unit tests of app/secrets.py (value sources, resolve_env) and the log redaction filter."""

import asyncio
import logging
import subprocess
import sys
import time
from pathlib import Path

import pytest

from app import secrets
from app.config import AcpAgent, Command, Env, Keyring, Literal, Prompt
from app.logging_setup import REDACTED, REDACTOR, SecretRedactor
from app.secrets import (
    InteractionRequired,
    MemoryStore,
    SecretError,
    SecretServiceUnavailable,
    resolve,
    resolve_env,
)

SECRET = "s3cr3t-value-123"
REPO = Path(__file__).resolve().parent.parent.parent


@pytest.fixture(autouse=True)
def clean_redactor():
    REDACTOR.clear()
    yield
    REDACTOR.clear()


def agent(**env) -> AcpAgent:
    return AcpAgent(id="a", name="a", command="x", cwd="/tmp", env=env)  # noqa: S108


async def no_prompt(label: str) -> str | None:
    raise AssertionError(f"unexpected prompt {label}")


# -- each source ---------------------------------------------------------------------------


async def test_literal() -> None:
    assert await resolve(Literal("v"), store=None, prompt_cb=None) == "v"


async def test_env_set(monkeypatch) -> None:
    monkeypatch.setenv("AI_PANEL_TEST_VAR", "from-env")
    assert await resolve(Env("AI_PANEL_TEST_VAR"), store=None, prompt_cb=None) == "from-env"


async def test_env_missing_is_none(monkeypatch) -> None:
    monkeypatch.delenv("AI_PANEL_TEST_VAR", raising=False)
    assert await resolve(Env("AI_PANEL_TEST_VAR"), store=None, prompt_cb=None) is None


async def test_keyring_from_store() -> None:
    store = MemoryStore({"api": SECRET})
    assert await resolve(Keyring("api"), store=store, prompt_cb=None) == SECRET


async def test_keyring_missing_item_is_none() -> None:
    assert await resolve(Keyring("nope"), store=MemoryStore(), prompt_cb=None) is None


async def test_keyring_without_store_is_unavailable() -> None:
    with pytest.raises(SecretServiceUnavailable, match="brak usługi Secret Service"):
        await resolve(Keyring("api"), store=None, prompt_cb=None)


async def test_keyring_store_error_propagates() -> None:
    class Broken(MemoryStore):
        def get(self, name: str) -> str | None:
            raise SecretServiceUnavailable("brak usługi Secret Service (test)")

    with pytest.raises(SecretServiceUnavailable):
        await resolve(Keyring("api"), store=Broken(), prompt_cb=None)


async def test_command_printf() -> None:
    assert await resolve(Command("printf secret"), store=None, prompt_cb=None) == "secret"


async def test_command_trailing_newlines_trimmed() -> None:
    value = await resolve(Command(r"printf 'a b\n\n'"), store=None, prompt_cb=None)
    assert value == "a b"


async def test_command_inner_newline_kept() -> None:
    value = await resolve(Command(r"printf 'a\nb\n'"), store=None, prompt_cb=None)
    assert value == "a\nb"


async def test_command_runs_without_shell() -> None:
    value = await resolve(Command("printf '%s' '$HOME;echo x|cat'"), store=None, prompt_cb=None)
    assert value == "$HOME;echo x|cat"


async def test_command_false_is_error_without_value() -> None:
    with pytest.raises(SecretError) as info:
        await resolve(Command("false"), store=None, prompt_cb=None)
    assert "false" in str(info.value)
    assert "kodem 1" in str(info.value)


async def test_command_failure_does_not_show_stdout() -> None:
    cmd = f"sh -c 'printf {SECRET}; exit 4'"
    with pytest.raises(SecretError) as info:
        await resolve(Command(cmd), store=None, prompt_cb=None)
    assert "kodem 4" in str(info.value)
    assert SECRET not in str(info.value)
    assert SECRET not in repr(info.value)


async def test_command_timeout() -> None:
    start = time.monotonic()
    with pytest.raises(SecretError, match="0.5 s"):
        await resolve(Command("sleep 20", timeout_s=0.5), store=None, prompt_cb=None)
    assert time.monotonic() - start < 3


async def test_command_timeout_kills_children(tmp_path) -> None:
    marker = tmp_path / "late"
    cmd = f"sh -c 'sleep 1; touch {marker}'"
    with pytest.raises(SecretError):
        await resolve(Command(cmd, timeout_s=0.2), store=None, prompt_cb=None)
    await asyncio.sleep(1.5)
    assert not marker.exists()


async def test_command_not_found() -> None:
    with pytest.raises(SecretError, match="/nonexistent/tool"):
        await resolve(Command("/nonexistent/tool arg"), store=None, prompt_cb=None)


async def test_command_not_utf8() -> None:
    with pytest.raises(SecretError, match="UTF-8"):
        await resolve(Command(r"printf '\377'"), store=None, prompt_cb=None)


async def test_command_output_limit(monkeypatch) -> None:
    monkeypatch.setattr(secrets, "COMMAND_OUTPUT_LIMIT", 1000)
    with pytest.raises(SecretError, match="1000"):
        await resolve(Command("head -c 5000 /dev/zero"), store=None, prompt_cb=None)


async def test_command_empty() -> None:
    with pytest.raises(SecretError, match="puste"):
        await resolve(Command("  "), store=None, prompt_cb=None)


async def test_prompt_uses_callback_and_label() -> None:
    labels = []

    async def cb(label: str) -> str | None:
        labels.append(label)
        return "typed"

    assert await resolve(Prompt("Klucz"), store=None, prompt_cb=cb) == "typed"
    assert await resolve(Prompt(), store=None, prompt_cb=cb, name="TOKEN") == "typed"
    assert labels == ["Klucz", "Wartość zmiennej TOKEN"]


async def test_prompt_cancelled_is_none() -> None:
    async def cb(label: str) -> str | None:
        return None

    assert await resolve(Prompt("x"), store=None, prompt_cb=cb) is None


async def test_prompt_empty_answer_is_none() -> None:
    async def cb(label: str) -> str | None:
        return ""

    assert await resolve(Prompt("x"), store=None, prompt_cb=cb) is None
    assert await resolve_env(agent(TOKEN=Prompt()), store=None, prompt_cb=cb) == {}


async def test_prompt_without_callback_needs_interaction() -> None:
    with pytest.raises(InteractionRequired, match="wymaga interakcji"):
        await resolve(Prompt("Klucz"), store=None, prompt_cb=None)


# -- resolve_env ---------------------------------------------------------------------------


async def test_resolve_env_all_sources(monkeypatch) -> None:
    monkeypatch.setenv("AI_PANEL_TEST_VAR", "e")

    async def cb(label: str) -> str | None:
        return "p"

    entry = agent(
        A=Literal("l"),
        B=Env("AI_PANEL_TEST_VAR"),
        C=Keyring("k"),
        D=Command("printf c"),
        E=Prompt(),
    )
    env = await resolve_env(entry, store=MemoryStore({"k": "kv"}), prompt_cb=cb)
    assert env == {"A": "l", "B": "e", "C": "kv", "D": "c", "E": "p"}


async def test_resolve_env_skips_missing_optional(monkeypatch, caplog) -> None:
    monkeypatch.delenv("AI_PANEL_UNSET", raising=False)
    entry = agent(
        GONE=Env("AI_PANEL_UNSET"), NOKEY=Keyring("missing"), HERE=Keyring("k"), LIT=Literal("x")
    )
    with caplog.at_level(logging.INFO, logger="app"):
        env = await resolve_env(entry, store=MemoryStore({"k": SECRET}), prompt_cb=no_prompt)
    assert env == {"HERE": SECRET, "LIT": "x"}
    text = caplog.text
    assert "GONE" in text and "NOKEY" in text
    assert SECRET not in text
    assert all(r.levelno == logging.INFO for r in caplog.records)


async def test_resolve_env_error_names_variable_not_value() -> None:
    entry = agent(OK=Command(f"printf {SECRET}"), BAD=Command("false"))
    with pytest.raises(SecretError) as info:
        await resolve_env(entry, store=None, prompt_cb=None)
    assert "BAD" in str(info.value)
    assert SECRET not in str(info.value)


async def test_resolve_env_keeps_error_type() -> None:
    with pytest.raises(InteractionRequired, match="ASK"):
        await resolve_env(agent(ASK=Prompt()), store=None, prompt_cb=None)
    with pytest.raises(SecretServiceUnavailable, match="KEY"):
        await resolve_env(agent(KEY=Keyring("x")), store=None, prompt_cb=None)


async def test_resolve_env_empty() -> None:
    assert await resolve_env(agent(), store=None, prompt_cb=None) == {}


# -- redaction -----------------------------------------------------------------------------


@pytest.fixture
def captured_log():
    """A handler on the ``app`` logger with the redaction filter, as in setup_logging()."""
    records: list[str] = []

    class ListHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(self.format(record))

    handler = ListHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    handler.addFilter(REDACTOR)
    logger = logging.getLogger("app")
    old_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    yield records
    logger.removeHandler(handler)
    logger.setLevel(old_level)


async def test_resolved_secret_is_redacted_in_log(captured_log) -> None:
    value = await resolve(Command(f"printf {SECRET}"), store=None, prompt_cb=None)
    assert value == SECRET
    child = logging.getLogger("app.backends.test")
    child.debug("env sent: %s", {"TOKEN": value})
    child.info(f"inline {value} and again {value}")
    try:
        raise RuntimeError(f"boom {value}")
    except RuntimeError:
        child.exception("failed")
    joined = "\n".join(captured_log)
    assert SECRET not in joined
    assert joined.count(REDACTED) == 4


async def test_keyring_and_prompt_values_registered(captured_log) -> None:
    async def cb(label: str) -> str | None:
        return "typed-secret"

    await resolve(Keyring("k"), store=MemoryStore({"k": "keyring-secret"}), prompt_cb=None)
    await resolve(Prompt(), store=None, prompt_cb=cb)
    logging.getLogger("app").warning("keyring-secret typed-secret")
    assert captured_log == [f"WARNING app: {REDACTED} {REDACTED}"]


async def test_env_and_literal_registered_only_for_secret_names(monkeypatch, captured_log) -> None:
    monkeypatch.setenv("AI_PANEL_TEST_VAR", "env-secret-value")
    entry = agent(
        API_KEY=Env("AI_PANEL_TEST_VAR"), my_password=Literal("literal-pass"), MODE=Literal("plain")
    )
    await resolve_env(entry, store=None, prompt_cb=None)
    logging.getLogger("app").info("env-secret-value literal-pass plain")
    assert captured_log == [f"INFO app: {REDACTED} {REDACTED} plain"]


def test_redactor_ignores_short_values() -> None:
    redactor = SecretRedactor()
    redactor.register("ab")
    redactor.register("")
    redactor.register(None)
    assert redactor.redact("ab cd") == "ab cd"


def test_redactor_longest_first() -> None:
    redactor = SecretRedactor()
    redactor.register("abcd")
    redactor.register("abcdefgh")
    assert redactor.redact("x abcdefgh y abcd") == f"x {REDACTED} y {REDACTED}"


def test_redactor_bad_format_args_do_not_raise() -> None:
    redactor = SecretRedactor()
    redactor.register("hidden-value")
    record = logging.LogRecord("app", logging.INFO, __file__, 1, "%s %s hidden-value", ("x",), None)
    assert redactor.filter(record) is True
    assert "hidden-value" not in record.getMessage()


def test_setup_logging_installs_redactor(isolated_env, capsys) -> None:
    from app.logging_setup import log_path, setup_logging

    setup_logging()
    try:
        REDACTOR.register(SECRET)
        logging.getLogger("app.test").warning("value=%s", SECRET)
        for handler in logging.getLogger("app").handlers:
            handler.flush()
        assert SECRET not in capsys.readouterr().err
        content = log_path().read_text(encoding="utf-8")
        assert "value=" + REDACTED in content
        assert SECRET not in content
    finally:
        logger = logging.getLogger("app")
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()
        logger.propagate = True
        logger.setLevel(logging.NOTSET)


def test_import_does_not_load_gi() -> None:
    probe = subprocess.run(
        [sys.executable, "-c", "import sys, app.secrets; print('gi' in sys.modules)"],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    assert probe.stdout.strip() == "False"
