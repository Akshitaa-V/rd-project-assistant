"""Portfolio KPIs computed in SQL: schedule, budget burn, risks and a traffic-light status.

Status rules (also written down in the process documents):
  red   - two or more overdue milestones, or one overdue milestone together with a high risk
  amber - one overdue milestone, a burn index above 1.15, or an open risk scored 15 or more
  green - everything else
"""
from __future__ import annotations

import sqlite3
from datetime import date

from . import config

HIGH_RISK = 15
BURN_LIMIT = 1.15

HEALTH_SQL = """
WITH ms AS (
    SELECT project_id,
           SUM(actual_date IS NULL AND planned_date < :today)                AS overdue,
           SUM(actual_date IS NOT NULL)                                      AS done,
           SUM(actual_date IS NOT NULL AND actual_date <= planned_date)      AS on_time,
           AVG(CASE WHEN actual_date IS NOT NULL
                    THEN julianday(actual_date) - julianday(planned_date) END) AS avg_slip_days
    FROM milestones GROUP BY project_id
), hrs AS (
    SELECT project_id, SUM(hours) AS hours_used FROM timesheets GROUP BY project_id
), rk AS (
    SELECT project_id, MAX(probability * impact) AS max_risk_score,
           SUM(probability * impact >= :high) AS high_risks
    FROM risks WHERE status = 'open' GROUP BY project_id
)
SELECT p.project_id, p.name, p.department, p.owner, p.start_date, p.planned_end, p.budget_hours,
       COALESCE(ms.overdue, 0) AS overdue, COALESCE(ms.done, 0) AS done,
       COALESCE(ms.on_time, 0) AS on_time, ROUND(COALESCE(ms.avg_slip_days, 0), 1) AS avg_slip_days,
       COALESCE(hrs.hours_used, 0) AS hours_used,
       MIN(1.0, MAX(0.01, (julianday(:today) - julianday(p.start_date))
                        / (julianday(p.planned_end) - julianday(p.start_date)))) AS elapsed_share,
       COALESCE(rk.max_risk_score, 0) AS max_risk_score, COALESCE(rk.high_risks, 0) AS high_risks
FROM projects p
LEFT JOIN ms  ON ms.project_id  = p.project_id
LEFT JOIN hrs ON hrs.project_id = p.project_id
LEFT JOIN rk  ON rk.project_id  = p.project_id
ORDER BY p.project_id
"""


def project_health(con: sqlite3.Connection, today: date = config.REPORT_DATE) -> list[dict]:
    rows = [dict(r) for r in con.execute(HEALTH_SQL, {"today": today.isoformat(), "high": HIGH_RISK})]
    for r in rows:
        r["budget_used_share"] = round(r["hours_used"] / r["budget_hours"], 3)
        r["burn_index"] = round(r["budget_used_share"] / r["elapsed_share"], 2)
        r["elapsed_share"] = round(r["elapsed_share"], 3)
        reasons = []
        if r["overdue"]:
            reasons.append(f"{r['overdue']} overdue milestone(s)")
        if r["burn_index"] > BURN_LIMIT:
            reasons.append(f"burn index {r['burn_index']}")
        if r["max_risk_score"] >= HIGH_RISK:
            reasons.append(f"high risk (score {r['max_risk_score']})")
        if r["overdue"] >= 2 or (r["overdue"] >= 1 and r["max_risk_score"] >= HIGH_RISK):
            r["status"] = "red"
        elif reasons:
            r["status"] = "amber"
        else:
            r["status"] = "green"
        r["reasons"] = reasons
    return rows


def overdue_milestones(con: sqlite3.Connection, today: date = config.REPORT_DATE,
                       project_id: str | None = None) -> list[dict]:
    sql = """
    SELECT m.milestone_id, m.project_id, p.name AS project, m.name AS milestone, m.owner,
           m.planned_date, CAST(julianday(:today) - julianday(m.planned_date) AS INTEGER) AS days_overdue
    FROM milestones m JOIN projects p USING (project_id)
    WHERE m.actual_date IS NULL AND m.planned_date < :today
      AND (:pid IS NULL OR m.project_id = :pid)
    ORDER BY days_overdue DESC"""
    return [dict(r) for r in con.execute(sql, {"today": today.isoformat(), "pid": project_id})]


def open_risks(con: sqlite3.Connection, min_score: int = 0, project_id: str | None = None) -> list[dict]:
    sql = """
    SELECT r.risk_id, r.project_id, p.name AS project, r.title, r.probability, r.impact,
           r.probability * r.impact AS score, r.owner,
           RANK() OVER (PARTITION BY r.project_id ORDER BY r.probability * r.impact DESC) AS rank_in_project
    FROM risks r JOIN projects p USING (project_id)
    WHERE r.status = 'open' AND r.probability * r.impact >= :min
      AND (:pid IS NULL OR r.project_id = :pid)
    ORDER BY score DESC, r.risk_id"""
    return [dict(r) for r in con.execute(sql, {"min": min_score, "pid": project_id})]


def weekly_hours(con: sqlite3.Connection) -> list[dict]:
    """Hours per department and week with a rolling 4-week average (window function)."""
    sql = """
    WITH w AS (
        SELECT p.department, t.week_start, SUM(t.hours) AS hours
        FROM timesheets t JOIN projects p USING (project_id)
        GROUP BY p.department, t.week_start)
    SELECT department, week_start, hours,
           ROUND(AVG(hours) OVER (PARTITION BY department ORDER BY week_start
                                  ROWS BETWEEN 3 PRECEDING AND CURRENT ROW), 1) AS rolling_4w
    FROM w ORDER BY department, week_start"""
    return [dict(r) for r in con.execute(sql)]


def portfolio_summary(health: list[dict]) -> dict:
    done = sum(r["done"] for r in health)
    on_time = sum(r["on_time"] for r in health)
    return {
        "projects": len(health),
        "status_counts": {s: sum(r["status"] == s for r in health) for s in ("red", "amber", "green")},
        "milestones_done": done,
        "on_time_rate": round(on_time / done, 3) if done else None,
        "overdue_milestones": sum(r["overdue"] for r in health),
        "high_risks": sum(r["high_risks"] for r in health),
    }


def find_project(con: sqlite3.Connection, text: str) -> dict | None:
    """Resolve a project from an id (RD-101) or a part of its name."""
    t = text.strip().lower()
    for r in con.execute("SELECT project_id, name FROM projects"):
        if t == r["project_id"].lower() or (len(t) >= 3 and t in r["name"].lower()):
            return dict(r)
    return None
