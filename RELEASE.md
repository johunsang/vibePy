# Release Process

This repo uses Semantic Versioning (`MAJOR.MINOR.PATCH`) and keeps the version as a single source of truth in `pyproject.toml`.

## Checklist (Recommended)

1. Update version
- Edit `pyproject.toml` `[project].version` (example: `0.2.1`).

2. Update changelog
- Add a new entry in `CHANGELOG.md`:
  - `## [0.2.1] - YYYY-MM-DD`
  - List `Added/Changed/Fixed/Security` items.

3. Run local checks
```bash
python3 -m unittest discover -s tests -p "test_*.py"
python3 scripts/check_version.py
python3 -m vibeweb validate examples/todo/todo.vweb.json
python3 -m vibeweb validate examples/crm/crm.advanced.vweb.json
```

4. Commit
```bash
git add -A
git commit -m "Release v0.2.1"
```

5. Tag
```bash
git tag v0.2.1
```

6. Push branch and tag
```bash
git push origin HEAD
git push origin v0.2.1
```

## Why Tags Matter

The gallery ZIP generator pins the generated app to a deterministic `vibepy` git ref.
When the current version is a clean SemVer like `0.2.0`, ZIPs prefer `@v0.2.0`.

That means:
- If the tag exists, ZIP installs are reproducible.
- If the tag does not exist, ZIP installs will fail.

