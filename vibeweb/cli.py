import argparse
import json
import glob
import sys
from pathlib import Path
from typing import Any, Dict

from vibeweb.server import run_server
from vibeweb.gallery import run_gallery
from vibeweb.ai import generate_spec
from vibeweb.spec import load_spec, validate_spec
from vibeweb.version import get_version


_SAMPLE = {
    "name": "Todo App",
    "spec_version": 1,
    "db": {
        "path": "todo.db",
        "models": [
            {
                "name": "Todo",
                "fields": {
                    "title": "text",
                    "done": "bool",
                    "created_at": "datetime"
                }
            }
        ]
    },
    "api": {"crud": ["Todo"]},
    "ui": {
        "admin": True,
        "admin_path": "/admin",
        "admin_auth": {
            "type": "basic",
            "username": "admin",
            "password": "change_me"
        },
        "pages": [
            {"path": "/", "model": "Todo", "title": "Todos"}
        ]
    }
}


def cmd_validate(args: argparse.Namespace) -> int:
    def _collect_paths(raw: str) -> list[Path]:
        p = Path(raw)
        if p.exists():
            if p.is_dir():
                return sorted(p.rglob("*.vweb.json"))
            return [p]

        # Allow shell-less glob usage: `vibeweb validate examples/**/*.vweb.json`
        if any(ch in raw for ch in ("*", "?", "[")):
            matches = [Path(m) for m in glob.glob(raw, recursive=True)]
            out: list[Path] = []
            for m in matches:
                if m.is_dir():
                    out.extend(sorted(m.rglob("*.vweb.json")))
                else:
                    out.append(m)
            return out
        return []

    files: list[Path] = []
    for raw in args.paths:
        files.extend(_collect_paths(raw))

    # Deduplicate while preserving stable order.
    seen: set[Path] = set()
    unique: list[Path] = []
    for f in files:
        rf = f.resolve()
        if rf in seen:
            continue
        seen.add(rf)
        unique.append(rf)

    if not unique:
        print("ERROR: No spec files found. Expected a .vweb.json file or a directory containing them.", file=sys.stderr)
        return 1

    errors: list[tuple[Path, Exception]] = []
    for f in unique:
        try:
            spec = load_spec(str(f))
            validate_spec(spec)
        except Exception as exc:  # noqa: BLE001
            errors.append((f, exc))

    if errors:
        for f, exc in errors:
            print(f"ERROR: {f}: {exc}", file=sys.stderr)
        return 1

    if len(unique) == 1:
        print("OK")
    else:
        print(f"OK ({len(unique)} files)")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    spec = load_spec(args.file)
    app = validate_spec(spec)
    run_server(app, host=args.host, port=args.port)
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    path = Path(args.file)
    if path.exists() and not args.force:
        raise SystemExit(f"File already exists: {path}")
    path.write_text(json.dumps(_SAMPLE, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(path))
    return 0


def cmd_ai(args: argparse.Namespace) -> int:
    if not args.prompt and not args.prompt_file:
        raise SystemExit("Provide --prompt or --prompt-file")
    prompt = args.prompt or Path(args.prompt_file).read_text(encoding="utf-8")
    spec = generate_spec(
        prompt,
        provider=args.provider,
        base_url=args.base_url,
        model=args.model,
        api_key=args.api_key,
        temperature=args.temperature,
    )
    spec_json = json.dumps(spec, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(spec_json, encoding="utf-8")
        print(str(Path(args.out)))
    else:
        print(spec_json)
    return 0


def cmd_gallery(args: argparse.Namespace) -> int:
    root = args.root or "examples"
    run_gallery(root=root, host=args.host, port=args.port)
    return 0


def cmd_fmt(args: argparse.Namespace) -> int:
    path = Path(args.file)
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw)
    formatted = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.check and formatted != raw:
        print(str(path))
        return 1
    if args.write:
        path.write_text(formatted, encoding="utf-8")
        print(str(path))
        return 0
    print(formatted, end="")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="vibeweb")
    parser.add_argument("--version", action="version", version=f"vibeweb {get_version()}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_validate = sub.add_parser("validate", help="Validate a VibeWeb spec")
    p_validate.add_argument("paths", nargs="+", help="Spec file(s), directory, or glob (e.g. examples/**/*.vweb.json)")
    p_validate.set_defaults(func=cmd_validate)

    p_run = sub.add_parser("run", help="Run a VibeWeb app")
    p_run.add_argument("file")
    p_run.add_argument("--host", default="127.0.0.1")
    p_run.add_argument("--port", type=int, default=8000)
    p_run.set_defaults(func=cmd_run)

    p_init = sub.add_parser("init", help="Create a sample spec JSON")
    p_init.add_argument("file", nargs="?", default="app.vweb.json")
    p_init.add_argument("--force", action="store_true")
    p_init.set_defaults(func=cmd_init)

    p_ai = sub.add_parser("ai", help="Generate a spec using an LLM")
    p_ai.add_argument("--prompt", help="Prompt text")
    p_ai.add_argument("--prompt-file", help="Prompt file path")
    p_ai.add_argument("--out", help="Output file path")
    p_ai.add_argument("--provider", default="openai", choices=["openai", "deepseek", "ollama"])
    p_ai.add_argument("--base-url", dest="base_url")
    p_ai.add_argument("--model")
    p_ai.add_argument("--api-key", dest="api_key")
    p_ai.add_argument("--temperature", type=float, default=0.2)
    p_ai.set_defaults(func=cmd_ai)

    p_gallery = sub.add_parser("gallery", help="Serve the examples homepage")
    p_gallery.add_argument("--root", help="Root directory (default: examples)")
    p_gallery.add_argument("--host", default="127.0.0.1")
    p_gallery.add_argument("--port", type=int, default=9000)
    p_gallery.set_defaults(func=cmd_gallery)

    p_fmt = sub.add_parser("fmt", help="Format a spec JSON file")
    p_fmt.add_argument("file")
    p_fmt.add_argument("--write", action="store_true", help="Write formatted JSON back to file")
    p_fmt.add_argument("--check", action="store_true", help="Exit non-zero if formatting would change the file")
    p_fmt.set_defaults(func=cmd_fmt)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
