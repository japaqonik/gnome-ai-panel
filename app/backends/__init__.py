"""Backends: the common event model (``base``), JSON-RPC over stdio (``jsonrpc``), ACP and API.

``get_backend(agent_cfg)`` keeps one backend (one agent process) per agent id (FR-17). Asking
again with a changed configuration returns the same backend, which restarts its process at
the next ``new_session()``. ``close_all()`` stops every agent (application ``quit``).
"""

from collections.abc import Mapping

from app.backends.acp import AcpBackend
from app.backends.base import Backend
from app.config import AcpAgent, Agent, McpServer
from app.secrets import LibsecretStore, PromptCallback, SecretStore

_registry: dict[str, AcpBackend] = {}


def get_backend(
    agent_cfg: Agent,
    *,
    mcp: Mapping[str, McpServer] | None = None,
    store: SecretStore | None = None,
    prompt_cb: PromptCallback | None = None,
) -> Backend:
    """Backend for ``agent_cfg``; ``mcp`` are the ``[mcp.*]`` entries of the configuration.

    ``store`` defaults to the GNOME keyring (used only by ``keyring`` value sources).
    """
    if not isinstance(agent_cfg, AcpAgent):
        raise NotImplementedError(f"agent type {agent_cfg.type!r} is not supported yet")
    backend = _registry.get(agent_cfg.id)
    if backend is None or backend.closed:
        backend = AcpBackend(
            agent_cfg,
            mcp,
            store=store if store is not None else LibsecretStore(),
            prompt_cb=prompt_cb,
        )
        _registry[agent_cfg.id] = backend
    else:
        backend.reconfigure(agent_cfg, mcp)
    return backend


async def close_all() -> None:
    """Close every backend created by ``get_backend`` (SIGTERM, then SIGKILL after 3 s)."""
    backends = list(_registry.values())
    _registry.clear()
    for backend in backends:
        await backend.close()
