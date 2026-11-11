import re

import app

SEMVER = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)


def test_version_is_semver_string():
    assert isinstance(app.__version__, str)
    assert SEMVER.match(app.__version__)


def test_version_matches_pyproject(repo_root):
    import tomllib

    data = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["version"] == app.__version__
