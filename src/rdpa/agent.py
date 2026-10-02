"""A tool-calling agent that answers project questions with the shared tools.

Two modes:
  * LLM mode (RDPA_MODEL set, e.g. "gpt-4o-mini" or "ollama/qwen2.5"): the model
    picks tools through function calling via LiteLLM, sees each result and
    answers, with a step limit so a confused model cannot loop forever.
  * Offline mode (no model configured): a deterministic router picks the tool
    from the question. It keeps the assistant usable without an API key and is
    what the tests and the routing evaluation run against.
Every step is recorded in a trace so it is clear which tool produced which fact.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

from . import tools

SYSTEM_PROMPT = (
    "You are an assistant for an R&D project management office. Answer only from tool "
    "results. Use project tools for status, schedule, budget and risk questions and the "
    "knowledge base for decisions, meeting outcomes and process rules. Cite project ids "
    "and document ids. If the tools do not contain the answer, say so."
)
MAX_STEPS = 5


@dataclass
class AgentResult:
    answer: str
    trace: list[dict] = field(default_factory=list)
    mode: str = "offline"


# ---------------------------------------------------------------- offline mode
PROJECT_ID = re.compile(r"\bRD-\d{3}\b", re.I)


def route(question: str) -> tuple[str, dict]:
    """Pick one tool and its arguments for a question (offline mode)."""
    q = question.lower()
    project = None
    m = PROJECT_ID.search(question)
    if m:
        project = m.group(0).upper()
    else:
        from .ingest import connect
        from contextlib import closing
        with closing(connect()) as con:
            for row in con.execute("SELECT project_id, name FROM projects"):
                name = row["name"].lower()
                # match the distinctive part of a name: first two words are enough
                if " ".join(name.split()[:2]) in q:
                    project = row["project_id"]
                    break

    if re.search(r"\b(decid|decision|why|minutes|review said|agreed|mitigat|policy|process|"
                 r"how do i|how to|rule|guideline|book|request)", q):
        return "search_knowledge_base", {"query": question}
    if re.search(r"\b(overdue|late|behind|delayed|missed)\b", q):
        return "list_overdue_milestones", ({"project": project} if project else {})
    if re.search(r"\brisks?\b", q):
        args: dict = {"project": project} if project else {}
        if re.search(r"\b(high|critical|top)\b", q):
            args["min_score"] = 15
        return "get_open_risks", args
    if project:
        return "get_project_status", {"project": project}
    if re.search(r"\b(portfolio|all projects|which projects|red|amber|green|overview)\b", q):
        return "get_portfolio_status", {}
    return "search_knowledge_base", {"query": question}


def _format(tool: str, result) -> str:
    if isinstance(result, dict) and "error" in result:
        return f"I could not answer that: {result['error']}"
    if tool == "get_portfolio_status":
        s = result["summary"]
        flagged = [f"{p['project_id']} {p['name']} ({p['status']}: {', '.join(p['reasons'])})"
                   for p in result["projects"] if p["status"] != "green"]
        return (f"{s['projects']} projects: {s['status_counts']['red']} red, "
                f"{s['status_counts']['amber']} amber, {s['status_counts']['green']} green. "
                + ("Needs attention: " + "; ".join(flagged) if flagged else ""))
    if tool == "get_project_status":
        r = result
        return (f"{r['project_id']} {r['name']} is {r['status']}. {r['done']} milestones done, "
                f"{r['overdue']} overdue, average slip {r['avg_slip_days']} days; "
                f"{r['budget_used_share']:.0%} of budget used at {r['elapsed_share']:.0%} of the "
                f"timeline (burn index {r['burn_index']}); highest open risk score {r['max_risk_score']}.")
    if tool == "list_overdue_milestones":
        if not result:
            return "No overdue milestones."
        return "Overdue: " + "; ".join(
            f"{m['project_id']} {m['milestone']} ({m['days_overdue']} days, owner {m['owner']})"
            for m in result[:8])
    if tool == "get_open_risks":
        if not result:
            return "No open risks match."
        return "Open risks: " + "; ".join(
            f"{r['project_id']} {r['title']} (score {r['score']}, owner {r['owner']})" for r in result[:6])
    if tool == "search_knowledge_base":
        if not result:
            return "The knowledge base has nothing on that."
        top = result[0]
        return f"{top['snippet']} [source: {top['doc_id']}]"
    return json.dumps(result)


def _run_offline(question: str) -> AgentResult:
    tool, args = route(question)
    result = tools.call(tool, args)
    return AgentResult(_format(tool, result), [{"tool": tool, "args": args, "result": result}])


# -------------------------------------------------------------------- LLM mode
def _run_llm(question: str, model: str) -> AgentResult:
    import litellm  # optional dependency

    messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": question}]
    trace: list[dict] = []
    for _ in range(MAX_STEPS):
        resp = litellm.completion(model=model, messages=messages, tools=tools.TOOL_SCHEMAS, timeout=60)
        msg = resp.choices[0].message
        calls = getattr(msg, "tool_calls", None) or []
        if not calls:
            return AgentResult(msg.content or "", trace, mode=f"llm:{model}")
        messages.append(msg.model_dump() if hasattr(msg, "model_dump") else dict(msg))
        for c in calls:
            try:
                args = json.loads(c.function.arguments or "{}")
            except json.JSONDecodeError:
                args, result = {}, {"error": "arguments were not valid JSON"}
            else:
                result = tools.call(c.function.name, args)
            trace.append({"tool": c.function.name, "args": args, "result": result})
            messages.append({"role": "tool", "tool_call_id": c.id,
                             "content": json.dumps(result, default=str)[:6000]})
    return AgentResult("Stopped after the step limit without a final answer.", trace, mode=f"llm:{model}")


def ask(question: str, model: str | None = None) -> AgentResult:
    model = model or os.environ.get("RDPA_MODEL")
    if model:
        try:
            return _run_llm(question, model)
        except Exception as exc:  # network, auth or provider errors: fall back, but say so
            result = _run_offline(question)
            result.mode = f"offline (LLM failed: {type(exc).__name__})"
            return result
    return _run_offline(question)
