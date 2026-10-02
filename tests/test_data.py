import sqlite3
from contextlib import closing

from rdpa import config, kpis
from rdpa.generate import generate
from rdpa.ingest import connect, validate_milestones, validate_risks, validate_timesheets


def test_every_injected_error_is_quarantined_exactly(built):
    injected = built["manifest"]["injected_errors"]
    for source, expected in injected.items():
        assert built["load"][source]["quarantined"] == expected, source


def test_quarantine_rows_keep_the_reason():
    with closing(connect()) as con:
        reasons = {r["reason"] for r in con.execute("SELECT reason FROM quarantine")}
    assert {"duplicate", "invalid_date", "unknown_project", "score_out_of_range",
            "missing_owner", "negative_hours"} <= reasons


def test_generation_is_reproducible(built):
    assert generate()["rows"] == built["manifest"]["rows"]


def test_validators_on_handcrafted_rows():
    ids = {"RD-101"}
    good, bad = validate_milestones([
        {"milestone_id": "M1", "project_id": "RD-101", "name": "x", "owner": "a", "planned_date": "2026-01-01", "actual_date": ""},
        {"milestone_id": "M2", "project_id": "RD-101", "name": "x", "owner": "a", "planned_date": "01.01.2026", "actual_date": ""},
        {"milestone_id": "M3", "project_id": "RD-999", "name": "x", "owner": "a", "planned_date": "2026-01-01", "actual_date": ""},
    ], ids)
    assert len(good) == 1 and [r for _, r in bad] == ["invalid_date", "unknown_project"]
    _, bad = validate_risks([{"risk_id": "R", "project_id": "RD-101", "title": "t", "probability": "6",
                              "impact": "2", "status": "open", "owner": "a"}], ids)
    assert bad[0][1] == "score_out_of_range"
    _, bad = validate_timesheets([{"week_start": "2026-01-05", "project_id": "RD-101", "employee": "e",
                                   "hours": "abc"}], ids)
    assert bad[0][1] == "negative_hours"


def test_database_constraints_hold():
    with closing(connect()) as con:
        assert con.execute("SELECT COUNT(*) FROM risks WHERE probability NOT BETWEEN 1 AND 5").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM timesheets WHERE hours < 0").fetchone()[0] == 0
        orphan = con.execute("SELECT COUNT(*) FROM milestones WHERE project_id NOT IN "
                             "(SELECT project_id FROM projects)").fetchone()[0]
        assert orphan == 0


def test_status_rules_are_applied():
    with closing(connect()) as con:
        health = kpis.project_health(con)
    assert len(health) == 12
    for r in health:
        high = r["max_risk_score"] >= kpis.HIGH_RISK
        if r["overdue"] >= 2 or (r["overdue"] and high):
            assert r["status"] == "red"
        elif r["overdue"] or high or r["burn_index"] > kpis.BURN_LIMIT:
            assert r["status"] == "amber"
        else:
            assert r["status"] == "green" and not r["reasons"]


def test_burn_index_matches_raw_sql():
    con = sqlite3.connect(config.DB_PATH)
    hours, budget = con.execute("SELECT SUM(hours), (SELECT budget_hours FROM projects WHERE project_id='RD-105') "
                                "FROM timesheets WHERE project_id='RD-105'").fetchone()
    con.close()
    with closing(connect()) as c2:
        row = next(r for r in kpis.project_health(c2) if r["project_id"] == "RD-105")
    assert abs(row["budget_used_share"] - hours / budget) < 0.001


def test_overdue_milestones_are_really_overdue():
    with closing(connect()) as con:
        rows = kpis.overdue_milestones(con)
    assert rows and all(r["days_overdue"] > 0 for r in rows)
    assert rows == sorted(rows, key=lambda r: -r["days_overdue"])


def test_rolling_average_window():
    with closing(connect()) as con:
        weekly = [w for w in kpis.weekly_hours(con) if w["department"] == "Power"]
    last4 = [w["hours"] for w in weekly[-4:]]
    assert abs(weekly[-1]["rolling_4w"] - round(sum(last4) / 4, 1)) < 0.11
