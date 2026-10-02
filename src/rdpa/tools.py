"""The tool layer shared by the MCP server, the agent and the HTTP API.

Every tool is read-only and returns plain JSON-serialisable data, so the same
function can be offered to an LLM, called from a workflow or used in a test.
"""
from __future__ import annotations

from contextlib import closing
from functools import lru_cache

from . import config, kpis
from .ingest import connect
from .knowledge import KnowledgeBase


@lru_cache(maxsize=1)
def _kb() -> KnowledgeBase:
    return KnowledgeBase(config.DOCS_DIR)


def reset_cache() -> None:
    _kb.cache_clear()


def _resolve(con, project: str | None) -> str | None:
    if not project:
        return None
    found = kpis.find_project(con, project)
    if not found:
        raise ValueError(f"Unknown project: {project!r}. Use an id like RD-101 or part of the name.")
    return found["project_id"]


def get_portfolio_status() -> dict:
    """Traffic-light status of every R&D project plus portfolio totals."""
    with closing(connect()) as con:
        health = kpis.project_health(con)
    return {
        "report_date": config.REPORT_DATE.isoformat(),
        "summary": kpis.portfolio_summary(health),
        "projects": [{k: r[k] for k in ("project_id", "name", "status", "reasons")} for r in health],
    }


def get_project_status(project: str) -> dict:
    """Schedule, budget burn and risk figures for one project (id or part of its name)."""
    with closing(connect()) as con:
        pid = _resolve(con, project)
        row = next(r for r in kpis.project_health(con) if r["project_id"] == pid)
        row["overdue_milestones"] = kpis.overdue_milestones(con, project_id=pid)
    return row


def list_overdue_milestones(project: str | None = None) -> list[dict]:
    """Milestones past their planned date and not completed, most overdue first."""
    with closing(connect()) as con:
        return kpis.overdue_milestones(con, project_id=_resolve(con, project))


def get_open_risks(project: str | None = None, min_score: int = 0) -> list[dict]:
    """Open risks scored probability x impact, highest first."""
    with closing(connect()) as con:
        return kpis.open_risks(con, min_score=min_score, project_id=_resolve(con, project))


def search_knowledge_base(query: str, k: int = 3) -> list[dict]:
    """Search meeting minutes, risk reviews and process documents; returns cited snippets."""
    return [hit.__dict__ for hit in _kb().search(query, k=k)]


TOOLS = {
    "get_portfolio_status": get_portfolio_status,
    "get_project_status": get_project_status,
    "list_overdue_milestones": list_overdue_milestones,
    "get_open_risks": get_open_risks,
    "search_knowledge_base": search_knowledge_base,
}

# JSON schemas in the OpenAI tool format (accepted by LiteLLM for any provider).
TOOL_SCHEMAS = [
    {"type": "function", "function": {
        "name": "get_portfolio_status", "description": get_portfolio_status.__doc__,
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "get_project_status", "description": get_project_status.__doc__,
        "parameters": {"type": "object", "properties": {"project": {"type": "string"}},
                       "required": ["project"]}}},
    {"type": "function", "function": {
        "name": "list_overdue_milestones", "description": list_overdue_milestones.__doc__,
        "parameters": {"type": "object", "properties": {"project": {"type": "string"}}}}},
    {"type": "function", "function": {
        "name": "get_open_risks", "description": get_open_risks.__doc__,
        "parameters": {"type": "object", "properties": {
            "project": {"type": "string"}, "min_score": {"type": "integer", "minimum": 0}}}}},
    {"type": "function", "function": {
        "name": "search_knowledge_base", "description": search_knowledge_base.__doc__,
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}},
                       "required": ["query"]}}},
]


def call(name: str, arguments: dict) -> object:
    """Run a tool by name; errors come back as data so an agent can recover."""
    if name not in TOOLS:
        return {"error": f"unknown tool {name}"}
    try:
        return TOOLS[name](**arguments)
    except (ValueError, TypeError) as exc:
        return {"error": str(exc)}
