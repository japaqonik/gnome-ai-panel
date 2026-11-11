import json

import pytest

from app import debug


def test_debug_enabled_only_for_1() -> None:
    assert debug.debug_enabled({"AI_PANEL_DEBUG": "1"})
    for value in ("", "0", "true", "yes"):
        assert not debug.debug_enabled({"AI_PANEL_DEBUG": value})
    assert not debug.debug_enabled({})


def test_dump_path_follows_xdg_state_home(isolated_env) -> None:
    assert debug.dump_path() == isolated_env["XDG_STATE_HOME"] / "gnome-ai-panel" / (
        "debug-dump.json"
    )


def test_build_dump_keeps_known_page_keys_only() -> None:
    state = {
        "screen": "chat",
        "agent": "a",
        "badge": "tools",
        "messages": [],
        "permission_dialog": {"open": False, "title": ""},
        "banner": None,
        "theme": "dark",
        "busy": False,
        "visible": True,  # not the page's business
        "pinned": True,
        "uri": "file:///evil",
        "extra": 1,
    }
    dump = debug.build_dump(state, visible=False, uri="file:///x/index.html")
    assert dump["visible"] is False
    assert dump["pinned"] is False
    assert dump["uri"] == "file:///x/index.html"
    assert "extra" not in dump
    assert dump["theme"] == "dark"


def test_write_dump_is_private_and_atomic(isolated_env) -> None:
    path = debug.write_dump({"messages": ["ż"]})
    assert path == debug.dump_path()
    assert path.stat().st_mode & 0o777 == 0o600
    assert json.loads(path.read_text(encoding="utf-8")) == {"messages": ["ż"]}
    first_inode = path.stat().st_ino
    debug.write_dump({"messages": []})
    assert path.stat().st_ino != first_inode  # replaced, never rewritten in place
    assert [p.name for p in path.parent.iterdir()] == ["debug-dump.json"]


def test_write_dump_rejects_nan_and_leaves_no_temp_file(tmp_path) -> None:
    target = tmp_path / "d.json"
    with pytest.raises(ValueError):
        debug.write_dump({"x": float("nan")}, target)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("text", ["</script><b>", "a\u2028b", "'\"\\", "ż & <"])
def test_js_string_cannot_break_out(text) -> None:
    literal = debug.js_string(text)
    assert "<" not in literal and ">" not in literal and "&" not in literal
    assert "\u2028" not in literal
    assert json.loads(literal) == text


def test_scripts_embed_the_value_as_a_literal() -> None:
    script = debug.send_script("x'); alert(1); ('")
    assert "alert(1); ('\"" in script  # inside the JSON string literal
    assert "requestSubmit" in script
    click = debug.click_script("a[data-external]")
    assert '"a[data-external]"' in click
