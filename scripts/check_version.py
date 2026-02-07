#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path


SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:[-+][0-9A-Za-z.-]+)?$")


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _read_pyproject_version(pyproject: Path) -> str:
    text = _read_text(pyproject)

    # Use tomllib when available (3.11+), else a narrow regex.
    try:
        import tomllib  # type: ignore

        data = tomllib.loads(text)
        project = data.get("project")
        if not isinstance(project, dict):
            raise ValueError("Missing [project] table")
        version = project.get("version")
        if not isinstance(version, str) or not version.strip():
            raise ValueError("Missing [project].version")
        return version.strip()
    except Exception:
        in_project = False
        section_re = re.compile(r"^\s*\[(?P<section>[^\]]+)\]\s*$")
        version_re = re.compile(r"^\s*version\s*=\s*([\"'])(?P<version>[^\"']+)\1\s*$")
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            sec = section_re.match(line)
            if sec:
                in_project = sec.group("section").strip() == "project"
                continue
            if not in_project:
                continue
            m = version_re.match(raw_line)
            if m:
                v = m.group("version").strip()
                if v:
                    return v
        raise ValueError("Could not read version from pyproject.toml")


def _parse_changelog_versions(changelog_text: str) -> list[str]:
    # Matches: ## [0.2.0] - 2026-02-07
    # or:      ## [Unreleased]
    heading_re = re.compile(r"^##\s+\[(?P<name>[^\]]+)\](?:\s+-\s+(?P<date>\d{4}-\d{2}-\d{2}))?\s*$")
    versions: list[str] = []
    for line in changelog_text.splitlines():
        m = heading_re.match(line.strip())
        if not m:
            continue
        versions.append(m.group("name").strip())
    return versions


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    pyproject = root / "pyproject.toml"
    changelog = root / "CHANGELOG.md"

    errors: list[str] = []

    if not pyproject.is_file():
        errors.append("Missing pyproject.toml")
        version = ""
    else:
        try:
            version = _read_pyproject_version(pyproject)
        except Exception as exc:
            version = ""
            errors.append(f"Failed to read version from pyproject.toml: {exc}")

    if version and not SEMVER_RE.match(version):
        errors.append(
            f"pyproject.toml version is not valid SemVer: {version!r} (expected MAJOR.MINOR.PATCH[...])"
        )

    if not changelog.is_file():
        errors.append("Missing CHANGELOG.md")
        changelog_text = ""
    else:
        changelog_text = _read_text(changelog)

    if changelog_text:
        versions = _parse_changelog_versions(changelog_text)
        if "Unreleased" not in versions:
            errors.append("CHANGELOG.md must include '## [Unreleased]'")
        if version and version not in versions:
            errors.append(f"CHANGELOG.md must include an entry for version {version!r}")

        # Encourage ordering: Unreleased first, then latest release.
        if version and "Unreleased" in versions and version in versions:
            if versions.index(version) < versions.index("Unreleased"):
                errors.append("CHANGELOG.md: version entry must come after [Unreleased]")

    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        return 1

    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
