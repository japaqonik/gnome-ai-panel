"""Edge cases of the navigation policy (tester additions, S3-T4)."""

import pytest

from app import links
from app.links import Decision

INDEX = "file:///opt/app/ui/index.html"


@pytest.mark.parametrize(
    "uri",
    [
        "file://localhost/opt/app/ui/index.html",  # same file, other spelling: not the page
        "file:///opt/app/ui/./index.html",
        "file:///opt/app/ui/../ui/index.html",
        "file:///OPT/app/ui/index.html",
        "http://[::1",  # malformed: urlsplit raises ValueError
        "mailto:?subject=x",  # no address
        "https://exa\tmple.com/",
        "java\tscript:alert(1)",
        "blob:https://example.com/uuid",
        "ws://example.com/",
        "intent://example.com#Intent;end",
    ],
)
def test_lookalikes_and_malformed_uris_are_blocked(uri) -> None:
    assert links.decide(uri, INDEX) is Decision.BLOCK
    assert links.decide(uri, INDEX, new_window=True) is Decision.BLOCK


@pytest.mark.parametrize(
    "uri",
    ["HTTP://example.com", "https://user@example.com/", "https://例え.jp/", "MAILTO:a@b.c"],
)
def test_case_and_userinfo_still_launch(uri) -> None:
    assert links.decide(uri, INDEX) is Decision.LAUNCH


def test_uri_exactly_at_the_limit_is_accepted() -> None:
    base = "https://example.com/"
    uri = base + "a" * (links.MAX_URI_LENGTH - len(base))
    assert len(uri) == links.MAX_URI_LENGTH
    assert links.is_external(uri)
    assert not links.is_external(uri + "a")
