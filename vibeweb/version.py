from __future__ import annotations

import importlib.metadata
import re
from pathlib import Path

_DISTRIBUTION_NAME = "vibepy"

try:
    import tomllib  # Python 3.11+
except Exception:  # pragma: no cover
    tomllib = None  # type: ignore[assignment]


def _find_repo_root(start: Path) -> Path | None:
    for parent in [start, *start.parents]:
        if (parent / "pyproject.toml").is_file():
            return parent
    return None


def _read_pyproject_version(pyproject: Path) -> str | None:
    # Prefer a real TOML parser (tomllib) to avoid fragile regex parsing.
    if tomllib is None:
        return _read_pyproject_version_regex(pyproject)
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except Exception:
        return None
    project = data.get("project")
    if isinstance(project, dict):
        version = project.get("version")
        if isinstance(version, str) and version.strip():
            return version.strip()
    return None


# Note: keep these regexes simple and readable. This file is used both in
# installed mode and repo-checkout mode, so it should be boring and reliable.
_SECTION_RE = re.compile(r"^\s*\[(?P<section>[^\]]+)\]\s*$")
_VERSION_RE = re.compile(r"^\s*version\s*=\s*([\"'])(?P<version>[^\"']+)\1\s*$")


def _read_pyproject_version_regex(pyproject: Path) -> str | None:
    """
    Fallback version reader for Python 3.10 where tomllib is not available.

    This is intentionally narrow: we only look for `[project]` then `version = "..."`.
    """
    try:
        text = pyproject.read_text(encoding="utf-8")
    except Exception:
        return None

    in_project = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        sec = _SECTION_RE.match(line)
        if sec:
            in_project = sec.group("section").strip() == "project"
            continue
        if not in_project:
            continue
        m = _VERSION_RE.match(raw_line)
        if m:
            version = m.group("version").strip()
            return version if version else None
    return None


def get_version() -> str:
    """
    Best-effort version lookup.

    1) When installed, prefer the installed distribution metadata.
    2) When running from a repo checkout, read [project].version from pyproject.toml.
    """
    try:
        return importlib.metadata.version(_DISTRIBUTION_NAME)
    except Exception:
        root = _find_repo_root(Path(__file__).resolve())
        if root:
            version = _read_pyproject_version(root / "pyproject.toml")
            if version:
                return version
        return "0.0.0+unknown"
