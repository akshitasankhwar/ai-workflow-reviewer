"""Command-line entry point.

Commands:
  analyze <bundle_dir> [--out F]   load, compile, resolve approvals, trace; print JSON
  review <bundle_dir> [--model fake|ollama|none] [--fake-script F] [--out report.json] [--disable CHECK]
  schemas [--out-dir D]            export JSON Schemas (default ./schemas)

Exit codes: analyze -> 1 if any blocking issue; review -> 0 only when status is PASS.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import load_config


def _emit(data: dict, out: str | None) -> None:
    text = json.dumps(data, indent=2, sort_keys=False, ensure_ascii=False)
    if out:
        Path(out).write_text(text + "\n", encoding="utf-8")
    else:
        sys.stdout.write(text + "\n")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="reviewer")
    p.add_argument("--config", default=None)
    sub = p.add_subparsers(dest="cmd", required=True)

    pa = sub.add_parser("analyze", help="compile a bundle and show the effective requirements")
    pa.add_argument("bundle")
    pa.add_argument("--out")

    pr = sub.add_parser("review", help="review a bundle and write a report")
    pr.add_argument("bundle")
    pr.add_argument("--model", choices=["none", "fake", "ollama"], default="none")
    pr.add_argument("--fake-script", default=None)
    pr.add_argument("--out")
    pr.add_argument("--disable", action="append", default=[],
                    help="disable a check by name (repeatable); a disabled required check -> INCOMPLETE")

    ps = sub.add_parser("schemas", help="export JSON Schemas for all contracts")
    ps.add_argument("--out-dir", default="schemas")

    args = p.parse_args(argv)
    cfg = load_config(args.config)

    if args.cmd == "analyze":
        from .pipeline import analysis_to_json, analyze
        a = analyze(args.bundle, cfg)
        _emit(analysis_to_json(a), args.out)
        return 1 if any(i.blocking for i in a.issues) else 0
    if args.cmd == "review":
        from .pipeline import review
        from .reporting.writer import human_summary, report_to_json
        rep = review(args.bundle, cfg, model=args.model, disable=tuple(args.disable),
                     fake_script=args.fake_script)
        _emit(report_to_json(rep), args.out)
        if args.out:
            sys.stderr.write(human_summary(rep) + "\n")
        return 0 if rep.status == "PASS" else 1
    if args.cmd == "schemas":
        from .contracts import export
        for path in export(args.out_dir):
            sys.stdout.write(f"{path}\n")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
