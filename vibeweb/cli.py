import argparse
import json
from pathlib import Path
from typing import Any, Dict

from vibeweb.server import run_server
from vibeweb.gallery import run_gallery
from vibeweb.ai import generate_spec
from vibeweb.spec import load_spec, validate_spec


_SAMPLE = {
    "name": "Todo App",
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
            "password": "admin"
        },
        "pages": [
            {"path": "/", "model": "Todo", "title": "Todos"}
        ]
    }
}


def cmd_validate(args: argparse.Namespace) -> int:
    spec = load_spec(args.file)
    validate_spec(spec)
    print("OK")
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="vibeweb")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_validate = sub.add_parser("validate", help="Validate a VibeWeb spec")
    p_validate.add_argument("file")
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

    p_ai = sub.add_parser("ai", help="Generate a spec using a local LLM")
    p_ai.add_argument("--prompt", help="Prompt text")
    p_ai.add_argument("--prompt-file", help="Prompt file path")
    p_ai.add_argument("--out", help="Output file path")
    p_ai.add_argument("--provider", default="openai", choices=["openai", "ollama"])
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

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
