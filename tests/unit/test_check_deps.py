"""scripts/check-deps.sh reports missing system packages with an apt command."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

TOOLS = ("python3", "Xvfb", "xvfb-run", "gjs", "node", "npm", "glib-compile-schemas")
SHELL_TOOLS = ("bash", "env")


def _fake_path(tmp_path: Path, omit: set[str]) -> str:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for tool in TOOLS + SHELL_TOOLS:
        if tool in omit:
            continue
        real = shutil.which(tool)
        if real is None:
            pytest.skip(f"{tool} not installed on this machine")
        (bindir / tool).symlink_to(real)
    return str(bindir)


def _run(repo_root: Path, path: str) -> subprocess.CompletedProcess[str]:
    script = repo_root / "scripts" / "check-deps.sh"
    return subprocess.run(
        [shutil.which("bash") or "/bin/bash", str(script)],
        env={**os.environ, "PATH": path},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_all_present(repo_root, tmp_path):
    result = _run(repo_root, _fake_path(tmp_path, set()))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "sudo apt install" not in result.stdout


def test_missing_xvfb_prints_apt_command(repo_root, tmp_path):
    result = _run(repo_root, _fake_path(tmp_path, {"Xvfb", "xvfb-run"}))
    assert result.returncode == 1
    assert "sudo apt install xvfb" in result.stdout


def test_missing_several_lists_each_package_once(repo_root, tmp_path):
    result = _run(repo_root, _fake_path(tmp_path, {"Xvfb", "xvfb-run", "gjs"}))
    assert result.returncode == 1
    line = next(ln for ln in result.stdout.splitlines() if ln.startswith("sudo apt install"))
    assert line.split()[3:] == ["xvfb", "gjs"]


@pytest.mark.parametrize(
    ("omit", "package"),
    [
        ({"node"}, "nodejs"),
        ({"npm"}, "npm"),
        ({"gjs"}, "gjs"),
        ({"glib-compile-schemas"}, "libglib2.0-bin"),
    ],
)
def test_missing_tool_maps_to_apt_package(repo_root, tmp_path, omit, package):
    result = _run(repo_root, _fake_path(tmp_path, omit))
    assert result.returncode == 1
    assert f"sudo apt install {package}" in result.stdout.splitlines()


def test_missing_python3_does_not_crash(repo_root, tmp_path):
    # Without python3 the gi/WebKit probes must be skipped, not fail with "command not found".
    result = _run(repo_root, _fake_path(tmp_path, {"python3"}))
    assert result.returncode == 1
    assert "sudo apt install python3" in result.stdout.splitlines()
    assert "command not found" not in result.stderr
