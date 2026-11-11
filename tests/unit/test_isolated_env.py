import os
from pathlib import Path


def test_isolated_env_redirects_home_and_xdg(isolated_env, tmp_path):
    for var in ("HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
        value = Path(os.environ[var])
        assert value == isolated_env[var]
        assert value.is_dir()
        assert value.is_relative_to(tmp_path)
    assert Path.home() == isolated_env["HOME"]


def test_isolated_env_clears_app_variables(monkeypatch, request):
    monkeypatch.setenv("AI_PANEL_CONFIG", "/somewhere/config.toml")
    request.getfixturevalue("isolated_env")
    assert "AI_PANEL_CONFIG" not in os.environ
