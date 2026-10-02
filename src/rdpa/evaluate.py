"""Evaluations: knowledge base retrieval quality and agent tool routing."""
from __future__ import annotations

import json
import time

from . import config, tools
from .agent import route

EVAL_DIR = config.ROOT / "eval"


def retrieval_eval() -> dict:
    cases = json.loads((EVAL_DIR / "kb_queries.json").read_text(encoding="utf-8"))
    hit1 = hit3 = 0
    misses = []
    t0 = time.perf_counter()
    for c in cases:
        ids = [h["doc_id"] for h in tools.search_knowledge_base(c["q"], k=3)]
        hit1 += bool(ids) and ids[0] == c["doc"]
        hit3 += c["doc"] in ids
        if not ids or ids[0] != c["doc"]:
            misses.append({"query": c["q"], "expected": c["doc"], "got": ids})
    ms = (time.perf_counter() - t0) * 1000 / len(cases)
    return {"cases": len(cases), "hit_at_1": hit1, "hit_at_3": hit3,
            "avg_query_ms": round(ms, 2), "misses": misses}


def routing_eval() -> dict:
    cases = json.loads((EVAL_DIR / "routing.json").read_text(encoding="utf-8"))
    wrong = [{"q": c["q"], "expected": c["tool"], "got": route(c["q"])[0]}
             for c in cases if route(c["q"])[0] != c["tool"]]
    return {"cases": len(cases), "correct": len(cases) - len(wrong), "wrong": wrong}


def run_all() -> dict:
    return {"retrieval": retrieval_eval(), "routing": routing_eval()}
