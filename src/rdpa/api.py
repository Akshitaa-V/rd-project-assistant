"""HTTP API used by workflow tools (n8n, Power Automate, cron) and for quick questions.

    uvicorn rdpa.api:app --port 8000
Set RDPA_WEBHOOK_TOKEN; workflow calls must send it in the X-Webhook-Token header.
"""
from __future__ import annotations

import hmac
import os
import time

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from . import agent, tools
from .dashboard import build_dashboard
from .report import build_report

app = FastAPI(title="R&D Project Assistant", version="1.0.0")


class Question(BaseModel):
    question: str = Field(min_length=3, max_length=500)


def _check_token(token: str | None) -> None:
    expected = os.environ.get("RDPA_WEBHOOK_TOKEN")
    if not expected:
        raise HTTPException(503, "RDPA_WEBHOOK_TOKEN is not configured on the server")
    if not token or not hmac.compare_digest(token, expected):
        raise HTTPException(401, "invalid webhook token")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/portfolio")
def portfolio() -> dict:
    return tools.get_portfolio_status()


@app.post("/ask")
def ask(q: Question) -> dict:
    result = agent.ask(q.question)
    return {"answer": result.answer, "mode": result.mode, "trace": result.trace}


@app.post("/webhooks/weekly-report")
def weekly_report(x_webhook_token: str | None = Header(default=None)) -> dict:
    """Called on a schedule by a workflow: rebuilds report and dashboard, returns what to send."""
    _check_token(x_webhook_token)
    start = time.perf_counter()
    payload = build_report()
    build_dashboard()
    payload["build_seconds"] = round(time.perf_counter() - start, 2)
    payload["has_red_projects"] = bool(payload["red_projects"])
    return payload
