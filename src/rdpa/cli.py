"""Command line entry point.

    python -m rdpa build            generate data, validate + load, build report and dashboard
    python -m rdpa ask "question"   ask the agent
    python -m rdpa eval             run the retrieval and routing evaluations
"""
from __future__ import annotations

import argparse
import json
import time

from . import config, tools
from .agent import ask
from .dashboard import build_dashboard
from .generate import generate
from .ingest import ingest
from .report import build_report


def cmd_build(_args) -> None:
    t0 = time.perf_counter()
    manifest = generate()
    load = ingest()
    tools.reset_cache()
    report = build_report()
    dash = build_dashboard()
    secs = time.perf_counter() - t0
    print(json.dumps({"rows": manifest["rows"], "documents": manifest["documents"], "load": load,
                      "summary": report["summary"], "red_projects": report["red_projects"],
                      "dashboard": str(dash), "seconds": round(secs, 2)}, indent=2))


def cmd_ask(args) -> None:
    result = ask(args.question)
    print(result.answer)
    if args.trace:
        print(json.dumps({"mode": result.mode, "trace": result.trace}, indent=2, default=str))


def cmd_eval(_args) -> None:
    from .evaluate import run_all
    print(json.dumps(run_all(), indent=2))


def main() -> None:
    p = argparse.ArgumentParser(prog="rdpa", description="R&D Project Assistant")
    sub = p.add_subparsers(required=True)
    sub.add_parser("build").set_defaults(fn=cmd_build)
    a = sub.add_parser("ask")
    a.add_argument("question")
    a.add_argument("--trace", action="store_true")
    a.set_defaults(fn=cmd_ask)
    sub.add_parser("eval").set_defaults(fn=cmd_eval)
    args = p.parse_args()
    config.ensure_dirs()
    args.fn(args)


if __name__ == "__main__":
    main()
