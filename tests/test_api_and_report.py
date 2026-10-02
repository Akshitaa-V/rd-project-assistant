import csv
import json
from pathlib import Path

from fastapi.testclient import TestClient

from rdpa import config
from rdpa.api import app

client = TestClient(app)
ROOT = Path(__file__).resolve().parents[1]


def test_health_and_portfolio():
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/portfolio").json()["summary"]["projects"] == 12


def test_webhook_rejects_missing_or_wrong_token():
    assert client.post("/webhooks/weekly-report").status_code == 401
    assert client.post("/webhooks/weekly-report", headers={"X-Webhook-Token": "nope"}).status_code == 401


def test_webhook_without_server_token_is_503(monkeypatch):
    monkeypatch.delenv("RDPA_WEBHOOK_TOKEN")
    assert client.post("/webhooks/weekly-report", headers={"X-Webhook-Token": "x"}).status_code == 503


def test_webhook_builds_report(monkeypatch):
    monkeypatch.setenv("RDPA_WEBHOOK_TOKEN", "s3cret")
    r = client.post("/webhooks/weekly-report", headers={"X-Webhook-Token": "s3cret"})
    assert r.status_code == 200
    body = r.json()
    assert body["has_red_projects"] == bool(body["red_projects"])
    assert body["markdown"].startswith("# R&D Portfolio")
    assert (config.OUT_DIR / "dashboard.html").exists()


def test_ask_endpoint_validates_and_answers():
    assert client.post("/ask", json={"question": "?"}).status_code == 422
    r = client.post("/ask", json={"question": "Which milestones are overdue?"}).json()
    assert r["answer"].startswith("Overdue") and r["trace"]


def test_report_and_bi_exports_written(built):
    md = (config.OUT_DIR / "weekly_status_report.md").read_text(encoding="utf-8")
    assert "## Data quality" in md and "| RED |" in md
    with (config.OUT_DIR / "exports" / "project_health.csv").open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 12 and {"status", "burn_index"} <= set(rows[0])
    for name in ("overdue_milestones", "open_risks", "weekly_hours"):
        assert (config.OUT_DIR / "exports" / f"{name}.csv").stat().st_size > 0


def test_n8n_workflow_is_wired_to_the_api():
    wf = json.loads((ROOT / "workflows" / "n8n_weekly_status_report.json").read_text(encoding="utf-8"))
    nodes = {n["name"]: n for n in wf["nodes"]}
    http = next(n for n in wf["nodes"] if n["type"] == "n8n-nodes-base.httpRequest")
    assert http["parameters"]["url"].endswith("/webhooks/weekly-report")
    # every connection points at a node that exists
    for src, outs in wf["connections"].items():
        assert src in nodes
        for branch in outs["main"]:
            for link in branch:
                assert link["node"] in nodes
    # every node except the trigger is reachable
    targets = {l["node"] for o in wf["connections"].values() for b in o["main"] for l in b}
    assert set(nodes) - targets == {next(n for n in nodes if "Schedule" in n)}
