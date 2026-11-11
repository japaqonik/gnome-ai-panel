"""Connection test of one agent (FR-25): ``python -m app.cli test-agent ID`` and, later, the
"Test połączenia" button of the settings window.

``test_agent(cfg)`` starts a private ``AcpBackend`` (never the shared one of
``get_backend``, so a running conversation is not disturbed), runs ``initialize`` and
``session/new`` and closes the process again. Problems end up in ``TestResult.error`` as the
backend's ``Error`` event; ``describe_error`` adds a hint per error kind.

This module does not import GTK.
"""

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, ClassVar

from app import strings
from app.backends.acp import AcpBackend
from app.backends.base import BackendError, Error
from app.config import AcpAgent, Agent, McpServer
from app.secrets import PromptCallback, SecretStore

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TestResult:
    """``agent_info``/``protocol_version``/``auth_methods`` come from ``initialize`` and are
    also set when ``session/new`` failed afterwards (e.g. ``auth_required``)."""

    __test__: ClassVar[bool] = False  # not a pytest test class

    ok: bool
    agent_info: dict[str, Any] | None = None
    protocol_version: int | None = None
    auth_methods: list[dict[str, Any]] = field(default_factory=list)
    error: Error | None = None


async def test_agent(
    cfg: Agent,
    *,
    mcp: Mapping[str, McpServer] | None = None,
    store: SecretStore | None = None,
    prompt_cb: PromptCallback | None = None,
) -> TestResult:
    """Start the agent, ``initialize``, ``session/new``, close. Never raises for agent
    problems (missing command, bad protocol, login required, crash, timeout)."""
    if not isinstance(cfg, AcpAgent):
        return TestResult(
            ok=False, error=Error(strings.DIAG_UNSUPPORTED_TYPE.format(type=cfg.type), "other")
        )
    backend = AcpBackend(cfg, mcp, store=store, prompt_cb=prompt_cb)
    error: Error | None = None
    try:
        await backend.start()
        await backend.new_session()
    except BackendError as exc:
        error = exc.event
    except Exception as exc:  # the test must report, not crash (settings window, CLI)
        log.exception("%s: connection test failed unexpectedly", cfg.id)
        error = Error(strings.DIAG_UNEXPECTED.format(reason=exc), "other")
    finally:
        await backend.close()
    log.info("%s: connection test %s", cfg.id, "ok" if error is None else f"failed ({error.kind})")
    return TestResult(
        ok=error is None,
        agent_info=backend.agent_info,
        protocol_version=backend.protocol_version,
        auth_methods=list(backend.auth_methods),
        error=error,
    )


test_agent.__test__ = False  # type: ignore[attr-defined]  # not a pytest test


def describe_agent(info: dict[str, Any] | None) -> str:
    """``Title (name) version`` from ``agentInfo``; parts the agent did not send are left out."""
    if not info:
        return strings.DIAG_UNKNOWN_AGENT_INFO
    name = info.get("name") if isinstance(info.get("name"), str) else None
    title = info.get("title") if isinstance(info.get("title"), str) else None
    version = info.get("version") if isinstance(info.get("version"), str) else None
    if title and name and title != name:
        label = f"{title} ({name})"
    else:
        label = title or name or ""
    text = " ".join(part for part in (label, version) if part)
    return text or strings.DIAG_UNKNOWN_AGENT_INFO


def describe_error(error: Error) -> str:
    """The backend's message plus a hint for its kind (Polish, may span several lines)."""
    hint = strings.DIAG_HINTS.get(error.kind)
    return f"{error.message}\n{hint}" if hint else error.message
