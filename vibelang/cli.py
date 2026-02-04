import argparse
import json
from pathlib import Path
from typing import Any, Dict

from vibelang.compiler import compile_ir_to_source, run_file
from vibelang.ir import load_program, validate_ir


def _load_inputs(path: str | None) -> Dict[str, Any] | None:
    if not path:
        return None
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Inputs JSON must be an object")
    return data


def cmd_validate(args: argparse.Namespace) -> int:
    ir = load_program(args.file)
    validate_ir(ir)
    print("OK")
    return 0


def cmd_compile(args: argparse.Namespace) -> int:
    ir = load_program(args.file)
    source = compile_ir_to_source(ir)
    if args.out:
        Path(args.out).write_text(source, encoding="utf-8")
    else:
        print(source, end="")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    inputs = _load_inputs(args.inputs)
    result, report, _source, _ir = run_file(args.file, inputs=inputs)
    if args.json:
        print(report.to_json())
    else:
        print(result)
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    inputs = _load_inputs(args.inputs)
    _result, report, _source, _ir = run_file(args.file, inputs=inputs)
    print(report.to_json())
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="vibelang")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_validate = sub.add_parser("validate", help="Validate a VibeLang IR file")
    p_validate.add_argument("file")
    p_validate.set_defaults(func=cmd_validate)

    p_compile = sub.add_parser("compile", help="Compile IR to Python source")
    p_compile.add_argument("file")
    p_compile.add_argument("--out")
    p_compile.set_defaults(func=cmd_compile)

    p_run = sub.add_parser("run", help="Run a VibeLang IR file")
    p_run.add_argument("file")
    p_run.add_argument("--inputs", help="JSON file with input overrides")
    p_run.add_argument("--json", action="store_true", help="Print execution report JSON")
    p_run.set_defaults(func=cmd_run)

    p_report = sub.add_parser("report", help="Run and print execution report JSON")
    p_report.add_argument("file")
    p_report.add_argument("--inputs", help="JSON file with input overrides")
    p_report.set_defaults(func=cmd_report)

    p_parse = sub.add_parser("parse", help="Parse .vbl to JSON IR")
    p_parse.add_argument("file")
    p_parse.set_defaults(func=cmd_parse)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
def cmd_parse(args: argparse.Namespace) -> int:
    ir = load_program(args.file)
    print(json.dumps(ir, ensure_ascii=False, indent=2))
    return 0
