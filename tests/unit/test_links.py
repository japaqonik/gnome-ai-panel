import pytest

from app import links
from app.links import Decision

INDEX = "file:///opt/app/ui/index.html"


@pytest.mark.parametrize(
    "uri",
    [INDEX, INDEX + "#section", "file:///opt/app/ui/index.html#"],
)
def test_index_page_may_load(uri) -> None:
    assert links.decide(uri, INDEX) is Decision.ALLOW


@pytest.mark.parametrize(
    "uri",
    [
        "https://example.com/",
        "http://example.com/a?b=c#d",
        "HTTPS://Example.COM/",
        "mailto:someone@example.com",
    ],
)
def test_web_and_mail_links_are_launched(uri) -> None:
    assert links.decide(uri, INDEX) is Decision.LAUNCH
    assert links.decide(uri, INDEX, new_window=True) is Decision.LAUNCH


@pytest.mark.parametrize(
    "uri",
    [
        None,
        "",
        "file:///opt/app/ui/other.html",  # relative link of model output
        "file:///opt/app/ui/index.html?x=1",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "about:blank",
        "ftp://example.com/",
        "vbscript:x",
        "https://",  # no host
        "mailto:",
        "https://example.com/\nX",
        "https://example.com/" + "a" * links.MAX_URI_LENGTH,
    ],
)
def test_everything_else_is_blocked(uri) -> None:
    assert links.decide(uri, INDEX) is Decision.BLOCK


def test_new_window_never_shows_the_page() -> None:
    assert links.decide(INDEX, INDEX, new_window=True) is Decision.BLOCK


def test_context_menu_hides_reload_and_inspect_outside_debug() -> None:
    normal = links.hidden_menu_actions(debug=False)
    debug = links.hidden_menu_actions(debug=True)
    assert {"RELOAD", "INSPECT_ELEMENT", "OPEN_LINK_IN_NEW_WINDOW", "GO_BACK"} <= normal
    assert "RELOAD" not in debug and "INSPECT_ELEMENT" not in debug
    assert "OPEN_LINK_IN_NEW_WINDOW" in debug
    assert "COPY" not in normal and "COPY_LINK_TO_CLIPBOARD" not in normal


def test_menu_action_names_exist_in_webkit() -> None:
    import gi

    gi.require_version("WebKit", "6.0")
    from gi.repository import WebKit

    for name in links.hidden_menu_actions(debug=False):
        assert hasattr(WebKit.ContextMenuAction, name), name
