"""Unit tests of app/config.py: parsing, path expansion and validation of config.toml."""

from pathlib import Path

import pytest

from app.config import (
    AcpAgent,
    ApiAgent,
    Command,
    ConfigError,
    Env,
    Keyring,
    Literal,
    Prompt,
    config_path,
    load_config,
)

DATA = Path(__file__).resolve().parent.parent / "data"

GOOD_ACP = """
[agents.ok]
type = "acp"
command = "/usr/bin/true"
cwd = "/srv/ai-panel-cwd"
"""


@pytest.fixture
def write(tmp_path: Path, isolated_env):
    """Write ``text`` to a 0600 config file in tmp_path and return its path."""

    def _write(text: str, name: str = "config.toml") -> Path:
        path = tmp_path / name
        path.write_text(text, encoding="utf-8")
        path.chmod(0o600)
        return path

    return _write


def paths(issues: list[ConfigError]) -> list[str]:
    return [issue.path for issue in issues]


# -- example, missing, empty, syntax ------------------------------------------------------


def test_spec_example_parses(isolated_env, tmp_path: Path) -> None:
    src = DATA / "config_valid.toml"
    path = tmp_path / "config.toml"
    path.write_bytes(src.read_bytes())
    path.chmod(0o600)

    cfg = load_config(path)

    assert cfg.errors == []
    assert cfg.warnings == []
    assert cfg.exists
    assert list(cfg.agents) == ["moj-agent", "szybki-czat"]
    assert list(cfg.mcp) == ["gnome"]
    assert cfg.default_agent == "moj-agent"

    acp = cfg.agents["moj-agent"]
    assert isinstance(acp, AcpAgent)
    assert acp.type == "acp"
    assert acp.name == "moj-agent"
    assert acp.command == "/ścieżka/do/agenta"
    assert acp.args == ["acp"]
    assert acp.cwd == isolated_env["HOME"] / ".cache" / "ai-panel"
    assert acp.startup_timeout_s == 20.0
    assert acp.mcp == []
    assert acp.env == {
        "SOME_API_KEY": Keyring("moj-agent-key"),
        "SOME_OTHER": Env("ZMIENNA_Z_SYSTEMU"),
        "FROM_TOOL": Command("pass show ai/klucz", 10.0),
        "ASK_ME": Prompt(None),
        "PLAIN_VALUE": Literal("tekst"),
    }
    assert acp.session_meta is None
    assert acp.system_prompt is None

    api = cfg.agents["szybki-czat"]
    assert isinstance(api, ApiAgent)
    assert api.type == "api"
    assert api.endpoint == "https://adres/api"
    assert api.model == "nazwa-modelu"
    assert api.models == ["nazwa-modelu"]
    assert api.system_prompt == "Odpowiadaj zwięźle i po polsku."
    assert api.api_key == Keyring("szybki-czat-key")
    assert api.max_tokens == 4096
    assert api.anthropic_version == "2023-06-01"

    gnome = cfg.mcp["gnome"]
    assert gnome.command == "gnome-ai-panel-mcp"
    assert gnome.args == []
    assert gnome.env == {}

    assert cfg.chat.font_size == 14
    assert cfg.chat.theme == "system"
    assert cfg.chat.history_dir == isolated_env["HOME"] / ".local" / "share" / "gnome-ai-panel"


def test_missing_file_is_empty_valid_config(isolated_env, tmp_path: Path) -> None:
    path = tmp_path / "nope" / "config.toml"
    cfg = load_config(path)
    assert not cfg.exists
    assert cfg.errors == [] and cfg.warnings == []
    assert cfg.agents == {} and cfg.mcp == {}
    assert cfg.default_agent is None
    assert cfg.chat.history_dir == isolated_env["XDG_DATA_HOME"] / "gnome-ai-panel"
    assert not path.exists(), "loading must never create the file"
    assert not path.parent.exists()


def test_empty_file(write) -> None:
    cfg = load_config(write(""))
    assert cfg.exists
    assert cfg.errors == [] and cfg.warnings == []
    assert cfg.agents == {}
    assert cfg.chat.font_size == 14


def test_syntax_error_gives_one_error_with_line(write) -> None:
    cfg = load_config(write(GOOD_ACP + "\nbroken = \n"))
    assert len(cfg.errors) == 1
    error = cfg.errors[0]
    assert error.path == ""
    assert error.line == 7
    assert error.message.startswith("błąd składni TOML")
    assert "at line" not in error.message
    assert cfg.agents == {}


def test_duplicate_key_is_syntax_error(write) -> None:
    cfg = load_config(write(GOOD_ACP + GOOD_ACP))
    assert len(cfg.errors) == 1
    assert cfg.errors[0].line is not None


def test_not_utf8(tmp_path: Path, isolated_env) -> None:
    path = tmp_path / "config.toml"
    path.write_bytes(b'default_agent = "\xff"\n')
    path.chmod(0o600)
    cfg = load_config(path)
    assert len(cfg.errors) == 1
    assert "UTF-8" in cfg.errors[0].message


def test_unreadable_path_is_error(tmp_path: Path, isolated_env) -> None:
    directory = tmp_path / "dir.toml"
    directory.mkdir()
    cfg = load_config(directory)
    assert len(cfg.errors) == 1
    assert cfg.errors[0].message.startswith("nie można odczytać pliku")


# -- location ------------------------------------------------------------------------------


def test_config_path_xdg(isolated_env) -> None:
    assert config_path() == isolated_env["XDG_CONFIG_HOME"] / "gnome-ai-panel" / "config.toml"


def test_config_path_env_override_is_absolute(
    isolated_env, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AI_PANEL_CONFIG", "sub/c.toml")
    assert config_path() == tmp_path / "sub" / "c.toml"
    monkeypatch.setenv("AI_PANEL_CONFIG", "~/c.toml")
    assert config_path() == isolated_env["HOME"] / "c.toml"


def test_config_path_ignores_relative_xdg(isolated_env, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", "relative")
    assert config_path() == isolated_env["HOME"] / ".config" / "gnome-ai-panel" / "config.toml"


def test_load_uses_env_path(write, monkeypatch: pytest.MonkeyPatch) -> None:
    path = write(GOOD_ACP)
    monkeypatch.setenv("AI_PANEL_CONFIG", str(path))
    cfg = load_config()
    assert cfg.path == path
    assert list(cfg.agents) == ["ok"]


# -- path expansion ------------------------------------------------------------------------


def test_tilde_expansion(write, isolated_env) -> None:
    cfg = load_config(
        write(
            """
[agents.a]
type = "acp"
command = "~/bin/agent"
args = ["~/x", "acp", "--flag=~/y"]
cwd = "~/.cache/ai-panel"
[chat]
history_dir = "~/hist"
"""
        )
    )
    home = isolated_env["HOME"]
    agent = cfg.agents["a"]
    assert agent.command == str(home / "bin" / "agent")
    assert agent.args == [str(home / "x"), "acp", "--flag=~/y"]
    assert agent.cwd == home / ".cache" / "ai-panel"
    assert cfg.chat.history_dir == home / "hist"


def test_relative_paths_resolve_against_config_dir(write, tmp_path: Path) -> None:
    cfg = load_config(
        write(
            """
[agents.a]
type = "acp"
command = "../venv/bin/python"
args = ["./fake.py", "--scenario", "echo", "../other.py"]
cwd = "work"
[mcp.m]
command = "./mcp.py"
args = ["plain", "./rel"]
[chat]
history_dir = "hist"
"""
        )
    )
    assert cfg.errors == []
    agent = cfg.agents["a"]
    assert agent.command == str(tmp_path.parent / "venv" / "bin" / "python")
    assert agent.args == [
        str(tmp_path / "fake.py"),
        "--scenario",
        "echo",
        str(tmp_path.parent / "other.py"),
    ]
    assert agent.cwd == tmp_path / "work"
    assert cfg.mcp["m"].command == str(tmp_path / "mcp.py")
    assert cfg.mcp["m"].args == ["plain", str(tmp_path / "rel")]
    assert cfg.chat.history_dir == tmp_path / "hist"


def test_bare_command_left_for_path_lookup(write) -> None:
    cfg = load_config(write(GOOD_ACP.replace("/usr/bin/true", "kiro-cli")))
    assert cfg.agents["ok"].command == "kiro-cli"


def test_env_vars_expanded_in_paths(write, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIP_TEST_DIR", "/opt/aip")
    cfg = load_config(write(GOOD_ACP.replace("/srv/ai-panel-cwd", "$AIP_TEST_DIR/cwd")))
    assert cfg.agents["ok"].cwd == Path("/opt/aip/cwd")


# -- validation errors ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("body", "error_path", "fragment"),
    [
        ('type = "acp"\ncwd = "/x"', "agents.bad.command", "wymagane"),
        ('type = "acp"\ncommand = "/x"', "agents.bad.cwd", "wymagane"),
        ('type = "acp"\ncommand = ""\ncwd = "/x"', "agents.bad.command", "puste"),
        ('type = "acp"\ncommand = 5\ncwd = "/x"', "agents.bad.command", "tekst"),
        ('command = "/x"\ncwd = "/x"', "agents.bad.type", "wymagane"),
        ('type = "ssh"\ncommand = "/x"\ncwd = "/x"', "agents.bad.type", "nieznany typ"),
        ('type = "acp"\ncommand = "/x"\ncwd = "/x"\nargs = "acp"', "agents.bad.args", "lista"),
        (
            'type = "acp"\ncommand = "/x"\ncwd = "/x"\nargs = ["a", 1]',
            "agents.bad.args[1]",
            "tekst",
        ),
        (
            'type = "acp"\ncommand = "/x"\ncwd = "/x"\nstartup_timeout_s = "20"',
            "agents.bad.startup_timeout_s",
            "liczba",
        ),
        (
            'type = "acp"\ncommand = "/x"\ncwd = "/x"\nstartup_timeout_s = 0',
            "agents.bad.startup_timeout_s",
            "zakresem",
        ),
        (
            'type = "acp"\ncommand = "/x"\ncwd = "/x"\nstartup_timeout_s = true',
            "agents.bad.startup_timeout_s",
            "logiczna",
        ),
        (
            'type = "acp"\ncommand = "/x"\ncwd = "/x"\nmcp = ["ghost"]',
            "agents.bad.mcp[0]",
            "[mcp.ghost]",
        ),
        (
            'type = "acp"\ncommand = "/x"\ncwd = "/x"\nsession_meta = "x"',
            "agents.bad.session_meta",
            "tabela",
        ),
        (
            'type = "acp"\ncommand = "/x"\ncwd = "/x"\nsession_meta = { when = 2026-01-01 }',
            "agents.bad.session_meta.when",
            "nieobsługiwany",
        ),
        ('type = "acp"\ncommand = "/x"\ncwd = "/x"\nenv = 1', "agents.bad.env", "tabela"),
        (
            'type = "acp"\ncommand = "/x"\ncwd = "/x"\nenv = { A = "plain" }',
            "agents.bad.env.A",
            "tabela",
        ),
        (
            'type = "acp"\ncommand = "/x"\ncwd = "/x"\nenv = { "1A" = { source = "prompt" } }',
            "agents.bad.env.1A",
            "nazwa zmiennej",
        ),
        (
            'type = "acp"\ncommand = "/x"\ncwd = "/x"\nenv = { A = { name = "x" } }',
            "agents.bad.env.A.source",
            "wymagane",
        ),
        (
            'type = "acp"\ncommand = "/x"\ncwd = "/x"\nenv = { A = { source = "vault" } }',
            "agents.bad.env.A.source",
            "nieznane źródło",
        ),
        (
            'type = "acp"\ncommand = "/x"\ncwd = "/x"\nenv = { A = { source = "keyring" } }',
            "agents.bad.env.A.name",
            "wymagane",
        ),
        (
            'type = "acp"\ncommand = "/x"\ncwd = "/x"\n'
            'env = { A = { source = "env", name = "BAD-NAME" } }',
            "agents.bad.env.A.name",
            "nazwa zmiennej",
        ),
        (
            'type = "acp"\ncommand = "/x"\ncwd = "/x"\nenv = { A = { source = "command" } }',
            "agents.bad.env.A.cmd",
            "wymagane",
        ),
        (
            'type = "acp"\ncommand = "/x"\ncwd = "/x"\n'
            'env = { A = { source = "command", cmd = "pass \'x" } }',
            "agents.bad.env.A.cmd",
            "argumenty",
        ),
        (
            'type = "acp"\ncommand = "/x"\ncwd = "/x"\n'
            'env = { A = { source = "command", cmd = "x", timeout_s = -1 } }',
            "agents.bad.env.A.timeout_s",
            "zakresem",
        ),
        (
            'type = "acp"\ncommand = "/x"\ncwd = "/x"\n'
            'env = { A = { source = "prompt", label = 3 } }',
            "agents.bad.env.A.label",
            "tekst",
        ),
        (
            'type = "acp"\ncommand = "/x"\ncwd = "/x"\nenv = { A = { source = "literal" } }',
            "agents.bad.env.A.value",
            "wymagane",
        ),
        ('type = "api"\nmodel = "m"', "agents.bad.endpoint", "wymagane"),
        ('type = "api"\nendpoint = "https://h/v1"', "agents.bad.model", "wymagane"),
        ('type = "api"\nendpoint = "ftp://h"\nmodel = "m"', "agents.bad.endpoint", "http"),
        ('type = "api"\nendpoint = "https://"\nmodel = "m"', "agents.bad.endpoint", "http"),
        (
            'type = "api"\nendpoint = "https://h"\nmodel = "m"\nmax_tokens = 0',
            "agents.bad.max_tokens",
            "większa od zera",
        ),
        (
            'type = "api"\nendpoint = "https://h"\nmodel = "m"\nmax_tokens = 1.5',
            "agents.bad.max_tokens",
            "całkowita",
        ),
        (
            'type = "api"\nendpoint = "https://h"\nmodel = "m"\nmodels = ["m", ""]',
            "agents.bad.models[1]",
            "puste",
        ),
        (
            'type = "api"\nendpoint = "https://h"\nmodel = "m"\napi_key = "sk-x"',
            "agents.bad.api_key",
            "tabela",
        ),
        (
            'type = "api"\nendpoint = "https://h"\nmodel = "m"\napi_key = { source = "nope" }',
            "agents.bad.api_key.source",
            "nieznane źródło",
        ),
    ],
)
def test_invalid_agent_is_skipped_rest_works(write, body, error_path, fragment) -> None:
    cfg = load_config(write(GOOD_ACP + "\n[agents.bad]\n" + body + "\n"))
    assert error_path in paths(cfg.errors), cfg.errors
    message = next(e.message for e in cfg.errors if e.path == error_path)
    assert fragment in message
    assert "bad" not in cfg.agents
    assert cfg.skipped_agents == ["bad"]
    assert list(cfg.agents) == ["ok"]


def test_agent_not_a_table(write) -> None:
    cfg = load_config(write("agents = { x = 1 }\n"))
    assert paths(cfg.errors) == ["agents.x"]
    assert cfg.skipped_agents == ["x"]


def test_agents_not_a_table(write) -> None:
    cfg = load_config(write('agents = "x"\n'))
    assert paths(cfg.errors) == ["agents"]


def test_mcp_reference_to_invalid_server(write) -> None:
    cfg = load_config(
        write(
            """
[mcp.broken]
args = []
[agents.a]
type = "acp"
command = "/x"
cwd = "/x"
mcp = ["broken"]
"""
        )
    )
    assert paths(cfg.errors) == ["mcp.broken.command", "agents.a.mcp[0]"]
    assert "ma błędy" in cfg.errors[1].message
    assert cfg.mcp == {} and cfg.agents == {}


def test_valid_mcp_reference(write) -> None:
    cfg = load_config(
        write(
            """
[mcp.g]
command = "g"
env = { TOKEN = { source = "keyring", name = "g" } }
[agents.a]
type = "acp"
command = "/x"
cwd = "/x"
mcp = ["g"]
"""
        )
    )
    assert cfg.errors == []
    assert cfg.agents["a"].mcp == ["g"]
    assert cfg.mcp["g"].env == {"TOKEN": Keyring("g")}


def test_invalid_mcp_server_skipped(write) -> None:
    cfg = load_config(write('[mcp.a]\ncommand = 1\n[mcp.b]\ncommand = "b"\n'))
    assert paths(cfg.errors) == ["mcp.a.command"]
    assert list(cfg.mcp) == ["b"]


def test_several_errors_in_one_agent_all_reported(write) -> None:
    cfg = load_config(write(f"{(DATA / 'config_invalid.toml').read_text(encoding='utf-8')}"))
    assert set(paths(cfg.errors)) == {
        "agents.broken.command",
        "agents.broken.startup_timeout_s",
        "agents.broken.mcp[0]",
        "agents.broken.env.TOKEN.source",
    }
    assert list(cfg.agents) == ["good"]
    assert cfg.default_agent == "good"


def test_invalid_id(write) -> None:
    cfg = load_config(write('[agents.""]\ntype = "acp"\ncommand = "/x"\ncwd = "/x"\n'))
    assert paths(cfg.errors) == ["agents."]
    assert cfg.agents == {}


# -- default_agent -------------------------------------------------------------------------


def test_default_agent_empty_allowed(write) -> None:
    cfg = load_config(write('default_agent = ""\n' + GOOD_ACP))
    assert cfg.errors == []
    assert cfg.default_agent is None


def test_default_agent_unknown(write) -> None:
    cfg = load_config(write('default_agent = "ghost"\n' + GOOD_ACP))
    assert paths(cfg.errors) == ["default_agent"]
    assert "nieznany agent" in cfg.errors[0].message
    assert cfg.default_agent is None
    assert list(cfg.agents) == ["ok"]


def test_default_agent_points_to_invalid_agent(write) -> None:
    cfg = load_config(write('default_agent = "bad"\n[agents.bad]\ntype = "acp"\n'))
    assert "default_agent" in paths(cfg.errors)
    message = next(e.message for e in cfg.errors if e.path == "default_agent")
    assert "ma błędy" in message


def test_default_agent_wrong_type(write) -> None:
    cfg = load_config(write("default_agent = 3\n"))
    assert paths(cfg.errors) == ["default_agent"]


# -- [chat] --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("body", "error_path"),
    [
        ("font_size = 200", "chat.font_size"),
        ("font_size = 2", "chat.font_size"),
        ('font_size = "14"', "chat.font_size"),
        ('theme = "blue"', "chat.theme"),
        ("theme = 1", "chat.theme"),
        ('history_dir = ""', "chat.history_dir"),
    ],
)
def test_chat_invalid_value_falls_back_to_default(write, isolated_env, body, error_path) -> None:
    cfg = load_config(write(GOOD_ACP + "\n[chat]\n" + body + "\n"))
    assert paths(cfg.errors) == [error_path]
    assert cfg.chat.font_size == 14
    assert cfg.chat.theme == "system"
    assert cfg.chat.history_dir == isolated_env["XDG_DATA_HOME"] / "gnome-ai-panel"
    assert list(cfg.agents) == ["ok"]


def test_chat_values(write) -> None:
    cfg = load_config(write('[chat]\nfont_size = 18\ntheme = "dark"\nhistory_dir = "/h"\n'))
    assert cfg.errors == []
    assert (cfg.chat.font_size, cfg.chat.theme, cfg.chat.history_dir) == (18, "dark", Path("/h"))


def test_chat_not_a_table(write) -> None:
    cfg = load_config(write('chat = "x"\n'))
    assert paths(cfg.errors) == ["chat"]


# -- optional fields and defaults ----------------------------------------------------------


def test_acp_optional_fields(write) -> None:
    cfg = load_config(
        write(
            """
[agents.a]
type = "acp"
name = "Mój agent"
command = "/x"
cwd = "/x"
startup_timeout_s = 1.5
system_prompt = "Bądź zwięzły."
[agents.a.session_meta]
claudeCode = { options = { disallowedTools = ["Bash"] } }
"""
        )
    )
    assert cfg.errors == []
    agent = cfg.agents["a"]
    assert agent.name == "Mój agent"
    assert agent.startup_timeout_s == 1.5
    assert agent.system_prompt == "Bądź zwięzły."
    assert agent.session_meta == {"claudeCode": {"options": {"disallowedTools": ["Bash"]}}}


def test_api_models_include_model(write) -> None:
    cfg = load_config(
        write(
            """
[agents.a]
type = "api"
endpoint = "http://127.0.0.1:1/v1/messages"
model = "m2"
models = ["m1"]
max_tokens = 100
anthropic_version = "2024-01-01"
api_key = { source = "env", name = "ANTHROPIC_API_KEY" }
"""
        )
    )
    assert cfg.errors == []
    agent = cfg.agents["a"]
    assert agent.models == ["m2", "m1"]
    assert agent.max_tokens == 100
    assert agent.anthropic_version == "2024-01-01"
    assert agent.api_key == Env("ANTHROPIC_API_KEY")


def test_command_source_timeout(write) -> None:
    cfg = load_config(
        write(
            GOOD_ACP + '[agents.ok.env]\nX = { source = "command", cmd = "a b", timeout_s = 2 }\n'
        )
    )
    assert cfg.agents["ok"].env["X"] == Command("a b", 2.0)


def test_unknown_keys_are_warnings(write) -> None:
    cfg = load_config(
        write(
            "colour = 1\n"
            + GOOD_ACP
            + 'extra = 1\n[agents.ok.env]\nX = { source = "env", name = "X", cmd = "y" }\n'
            + "[chat]\nwidth = 400\n"
        )
    )
    assert cfg.errors == []
    assert set(paths(cfg.warnings)) == {
        "colour",
        "agents.ok.extra",
        "agents.ok.env.X.cmd",
        "chat.width",
    }
    assert list(cfg.agents) == ["ok"]


# -- warnings: literal secrets and permissions ---------------------------------------------


def test_literal_warning_for_secret_like_names(write) -> None:
    cfg = load_config(
        write(
            GOOD_ACP
            + "[agents.ok.env]\n"
            + 'SOME_API_KEY = { source = "literal", value = "abc" }\n'
            + 'PLAIN_VALUE = { source = "literal", value = "tekst" }\n'
            + 'my_token = { source = "literal", value = "t" }\n'
            + 'DB_PASSWORD = { source = "literal", value = "p" }\n'
            + 'ClientSecret = { source = "literal", value = "s" }\n'
            + 'OTHER_KEY = { source = "keyring", name = "k" }\n'
        )
    )
    assert cfg.errors == []
    assert paths(cfg.warnings) == [
        "agents.ok.env.SOME_API_KEY",
        "agents.ok.env.my_token",
        "agents.ok.env.DB_PASSWORD",
        "agents.ok.env.ClientSecret",
    ]
    assert "literal" in cfg.warnings[0].message
    assert cfg.agents["ok"].env["SOME_API_KEY"] == Literal("abc")


def test_literal_warning_for_api_key(write) -> None:
    cfg = load_config(
        write(
            '[agents.a]\ntype = "api"\nendpoint = "https://h"\nmodel = "m"\n'
            'api_key = { source = "literal", value = "sk-x" }\n'
        )
    )
    assert cfg.errors == []
    assert paths(cfg.warnings) == ["agents.a.api_key"]


def test_literal_value_not_in_repr() -> None:
    assert "sk-secret" not in repr(Literal("sk-secret"))


def test_permission_warning_0666(write) -> None:
    path = write(GOOD_ACP)
    path.chmod(0o666)
    cfg = load_config(path)
    assert cfg.errors == []
    assert len(cfg.warnings) == 1
    warning = cfg.warnings[0]
    assert warning.path == ""
    assert "0666" in warning.message and str(path) in warning.message
    assert list(cfg.agents) == ["ok"]


@pytest.mark.parametrize("mode", [0o620, 0o602])
def test_permission_warning_group_or_other_writable(write, mode) -> None:
    path = write(GOOD_ACP)
    path.chmod(mode)
    assert len(load_config(path).warnings) == 1


@pytest.mark.parametrize("mode", [0o600, 0o644, 0o400])
def test_no_permission_warning(write, mode) -> None:
    path = write(GOOD_ACP)
    path.chmod(mode)
    assert load_config(path).warnings == []


def test_permission_warning_even_on_syntax_error(write) -> None:
    path = write("x = \n")
    path.chmod(0o666)
    cfg = load_config(path)
    assert len(cfg.errors) == 1 and len(cfg.warnings) == 1
