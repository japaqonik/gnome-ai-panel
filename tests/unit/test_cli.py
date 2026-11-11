"""Unit tests of app/cli.py: check-config and agents (in process, plus one subprocess run)."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.cli import main

DATA = Path(__file__).resolve().parent.parent / "data"
REPO = Path(__file__).resolve().parent.parent.parent


def run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    code = main(argv)
    out, err = capsys.readouterr()
    return code, out, err


def private_copy(tmp_path: Path, name: str) -> Path:
    path = tmp_path / name
    path.write_bytes((DATA / name).read_bytes())
    path.chmod(0o600)
    return path


def test_check_config_valid(isolated_env, tmp_path, capsys) -> None:
    path = private_copy(tmp_path, "config_valid.toml")
    code, out, _ = run(["check-config", "--config", str(path)], capsys)
    assert code == 0
    assert "Konfiguracja poprawna" in out
    assert "agenci: 2" in out and "serwery MCP: 1" in out


def test_check_config_invalid(isolated_env, tmp_path, capsys) -> None:
    path = private_copy(tmp_path, "config_invalid.toml")
    code, out, _ = run(["check-config", "--config", str(path)], capsys)
    assert code == 1
    lines = out.splitlines()
    assert any(line.startswith("agents.broken.command: ") for line in lines)
    assert any(line.startswith("agents.broken.mcp[0]: ") for line in lines)
    assert not any(line.startswith("agents.good") for line in lines)


def test_check_config_missing_file_ok(isolated_env, tmp_path, capsys) -> None:
    code, out, _ = run(["check-config", "--config", str(tmp_path / "none.toml")], capsys)
    assert code == 0
    assert "pusta konfiguracja" in out


def test_check_config_uses_env(isolated_env, tmp_path, monkeypatch, capsys) -> None:
    path = private_copy(tmp_path, "config_invalid.toml")
    monkeypatch.setenv("AI_PANEL_CONFIG", str(path))
    code, out, _ = run(["check-config"], capsys)
    assert code == 1
    assert str(path) in out


def test_check_config_syntax_error_has_file_and_line(isolated_env, tmp_path, capsys) -> None:
    path = tmp_path / "c.toml"
    path.write_text("a = 1\nb = \n", encoding="utf-8")
    path.chmod(0o600)
    code, out, _ = run(["check-config", "--config", str(path)], capsys)
    assert code == 1
    assert out.splitlines()[0].startswith(f"{path}:2: błąd składni TOML")


def test_check_config_warnings_do_not_fail(isolated_env, tmp_path, capsys) -> None:
    path = tmp_path / "c.toml"
    path.write_text(
        '[agents.a]\ntype = "acp"\ncommand = "/x"\ncwd = "/x"\n'
        'env = { API_KEY = { source = "literal", value = "v" } }\n',
        encoding="utf-8",
    )
    path.chmod(0o666)
    code, out, _ = run(["check-config", "--config", str(path)], capsys)
    assert code == 0
    warnings = [line for line in out.splitlines() if line.startswith("ostrzeżenie: ")]
    assert len(warnings) == 2
    assert any("agents.a.env.API_KEY: " in line for line in warnings)
    assert "\nv\n" not in out and " v " not in out


def test_agents_json_missing_config(isolated_env, monkeypatch, capsys) -> None:
    monkeypatch.setenv("AI_PANEL_CONFIG", "/nonexistent")
    code, out, err = run(["agents", "--json"], capsys)
    assert code == 0
    assert json.loads(out) == []
    assert err == ""


def test_agents_json_skips_invalid(isolated_env, tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("AI_PANEL_CONFIG", str(private_copy(tmp_path, "config_invalid.toml")))
    code, out, err = run(["agents", "--json"], capsys)
    assert code == 0
    assert json.loads(out) == [
        {"id": "good", "type": "acp", "name": "good", "valid": True, "default": True}
    ]
    assert "broken" not in out
    assert "broken" in err


def test_agents_text(isolated_env, tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("AI_PANEL_CONFIG", str(private_copy(tmp_path, "config_valid.toml")))
    code, out, _ = run(["agents"], capsys)
    assert code == 0
    assert out.splitlines() == [
        "moj-agent\tacp\tmoj-agent (domyślny)",
        "szybki-czat\tapi\tszybki-czat",
    ]


def test_agents_text_empty(isolated_env, capsys) -> None:
    code, out, _ = run(["agents"], capsys)
    assert code == 0
    assert out.strip() == "Brak skonfigurowanych agentów."


def test_no_command_is_usage_error(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2


def test_module_entry_point(isolated_env) -> None:
    """``python -m app.cli`` runs without GTK and returns the command's exit code."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.cli",
            "check-config",
            "--config",
            "tests/data/config_invalid.toml",
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 1
    assert any(line.startswith("agents.broken.command:") for line in result.stdout.splitlines())
    probe = subprocess.run(
        [sys.executable, "-c", "import sys, app.cli; print('gi' in sys.modules)"],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    assert probe.stdout.strip() == "False"
