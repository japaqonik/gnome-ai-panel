"""Navigation policy of the chat web view (FR-13). No GTK import.

The page renders model output, so every navigation it asks for is checked here:

- the main frame may only show ``app/ui/index.html`` (reload, fragment links);
- links to ``http``, ``https`` and ``mailto`` open in the default browser / mail client;
- everything else (``file:`` and other relative targets, ``javascript:``, ``data:`` …) is
  blocked;
- new windows are never created; a user's request for one is treated like a link.
"""

import enum
from urllib.parse import urlsplit, urlunsplit

EXTERNAL_SCHEMES = frozenset({"http", "https", "mailto"})
# Longer URIs are blocked (no real link needs them; keeps the URI log readable).
MAX_URI_LENGTH = 8192

# Context menu entries (WebKit.ContextMenuAction names) the page never offers: navigation
# inside the panel, new windows and downloads. RELOAD and INSPECT_ELEMENT stay in debug mode.
ALWAYS_HIDDEN_MENU_ACTIONS = frozenset(
    {
        "GO_BACK",
        "GO_FORWARD",
        "STOP",
        "OPEN_LINK",
        "OPEN_LINK_IN_NEW_WINDOW",
        "DOWNLOAD_LINK_TO_DISK",
        "OPEN_IMAGE_IN_NEW_WINDOW",
        "DOWNLOAD_IMAGE_TO_DISK",
        "OPEN_FRAME_IN_NEW_WINDOW",
        "OPEN_VIDEO_IN_NEW_WINDOW",
        "OPEN_AUDIO_IN_NEW_WINDOW",
        "DOWNLOAD_VIDEO_TO_DISK",
        "DOWNLOAD_AUDIO_TO_DISK",
    }
)
DEBUG_ONLY_MENU_ACTIONS = frozenset({"RELOAD", "INSPECT_ELEMENT"})


class Decision(enum.Enum):
    ALLOW = "allow"  # let the web view navigate
    LAUNCH = "launch"  # stay on the page, open the URI outside the app
    BLOCK = "block"  # stay on the page, do nothing


def _without_fragment(uri: str) -> str:
    parts = urlsplit(uri)
    return urlunsplit(parts._replace(fragment=""))


def is_external(uri: str) -> bool:
    """``uri`` may be handed to the desktop (``http``, ``https`` or ``mailto`` only)."""
    if not uri or len(uri) > MAX_URI_LENGTH:
        return False
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in uri):
        return False
    try:
        parts = urlsplit(uri)
    except ValueError:
        return False
    scheme = parts.scheme.lower()
    if scheme not in EXTERNAL_SCHEMES:
        return False
    if scheme == "mailto":
        return bool(parts.path)
    return bool(parts.hostname)


def decide(uri: str | None, index_uri: str, *, new_window: bool = False) -> Decision:
    """What to do with a navigation of the page to ``uri``."""
    if not uri:
        return Decision.BLOCK
    if not new_window:
        try:
            if _without_fragment(uri) == _without_fragment(index_uri):
                return Decision.ALLOW
        except ValueError:
            return Decision.BLOCK
    return Decision.LAUNCH if is_external(uri) else Decision.BLOCK


def hidden_menu_actions(debug: bool) -> frozenset[str]:
    """Names of ``WebKit.ContextMenuAction`` values removed from the context menu."""
    if debug:
        return ALWAYS_HIDDEN_MENU_ACTIONS
    return ALWAYS_HIDDEN_MENU_ACTIONS | DEBUG_ONLY_MENU_ACTIONS
