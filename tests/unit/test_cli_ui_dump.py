"""``python -m app.cli ui-dump`` with the D-Bus call replaced."""

import json

from app import cli, debug


def test_prints_the_new_dump(isolated_env, monkeypatch, capsys) -> None:
    debug.write_dump({"screen": "old"})
    calls = []

    def activate(name: str) -> None:
        calls.append(name)
        debug.write_dump({"screen": "chat", "messages": []})

    monkeypatch.setattr(cli, "activate_app_action", activate)
    assert cli.main(["ui-dump"]) == 0
    assert calls == ["debug-dump"]
    assert json.loads(capsys.readouterr().out) == {"screen": "chat", "messages": []}


def test_old_dump_is_not_printed(isolated_env, monkeypatch, capsys) -> None:
    debug.write_dump({"screen": "old"})
    monkeypatch.setattr(cli, "activate_app_action", lambda name: None)
    parser = cli.build_parser()
    args = parser.parse_args(["ui-dump"])
    args.timeout = 0.2
    assert args.func(args) == 1
    out, err = capsys.readouterr()
    assert out == ""
    assert err.startswith("błąd: ") and "debug-dump.json" in err


def test_dbus_error_exits_1(isolated_env, monkeypatch, capsys) -> None:
    def activate(name: str) -> None:
        raise RuntimeError("The name is not activatable")

    monkeypatch.setattr(cli, "activate_app_action", activate)
    assert cli.main(["ui-dump"]) == 1
    err = capsys.readouterr().err
    assert "The name is not activatable" in err
    assert "AI_PANEL_DEBUG=1" in err
