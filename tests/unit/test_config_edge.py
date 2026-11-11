"""Extra edge cases for app/config.py and app/cli.py (added by the tester, S2-T1)."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.cli import main
from app.config import AcpAgent, Literal, load_config

REPO = Path(__file__).resolve().parent.parent.parent
DATA = REPO / "tests" / "data"

SECRET = "sk-very-secret-0123456789"  # noqa: S105 (test fixture, not a real secret)


@pytest.fixture
def write(tmp_path: Path, isolated_env):
    def _write(text: str, name: str = "config.toml") -> Path:
        path = tmp_path / name
        path.write_text(text, encoding="utf-8")
        path.chmod(0o600)
        return path

    return _write


def acp(extra: str = "", agent_id: str = "a") -> str:
    return (
        f'[agents.{agent_id}]\ntype = "acp"\ncommand = "/usr/bin/true"\ncwd = "/tmp/x"\n{extra}\n'
    )


@pytest.mark.parametrize("value", ["nan", "inf", "-inf", "0", "-1", "600.5", "true"])
def test_startup_timeout_rejects_special_and_out_of_range(write, value) -> None:
    cfg = load_config(write(acp(f"startup_timeout_s = {value}")))
    assert [e.path for e in cfg.errors] == ["agents.a.startup_timeout_s"]
    assert cfg.agents == {}
    assert cfg.skipped_agents == ["a"]


@pytest.mark.parametrize("value", ["600", "0.001", "1"])
def test_startup_timeout_boundaries_accepted(write, value) -> None:
    cfg = load_config(write(acp(f"startup_timeout_s = {value}")))
    assert cfg.errors == []
    assert cfg.agents["a"].startup_timeout_s == float(value)


@pytest.mark.parametrize("size,ok", [(5, False), (6, True), (72, True), (73, False)])
def test_font_size_boundaries(write, size, ok) -> None:
    cfg = load_config(write(f"[chat]\nfont_size = {size}\n"))
    assert (cfg.errors == []) is ok
    assert cfg.chat.font_size == (size if ok else 14)


def test_font_size_float_rejected(write) -> None:
    cfg = load_config(write("[chat]\nfont_size = 14.5\n"))
    assert [e.path for e in cfg.errors] == ["chat.font_size"]
    assert cfg.chat.font_size == 14


def test_config_path_is_directory_is_error_not_crash(tmp_path, isolated_env, capsys) -> None:
    cfg = load_config(tmp_path)
    assert len(cfg.errors) == 1 and cfg.errors[0].path == ""
    assert main(["check-config", "--config", str(tmp_path)]) == 1


def test_literal_secret_value_never_printed(write, capsys) -> None:
    """Neither check-config nor agents print a literal value, even with errors around it."""
    path = write(
        acp(
            f'[agents.a.env]\nMY_TOKEN = {{ source = "literal", value = "{SECRET}", x = 1 }}\n'
            f'BAD = {{ source = "literal", value = "{SECRET}" , extra = "{SECRET}x" }}\n'
        )
        + f'[agents.b]\ntype = "api"\nendpoint = "ftp://x"\nmodel = "m"\n'
        f'api_key = {{ source = "literal", value = "{SECRET}" }}\n'
    )
    assert main(["check-config", "--config", str(path)]) == 1
    out, err = capsys.readouterr()
    assert SECRET not in out + err
    os.environ["AI_PANEL_CONFIG"] = str(path)
    try:
        main(["agents", "--json"])
        main(["agents"])
    finally:
        del os.environ["AI_PANEL_CONFIG"]
    out, err = capsys.readouterr()
    assert SECRET not in out + err
    cfg = load_config(path)
    assert SECRET not in repr(cfg)


def test_literal_warning_in_mcp_env(write) -> None:
    cfg = load_config(
        write(
            '[mcp.m]\ncommand = "x"\n[mcp.m.env]\nGH_TOKEN = { source = "literal", value = "v" }\n'
        )
    )
    assert cfg.errors == []
    assert [w.path for w in cfg.warnings] == ["mcp.m.env.GH_TOKEN"]
    assert isinstance(cfg.mcp["m"].env["GH_TOKEN"], Literal)


@pytest.mark.parametrize("name", ["password", "Db_Password", "SECRET_X", "akey"])
def test_literal_warning_case_insensitive(write, name) -> None:
    cfg = load_config(write(acp(f'[agents.a.env]\n{name} = {{ source = "literal", value = "v" }}')))
    assert cfg.errors == []
    assert len(cfg.warnings) == 1


def test_one_bad_agent_does_not_affect_others_in_cli(write, monkeypatch, capsys) -> None:
    path = write(acp(agent_id="good") + '[agents.bad]\ntype = "acp"\ncwd = "/x"\n')
    monkeypatch.setenv("AI_PANEL_CONFIG", str(path))
    assert main(["agents", "--json"]) == 0
    out, err = capsys.readouterr()
    assert [a["id"] for a in json.loads(out)] == ["good"]
    assert "bad" in err


def test_default_agent_whitespace_is_treated_as_empty(write) -> None:
    cfg = load_config(write('default_agent = "  "\n' + acp()))
    assert cfg.errors == []
    assert cfg.default_agent is None


def test_default_agent_marked_in_json(write, monkeypatch, capsys) -> None:
    path = write('default_agent = "a"\n' + acp() + acp(agent_id="b"))
    monkeypatch.setenv("AI_PANEL_CONFIG", str(path))
    main(["agents", "--json"])
    items = json.loads(capsys.readouterr().out)
    assert {i["id"]: i["default"] for i in items} == {"a": True, "b": False}


def test_relative_cwd_and_args_against_config_dir(tmp_path, isolated_env) -> None:
    sub = tmp_path / "conf"
    sub.mkdir()
    path = sub / "c.toml"
    path.write_text(
        '[agents.a]\ntype = "acp"\ncommand = "./bin/agent"\ncwd = "work"\n'
        'args = ["../script.py", "plain", "--flag=./x"]\n',
        encoding="utf-8",
    )
    path.chmod(0o600)
    # Load from a different working directory: resolution must not depend on cwd.
    old = os.getcwd()
    os.chdir("/")
    try:
        cfg = load_config(path)
    finally:
        os.chdir(old)
    agent = cfg.agents["a"]
    assert isinstance(agent, AcpAgent)
    assert agent.command == str(sub / "bin" / "agent")
    assert agent.cwd == sub / "work"
    assert agent.args == [str(tmp_path / "script.py"), "plain", "--flag=./x"]


def test_relative_ai_panel_config_resolves_against_cwd(tmp_path, isolated_env, monkeypatch) -> None:
    (tmp_path / "rel.toml").write_text(acp(), encoding="utf-8")
    (tmp_path / "rel.toml").chmod(0o600)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AI_PANEL_CONFIG", "rel.toml")
    cfg = load_config()
    assert cfg.path == tmp_path / "rel.toml"
    assert "a" in cfg.agents


def test_loader_never_creates_file_or_dirs(isolated_env, tmp_path) -> None:
    target = tmp_path / "nope" / "deeper" / "config.toml"
    cfg = load_config(target)
    assert cfg.errors == [] and not cfg.exists
    assert not (tmp_path / "nope").exists()


def test_xdg_default_location_untouched_when_missing(isolated_env) -> None:
    cfg = load_config()
    assert not cfg.path.exists()
    assert not cfg.path.parent.exists()


def test_syntax_error_line_matches_file_line(write) -> None:
    cfg = load_config(write("a = 1\nb = 2\n[chat\nfont_size = 3\n"))
    assert len(cfg.errors) == 1
    assert cfg.errors[0].line == 3


def test_cli_syntax_error_output_format(write, capsys) -> None:
    path = write('x = "unterminated\n')
    assert main(["check-config", "--config", str(path)]) == 1
    first = capsys.readouterr().out.splitlines()[0]
    assert first.startswith(f"{path}:1: ")


@pytest.mark.parametrize(
    "args,expected_code",
    [
        (["check-config", "--config", "tests/data/config_valid.toml"], 0),
        (["check-config", "--config", "tests/data/config_invalid.toml"], 1),
    ],
)
def test_make_cli_done_when(isolated_env, args, expected_code) -> None:
    """Done-when through ``make cli``: make reports CLI failure as exit 2 (GNU make)."""
    result = subprocess.run(
        ["make", "-s", "cli", "ARGS=" + " ".join(args)],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == (0 if expected_code == 0 else 2)
    if expected_code:
        assert any(line.startswith("agents.broken.command:") for line in result.stdout.splitlines())


def test_make_cli_agents_json_nonexistent(isolated_env) -> None:
    env = dict(os.environ, AI_PANEL_CONFIG="/nonexistent")
    result = subprocess.run(
        ["make", "-s", "cli", "ARGS=agents --json"],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0
    assert json.loads(result.stdout) == []


def test_check_config_runs_without_gtk(isolated_env) -> None:
    code = (
        "import sys, app.cli\n"
        "sys.argv=['x','check-config','--config',sys.argv[1]]\n"
        "rc = app.cli.main(sys.argv[1:])\n"
        "assert 'gi.repository.Gtk' not in sys.modules\n"
        "raise SystemExit(rc)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code, str(DATA / "config_valid.toml")],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
