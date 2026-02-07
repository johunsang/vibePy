# Changelog

All notable changes to this project will be documented in this file.

The format is based on *Keep a Changelog* and this project adheres to *Semantic Versioning*.

## [Unreleased]

### Documentation
- README: clarified GLM-4.7-Flash-first AI generator usage and added doc index links.

### UI
- Gallery homepage: Natural Language Builder copy now reflects an OpenAI-compatible endpoint (GLM-4.7-Flash recommended).
- Gallery homepage: `/generate` failures no longer dump huge HTML responses into the status line.

## [0.2.0] - 2026-02-07

### Added
- VibeWeb `spec_version: 1` with an action system (`http`, `llm`, `db`, `value`, `flow`).
- Hook system (`api.hooks`) with `when`, `when_changed`, optional `writeback`, and sync/async modes.
- Condition DSL for safe branching (`$and/$or/$not/$eq/$gt/...`) used by hooks and flow steps.
- Flow actions with step-level `when`, `retries`, `timeout_s`, and `parallel` execution groups.
- Spec-driven UI theming (`ui.theme`) with:
  - `css_urls`: external CSS links
  - `tailwind_config`: Tailwind config override (merged with defaults)
  - `classes`: class overrides for any theme key
- Admin list-view UI options per page:
  - `default_query`, `default_sort`, `default_dir`, `default_filters`
  - `visible_fields`, `hidden_fields`
- Advanced CRM example spec: `examples/crm/crm.advanced.vweb.json`.

### Changed
- Gallery upload parsing no longer uses `cgi` (removed in Python 3.13+).
- ZIP generator produces a one-command runnable app:
  - auto-creates `.venv`
  - pins `vibepy` dependency to a deterministic git ref (prefers `v{version}`)
  - marks `run.sh` and `run.command` as executable in the ZIP
- Admin UI theme usage is now consistent across public pages and admin pages.
- `vibeweb validate` accepts a spec file, a directory (recursively validates `*.vweb.json`), or a glob.
- CI validates all example specs via `python -m vibeweb validate examples`.

### Security
- Outbound HTTP/LLM actions are restricted by host allowlist (`VIBEWEB_OUTBOUND_ALLOW_HOSTS`).
- CSP is kept strict and only relaxed for the explicit hosts in `ui.theme.css_urls`.
