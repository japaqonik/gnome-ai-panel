"""Unit tests of the ``secret`` CLI commands and the terminal prompt (no real keyring)."""

import io

import pytest

from app import cli
from app.cli import main
from app.secrets import InteractionRequired, MemoryStore, SecretServiceUnavailable


class NoService(MemoryStore):
    def ensure_available(self) -> None:
        raise SecretServiceUnavailable("brak usługi Secret Service (keyring): test")


@pytest.fixture
def store(monkeypatch) -> MemoryStore:
    store = MemoryStore()
    monkeypatch.setattr(cli, "make_store", lambda: store)
    return store


def feed_stdin(monkeypatch, data: bytes) -> None:
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(data), encoding="utf-8"))


def run(argv, capsys) -> tuple[int, str, str]:
    code = main(argv)
    out, err = capsys.readouterr()
    return code, out, err


def test_set_has_delete(store, monkeypatch, capsys) -> None:
    feed_stdin(monkeypatch, b"abc\n")
    code, out, _ = run(["secret", "set", "test-x"], capsys)
    assert code == 0
    assert "test-x" in out
    assert "abc" not in out
    assert store.items == {"test-x": "abc"}

    assert run(["secret", "has", "test-x"], capsys)[0] == 0
    assert run(["secret", "delete", "test-x"], capsys)[0] == 0
    assert store.items == {}
    code, out, _ = run(["secret", "has", "test-x"], capsys)
    assert code == 1
    assert "Brak sekretu" in out
    assert run(["secret", "delete", "test-x"], capsys)[0] == 1


def test_set_keeps_inner_whitespace(store, monkeypatch, capsys) -> None:
    feed_stdin(monkeypatch, b" a b \r\n")
    assert run(["secret", "set", "n"], capsys)[0] == 0
    assert store.items["n"] == " a b "


def test_set_overwrites(store, monkeypatch, capsys) -> None:
    store.items["n"] = "old"
    feed_stdin(monkeypatch, b"new")
    assert run(["secret", "set", "n"], capsys)[0] == 0
    assert store.items["n"] == "new"


@pytest.mark.parametrize("data", [b"", b"\n", b"\r\n\n"])
def test_set_empty_value_fails(store, monkeypatch, capsys, data) -> None:
    feed_stdin(monkeypatch, data)
    code, _, err = run(["secret", "set", "n"], capsys)
    assert code == 1
    assert "pusta wartość" in err
    assert store.items == {}


def test_set_value_too_long(store, monkeypatch, capsys) -> None:
    feed_stdin(monkeypatch, b"x" * (cli.SECRET_VALUE_LIMIT + 1))
    code, _, err = run(["secret", "set", "n"], capsys)
    assert code == 1
    assert str(cli.SECRET_VALUE_LIMIT) in err
    assert store.items == {}


def test_set_not_utf8(store, monkeypatch, capsys) -> None:
    feed_stdin(monkeypatch, b"\xff\xfe")
    code, _, err = run(["secret", "set", "n"], capsys)
    assert code == 1
    assert "UTF-8" in err


@pytest.mark.parametrize("name", ["", "   ", "a\nb", "trailing\n", "x" * 257, "tab\there"])
def test_bad_name(store, capsys, name) -> None:
    code, _, err = run(["secret", "has", name], capsys)
    assert code == 1
    assert "nieprawidłowa nazwa" in err


@pytest.mark.parametrize("command", ["set", "delete", "has"])
def test_no_service(monkeypatch, capsys, command) -> None:
    monkeypatch.setattr(cli, "make_store", NoService)
    feed_stdin(monkeypatch, b"abc")
    code, out, err = run(["secret", command, "test-x"], capsys)
    assert code == 1
    assert "brak usługi Secret Service" in err
    assert "Traceback" not in err
    assert "abc" not in out + err


def test_secret_requires_subcommand(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["secret"])
    assert exc.value.code == 2


async def test_terminal_prompt_without_tty(monkeypatch) -> None:
    feed_stdin(monkeypatch, b"")
    with pytest.raises(InteractionRequired, match="wymaga interakcji"):
        await cli.terminal_prompt("Klucz API")


async def test_terminal_prompt_with_tty(monkeypatch) -> None:
    class Tty(io.StringIO):
        def isatty(self) -> bool:
            return True

    prompts = []
    monkeypatch.setattr("sys.stdin", Tty())
    monkeypatch.setattr(cli.getpass, "getpass", lambda p: prompts.append(p) or "typed")
    assert await cli.terminal_prompt("Klucz API") == "typed"
    assert prompts == ["Klucz API: "]
    monkeypatch.setattr(cli.getpass, "getpass", lambda p: "")
    assert await cli.terminal_prompt("Klucz API") is None


@pytest.mark.parametrize("name", ["ok-name", "with space", "zażółć", "x" * 256])
def test_good_names_accepted(store, monkeypatch, capsys, name) -> None:
    """Boundary of the name check: 256 characters and non-ASCII names are fine."""
    feed_stdin(monkeypatch, b"value-1234")
    code, _, err = run(["secret", "set", name], capsys)
    assert code == 0, err
    code, _, _ = run(["secret", "has", name], capsys)
    assert code == 0
