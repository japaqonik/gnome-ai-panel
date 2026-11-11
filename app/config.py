"""``config.toml``: data model, file location, parsing and validation (PLAN §11.1).

``load_config()`` never raises for problems in the file. Everything wrong ends up in
``Config.errors`` / ``Config.warnings`` as ``ConfigError(path, message)``:

- missing file → empty, valid configuration (the file is never created here);
- unreadable file or TOML syntax error → empty configuration with one error (with line number
  for syntax errors);
- an invalid ``[agents.x]`` or ``[mcp.x]`` entry is skipped, the rest keeps working;
- an invalid ``[chat]`` value falls back to its default.

Value sources (``keyring``/``env``/``command``/``prompt``/``literal``) are only parsed here;
resolving them is done in ``app/secrets.py``.

Paths: ``~`` and ``$VARS`` are expanded in ``cwd``, ``history_dir``, path-like ``command``
values (containing ``/``) and ``args`` items starting with ``~``, ``./`` or ``../``. Relative
paths are resolved against the directory of the configuration file. A bare ``command`` such
as ``kiro-cli`` is left for the ``PATH`` lookup.

This module does not import GTK.
"""

import datetime
import os
import re
import shlex
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import tomlkit
from tomlkit.exceptions import TOMLKitError

from app import strings

CONFIG_ENV = "AI_PANEL_CONFIG"
APP_DIR_NAME = "gnome-ai-panel"
CONFIG_FILE_NAME = "config.toml"

AGENT_TYPES = ("acp", "api")
SOURCES = ("keyring", "env", "command", "prompt", "literal")
THEMES = ("system", "light", "dark")
FONT_SIZE_RANGE = (6, 72)
TIMEOUT_RANGE_S = (0.0, 600.0)  # exclusive lower bound, inclusive upper bound
DEFAULT_STARTUP_TIMEOUT_S = 20.0
DEFAULT_COMMAND_TIMEOUT_S = 10.0
DEFAULT_MAX_TOKENS = 4096
DEFAULT_ANTHROPIC_VERSION = "2023-06-01"

# Names that suggest a secret; a ``literal`` source for them gets a warning (PLAN §13).
SECRET_NAME_RE = re.compile(r"KEY|TOKEN|SECRET|PASSWORD", re.IGNORECASE)
ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_ID_RE = re.compile(r"^[^\s\x00-\x1f\x7f]+$")
_TOML_LOCATION_RE = re.compile(r"\s+at line \d+ col \d+$")


# -- value sources -------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Keyring:
    name: str


@dataclass(frozen=True, slots=True)
class Env:
    name: str


@dataclass(frozen=True, slots=True)
class Command:
    cmd: str
    timeout_s: float = DEFAULT_COMMAND_TIMEOUT_S


@dataclass(frozen=True, slots=True)
class Prompt:
    label: str | None = None


@dataclass(frozen=True, slots=True)
class Literal:
    # Kept out of repr: a literal may still be a secret pasted by mistake.
    value: str = field(repr=False)


type ValueSource = Keyring | Env | Command | Prompt | Literal


# -- entries -------------------------------------------------------------------------------


@dataclass(slots=True)
class AcpAgent:
    id: str
    name: str
    command: str
    cwd: Path
    args: list[str] = field(default_factory=list)
    env: dict[str, ValueSource] = field(default_factory=dict)
    startup_timeout_s: float = DEFAULT_STARTUP_TIMEOUT_S
    mcp: list[str] = field(default_factory=list)
    session_meta: dict[str, Any] | None = None
    system_prompt: str | None = None
    type: str = field(default="acp", init=False)


@dataclass(slots=True)
class ApiAgent:
    id: str
    name: str
    endpoint: str
    model: str
    models: list[str] = field(default_factory=list)
    system_prompt: str | None = None
    api_key: ValueSource | None = None
    max_tokens: int = DEFAULT_MAX_TOKENS
    anthropic_version: str = DEFAULT_ANTHROPIC_VERSION
    type: str = field(default="api", init=False)


type Agent = AcpAgent | ApiAgent


@dataclass(slots=True)
class McpServer:
    id: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, ValueSource] = field(default_factory=dict)


def default_history_dir() -> Path:
    base = os.environ.get("XDG_DATA_HOME")
    if not base or not os.path.isabs(base):
        base = str(Path.home() / ".local" / "share")
    return Path(base) / APP_DIR_NAME


@dataclass(slots=True)
class ChatConfig:
    font_size: int = 14
    theme: str = "system"
    history_dir: Path = field(default_factory=default_history_dir)


@dataclass(frozen=True, slots=True)
class ConfigError:
    """A problem in the file. ``path`` is the dotted key (``agents.x.command``); it is empty
    for problems of the whole file (``line`` is then set for TOML syntax errors)."""

    path: str
    message: str
    line: int | None = None


@dataclass(slots=True)
class Config:
    path: Path
    exists: bool = False
    default_agent: str | None = None
    agents: dict[str, Agent] = field(default_factory=dict)
    mcp: dict[str, McpServer] = field(default_factory=dict)
    chat: ChatConfig = field(default_factory=ChatConfig)
    errors: list[ConfigError] = field(default_factory=list)
    warnings: list[ConfigError] = field(default_factory=list)
    skipped_agents: list[str] = field(default_factory=list)


# -- location and loading ------------------------------------------------------------------


def config_path() -> Path:
    """``$AI_PANEL_CONFIG`` or ``$XDG_CONFIG_HOME/gnome-ai-panel/config.toml`` (absolute)."""
    override = os.environ.get(CONFIG_ENV)
    if override:
        return Path(os.path.abspath(os.path.expanduser(override)))
    base = os.environ.get("XDG_CONFIG_HOME")
    if not base or not os.path.isabs(base):
        base = str(Path.home() / ".config")
    return Path(base) / APP_DIR_NAME / CONFIG_FILE_NAME


def load_config(path: str | os.PathLike[str] | None = None) -> Config:
    """Read and validate the configuration file (default: ``config_path()``)."""
    file = Path(os.path.abspath(os.path.expanduser(path))) if path else config_path()
    config = Config(path=file)

    try:
        st = os.stat(file)
    except FileNotFoundError:
        return config
    except OSError as exc:
        config.errors.append(ConfigError("", strings.CFG_READ_ERROR.format(reason=_reason(exc))))
        return config

    config.exists = True
    if stat.S_ISREG(st.st_mode) and st.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        mode = f"{stat.S_IMODE(st.st_mode):04o}"
        config.warnings.append(
            ConfigError("", strings.CFG_PERMISSIONS.format(file=file, mode=mode))
        )

    try:
        raw = file.read_bytes()
    except OSError as exc:
        config.errors.append(ConfigError("", strings.CFG_READ_ERROR.format(reason=_reason(exc))))
        return config
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        config.errors.append(ConfigError("", strings.CFG_NOT_UTF8.format(position=exc.start)))
        return config

    try:
        data = tomlkit.parse(text).unwrap()
    except TOMLKitError as exc:
        reason = _TOML_LOCATION_RE.sub("", str(exc))
        line = getattr(exc, "line", None)
        config.errors.append(ConfigError("", strings.CFG_SYNTAX.format(reason=reason), line=line))
        return config

    _Parser(config, base_dir=file.parent).parse(data)
    return config


def _reason(exc: OSError) -> str:
    return exc.strerror or str(exc)


# -- validation ----------------------------------------------------------------------------

_MISSING = object()

_ACP_KEYS = {
    "type",
    "name",
    "command",
    "args",
    "cwd",
    "env",
    "startup_timeout_s",
    "mcp",
    "session_meta",
    "system_prompt",
}
_API_KEYS = {
    "type",
    "name",
    "endpoint",
    "model",
    "models",
    "system_prompt",
    "api_key",
    "max_tokens",
    "anthropic_version",
}
_MCP_KEYS = {"command", "args", "env"}
_CHAT_KEYS = {"font_size", "theme", "history_dir"}
_TOP_KEYS = {"default_agent", "agents", "mcp", "chat"}
_SOURCE_KEYS = {
    "keyring": {"name"},
    "env": {"name"},
    "command": {"cmd", "timeout_s"},
    "prompt": {"label"},
    "literal": {"value"},
}


def _type_name(value: object) -> str:
    return strings.TYPE_NAMES.get(type(value).__name__, type(value).__name__)


def _join(prefix: str, key: str) -> str:
    return f"{prefix}.{key}" if prefix else key


class _Parser:
    def __init__(self, config: Config, base_dir: Path) -> None:
        self.config = config
        self.base_dir = base_dir

    # -- reporting

    def error(self, path: str, message: str) -> None:
        self.config.errors.append(ConfigError(path, message))

    def warn(self, path: str, message: str) -> None:
        self.config.warnings.append(ConfigError(path, message))

    def _unknown_keys(self, table: dict[str, Any], allowed: set[str], prefix: str) -> None:
        for key in table:
            if key not in allowed:
                self.warn(_join(prefix, key), strings.CFG_UNKNOWN_KEY)

    # -- typed getters: return _MISSING when absent, None after reporting an error

    def _get(self, table: dict[str, Any], key: str, prefix: str, required: bool) -> Any:
        if key not in table:
            if required:
                self.error(_join(prefix, key), strings.CFG_REQUIRED)
                return None
            return _MISSING
        return table[key]

    def _wrong_type(self, path: str, expected: str, value: object) -> None:
        self.error(
            path,
            strings.CFG_WRONG_TYPE.format(
                expected=strings.TYPE_NAMES[expected], actual=_type_name(value)
            ),
        )

    def get_str(
        self,
        table: dict[str, Any],
        key: str,
        prefix: str,
        *,
        required: bool = False,
        allow_empty: bool = False,
    ) -> Any:
        value = self._get(table, key, prefix, required)
        if value is _MISSING or value is None:
            return value
        path = _join(prefix, key)
        if not isinstance(value, str):
            self._wrong_type(path, "str", value)
            return None
        if not allow_empty and not value.strip():
            self.error(path, strings.CFG_EMPTY)
            return None
        return value

    def get_str_list(self, table: dict[str, Any], key: str, prefix: str) -> Any:
        value = self._get(table, key, prefix, required=False)
        if value is _MISSING:
            return value
        path = _join(prefix, key)
        if not isinstance(value, list):
            self._wrong_type(path, "list", value)
            return None
        ok = True
        for index, item in enumerate(value):
            if not isinstance(item, str):
                self._wrong_type(f"{path}[{index}]", "str", item)
                ok = False
        return list(value) if ok else None

    def get_number(
        self, table: dict[str, Any], key: str, prefix: str, *, integer: bool = False
    ) -> Any:
        value = self._get(table, key, prefix, required=False)
        if value is _MISSING:
            return value
        path = _join(prefix, key)
        types = (int,) if integer else (int, float)
        if isinstance(value, bool) or not isinstance(value, types):
            self._wrong_type(path, "int" if integer else "number", value)
            return None
        return value

    def get_timeout(self, table: dict[str, Any], key: str, prefix: str) -> Any:
        value = self.get_number(table, key, prefix)
        if value is _MISSING or value is None:
            return value
        low, high = TIMEOUT_RANGE_S
        if not low < value <= high:
            self.error(
                _join(prefix, key),
                strings.CFG_OUT_OF_RANGE.format(value=value, low=low, high=high),
            )
            return None
        return float(value)

    def get_table(self, table: dict[str, Any], key: str, prefix: str) -> Any:
        value = self._get(table, key, prefix, required=False)
        if value is _MISSING:
            return value
        if not isinstance(value, dict):
            self._wrong_type(_join(prefix, key), "dict", value)
            return None
        return value

    # -- paths

    def expand_path(self, value: str) -> Path:
        expanded = os.path.expandvars(os.path.expanduser(value))
        return Path(os.path.abspath(os.path.join(self.base_dir, expanded)))

    def expand_command(self, value: str) -> str:
        expanded = os.path.expandvars(os.path.expanduser(value))
        if "/" not in expanded:
            return expanded
        return str(self.expand_path(expanded))

    def expand_args(self, args: list[str]) -> list[str]:
        result = []
        for arg in args:
            if arg.startswith(("~", "./", "../")):
                result.append(str(self.expand_path(arg)))
            else:
                result.append(arg)
        return result

    # -- top level

    def parse(self, data: dict[str, Any]) -> None:
        self._unknown_keys(data, _TOP_KEYS, "")
        self.parse_mcp_servers(data)
        self.parse_agents(data)
        self.parse_default_agent(data)
        self.parse_chat(data)

    def _entries(self, data: dict[str, Any], key: str) -> dict[str, Any]:
        value = self.get_table(data, key, "")
        if value is _MISSING or value is None:
            return {}
        return value

    def _valid_id(self, entry_id: str, path: str) -> bool:
        if _ID_RE.match(entry_id):
            return True
        self.error(path, strings.CFG_INVALID_ID.format(value=entry_id))
        return False

    def parse_mcp_servers(self, data: dict[str, Any]) -> None:
        self.mcp_defined: set[str] = set()
        for server_id, table in self._entries(data, "mcp").items():
            self.mcp_defined.add(server_id)
            prefix = f"mcp.{server_id}"
            before = len(self.config.errors)
            if not self._valid_id(server_id, prefix):
                continue
            if not isinstance(table, dict):
                self._wrong_type(prefix, "dict", table)
                continue
            self._unknown_keys(table, _MCP_KEYS, prefix)
            command = self.get_str(table, "command", prefix, required=True)
            args = self.get_str_list(table, "args", prefix)
            env = self.parse_env(table, prefix)
            if len(self.config.errors) > before:
                continue
            self.config.mcp[server_id] = McpServer(
                id=server_id,
                command=self.expand_command(command),
                args=self.expand_args(args if args is not _MISSING else []),
                env=env,
            )

    def parse_agents(self, data: dict[str, Any]) -> None:
        for agent_id, table in self._entries(data, "agents").items():
            prefix = f"agents.{agent_id}"
            before = len(self.config.errors)
            agent = self.parse_agent(agent_id, table, prefix)
            if agent is None or len(self.config.errors) > before:
                self.config.skipped_agents.append(agent_id)
                continue
            self.config.agents[agent_id] = agent

    def parse_agent(self, agent_id: str, table: Any, prefix: str) -> Agent | None:
        if not self._valid_id(agent_id, prefix):
            return None
        if not isinstance(table, dict):
            self._wrong_type(prefix, "dict", table)
            return None
        agent_type = self.get_str(table, "type", prefix, required=True)
        if agent_type is None:
            return None
        if agent_type not in AGENT_TYPES:
            self.error(
                f"{prefix}.type",
                strings.CFG_UNKNOWN_AGENT_TYPE.format(
                    value=agent_type, allowed=", ".join(AGENT_TYPES)
                ),
            )
            return None
        name = self.get_str(table, "name", prefix)
        name = agent_id if name is _MISSING or name is None else name
        if agent_type == "acp":
            return self.parse_acp(agent_id, name, table, prefix)
        return self.parse_api(agent_id, name, table, prefix)

    def parse_acp(self, agent_id: str, name: str, table: dict[str, Any], prefix: str) -> Any:
        self._unknown_keys(table, _ACP_KEYS, prefix)
        command = self.get_str(table, "command", prefix, required=True)
        args = self.get_str_list(table, "args", prefix)
        cwd = self.get_str(table, "cwd", prefix, required=True)
        env = self.parse_env(table, prefix)
        timeout = self.get_timeout(table, "startup_timeout_s", prefix)
        mcp = self.parse_mcp_refs(table, prefix)
        session_meta = self.get_table(table, "session_meta", prefix)
        if isinstance(session_meta, dict):
            self.check_json_value(session_meta, f"{prefix}.session_meta")
        system_prompt = self.get_str(table, "system_prompt", prefix, allow_empty=True)
        if None in (command, args, cwd, timeout, mcp, session_meta, system_prompt):
            return None
        return AcpAgent(
            id=agent_id,
            name=name,
            command=self.expand_command(command),
            cwd=self.expand_path(cwd),
            args=self.expand_args(args if args is not _MISSING else []),
            env=env,
            startup_timeout_s=DEFAULT_STARTUP_TIMEOUT_S if timeout is _MISSING else timeout,
            mcp=mcp,
            session_meta=None if session_meta is _MISSING else dict(session_meta),
            system_prompt=None if system_prompt is _MISSING else system_prompt,
        )

    def parse_api(self, agent_id: str, name: str, table: dict[str, Any], prefix: str) -> Any:
        self._unknown_keys(table, _API_KEYS, prefix)
        endpoint = self.get_str(table, "endpoint", prefix, required=True)
        if isinstance(endpoint, str):
            url = urlparse(endpoint)
            if url.scheme not in ("http", "https") or not url.netloc:
                self.error(f"{prefix}.endpoint", strings.CFG_BAD_URL)
                endpoint = None
        model = self.get_str(table, "model", prefix, required=True)
        models = self.get_str_list(table, "models", prefix)
        if isinstance(models, list):
            for index, item in enumerate(models):
                if not item.strip():
                    self.error(f"{prefix}.models[{index}]", strings.CFG_EMPTY)
                    models = None
                    break
        system_prompt = self.get_str(table, "system_prompt", prefix, allow_empty=True)
        api_key: Any = _MISSING
        if "api_key" in table:
            api_key = self.parse_source(table["api_key"], f"{prefix}.api_key", "api_key")
        max_tokens = self.get_number(table, "max_tokens", prefix, integer=True)
        if isinstance(max_tokens, int) and max_tokens < 1:
            self.error(f"{prefix}.max_tokens", strings.CFG_NOT_POSITIVE)
            max_tokens = None
        version = self.get_str(table, "anthropic_version", prefix)
        if None in (endpoint, model, models, system_prompt, api_key, max_tokens, version):
            return None
        model_list = [model] if models is _MISSING else list(models)
        if model not in model_list:
            model_list.insert(0, model)
        return ApiAgent(
            id=agent_id,
            name=name,
            endpoint=endpoint,
            model=model,
            models=model_list,
            system_prompt=None if system_prompt is _MISSING else system_prompt,
            api_key=None if api_key is _MISSING else api_key,
            max_tokens=DEFAULT_MAX_TOKENS if max_tokens is _MISSING else max_tokens,
            anthropic_version=DEFAULT_ANTHROPIC_VERSION if version is _MISSING else version,
        )

    def parse_mcp_refs(self, table: dict[str, Any], prefix: str) -> Any:
        refs = self.get_str_list(table, "mcp", prefix)
        if refs is _MISSING:
            return []
        if refs is None:
            return None
        ok = True
        for index, ref in enumerate(refs):
            path = f"{prefix}.mcp[{index}]"
            if ref not in self.mcp_defined:
                self.error(path, strings.CFG_UNKNOWN_MCP.format(value=ref))
                ok = False
            elif ref not in self.config.mcp:
                self.error(path, strings.CFG_INVALID_MCP.format(value=ref))
                ok = False
        return refs if ok else None

    def parse_env(self, table: dict[str, Any], prefix: str) -> dict[str, ValueSource]:
        env_table = self.get_table(table, "env", prefix)
        if not isinstance(env_table, dict):
            return {}
        result: dict[str, ValueSource] = {}
        for var, spec in env_table.items():
            path = f"{prefix}.env.{var}"
            if not ENV_NAME_RE.match(var):
                self.error(path, strings.CFG_INVALID_ENV_NAME.format(value=var))
                continue
            source = self.parse_source(spec, path, var)
            if source is not None:
                result[var] = source
        return result

    def parse_source(self, spec: Any, path: str, name: str) -> ValueSource | None:
        """Parse ``{ source = "…", … }``. ``name`` is checked for the ``literal`` warning."""
        if not isinstance(spec, dict):
            self._wrong_type(path, "dict", spec)
            return None
        source = self.get_str(spec, "source", path, required=True)
        if source is None:
            return None
        if source not in SOURCES:
            self.error(
                f"{path}.source",
                strings.CFG_UNKNOWN_SOURCE.format(value=source, allowed=", ".join(SOURCES)),
            )
            return None
        self._unknown_keys(spec, _SOURCE_KEYS[source] | {"source"}, path)
        before = len(self.config.errors)
        result: ValueSource | None = None
        if source in ("keyring", "env"):
            value = self.get_str(spec, "name", path, required=True)
            if source == "env" and isinstance(value, str) and not ENV_NAME_RE.match(value):
                self.error(f"{path}.name", strings.CFG_INVALID_ENV_NAME.format(value=value))
            elif isinstance(value, str):
                result = Keyring(value) if source == "keyring" else Env(value)
        elif source == "command":
            cmd = self.get_str(spec, "cmd", path, required=True)
            timeout = self.get_timeout(spec, "timeout_s", path)
            if isinstance(cmd, str):
                try:
                    shlex.split(cmd)
                except ValueError as exc:
                    self.error(f"{path}.cmd", strings.CFG_BAD_COMMAND_LINE.format(reason=exc))
                    cmd = None
            if isinstance(cmd, str) and timeout is not None:
                result = Command(cmd, DEFAULT_COMMAND_TIMEOUT_S if timeout is _MISSING else timeout)
        elif source == "prompt":
            label = self.get_str(spec, "label", path)
            if label is not None:
                result = Prompt(None if label is _MISSING else label)
        else:
            value = self.get_str(spec, "value", path, required=True, allow_empty=True)
            if isinstance(value, str):
                result = Literal(value)
                if SECRET_NAME_RE.search(name):
                    self.warn(path, strings.CFG_LITERAL_WARNING)
        return result if len(self.config.errors) == before else None

    def check_json_value(self, value: Any, path: str) -> None:
        """``session_meta`` is sent as JSON: reject TOML dates and times."""
        if isinstance(value, dict):
            for key, item in value.items():
                self.check_json_value(item, f"{path}.{key}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                self.check_json_value(item, f"{path}[{index}]")
        elif isinstance(value, datetime.date | datetime.time):
            self.error(path, strings.CFG_UNSUPPORTED_VALUE.format(actual=_type_name(value)))

    def parse_default_agent(self, data: dict[str, Any]) -> None:
        value = self.get_str(data, "default_agent", "", allow_empty=True)
        if not isinstance(value, str) or not value.strip():
            return
        if value in self.config.agents:
            self.config.default_agent = value
        elif value in self.config.skipped_agents:
            self.error("default_agent", strings.CFG_INVALID_DEFAULT.format(value=value))
        else:
            self.error("default_agent", strings.CFG_UNKNOWN_DEFAULT.format(value=value))

    def parse_chat(self, data: dict[str, Any]) -> None:
        table = self.get_table(data, "chat", "")
        if not isinstance(table, dict):
            return
        chat = self.config.chat
        self._unknown_keys(table, _CHAT_KEYS, "chat")
        font_size = self.get_number(table, "font_size", "chat", integer=True)
        if isinstance(font_size, int):
            low, high = FONT_SIZE_RANGE
            if low <= font_size <= high:
                chat.font_size = font_size
            else:
                self.error(
                    "chat.font_size",
                    strings.CFG_OUT_OF_RANGE.format(value=font_size, low=low, high=high),
                )
        theme = self.get_str(table, "theme", "chat")
        if isinstance(theme, str):
            if theme in THEMES:
                chat.theme = theme
            else:
                self.error(
                    "chat.theme", strings.CFG_CHOICE.format(value=theme, allowed=", ".join(THEMES))
                )
        history_dir = self.get_str(table, "history_dir", "chat")
        if isinstance(history_dir, str):
            chat.history_dir = self.expand_path(history_dir)
