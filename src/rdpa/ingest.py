"""Validate the CSV exports and load them into SQLite.

Rows that fail a rule are not dropped silently: they go to a quarantine
table together with the rule they broke, so the data owner can fix them.
"""
from __future__ import annotations

import csv
import json
import sqlite3
from collections import Counter
from datetime import date
from pathlib import Path

from . import config

SCHEMA = """
DROP TABLE IF EXISTS projects;
DROP TABLE IF EXISTS milestones;
DROP TABLE IF EXISTS risks;
DROP TABLE IF EXISTS timesheets;
DROP TABLE IF EXISTS quarantine;
CREATE TABLE projects (
    project_id TEXT PRIMARY KEY, name TEXT NOT NULL, department TEXT NOT NULL,
    owner TEXT NOT NULL, start_date TEXT NOT NULL, planned_end TEXT NOT NULL,
    budget_hours REAL NOT NULL CHECK (budget_hours > 0));
CREATE TABLE milestones (
    milestone_id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(project_id),
    name TEXT NOT NULL, owner TEXT, planned_date TEXT NOT NULL, actual_date TEXT);
CREATE TABLE risks (
    risk_id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(project_id),
    title TEXT NOT NULL, probability INTEGER NOT NULL CHECK (probability BETWEEN 1 AND 5),
    impact INTEGER NOT NULL CHECK (impact BETWEEN 1 AND 5), status TEXT NOT NULL, owner TEXT NOT NULL);
CREATE TABLE timesheets (
    week_start TEXT NOT NULL, project_id TEXT NOT NULL REFERENCES projects(project_id),
    employee TEXT NOT NULL, hours REAL NOT NULL CHECK (hours >= 0),
    PRIMARY KEY (week_start, project_id, employee));
CREATE TABLE quarantine (source TEXT NOT NULL, row_json TEXT NOT NULL, reason TEXT NOT NULL);
"""


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _is_date(value: str, optional: bool = False) -> bool:
    if value == "" and optional:
        return True
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False


def _int_in(value: str, lo: int, hi: int) -> bool:
    try:
        return lo <= int(value) <= hi
    except ValueError:
        return False


def validate_milestones(rows, project_ids):
    good, bad, seen = [], [], set()
    for r in rows:
        key = tuple(r.values())
        if not (_is_date(r["planned_date"]) and _is_date(r["actual_date"], optional=True)):
            bad.append((r, "invalid_date"))
        elif r["project_id"] not in project_ids:
            bad.append((r, "unknown_project"))
        elif key in seen:
            bad.append((r, "duplicate"))
        else:
            seen.add(key)
            good.append(r)
    return good, bad


def validate_risks(rows, project_ids):
    good, bad, seen = [], [], set()
    for r in rows:
        key = tuple(r.values())
        if not (_int_in(r["probability"], 1, 5) and _int_in(r["impact"], 1, 5)):
            bad.append((r, "score_out_of_range"))
        elif not r["owner"].strip():
            bad.append((r, "missing_owner"))
        elif r["project_id"] not in project_ids:
            bad.append((r, "unknown_project"))
        elif key in seen:
            bad.append((r, "duplicate"))
        else:
            seen.add(key)
            good.append(r)
    return good, bad


def validate_timesheets(rows, project_ids):
    good, bad, seen = [], [], set()
    for r in rows:
        key = tuple(r.values())
        try:
            hours = float(r["hours"])
        except ValueError:
            hours = -1.0
        if hours < 0:
            bad.append((r, "negative_hours"))
        elif not _is_date(r["week_start"]):
            bad.append((r, "invalid_date"))
        elif r["project_id"] not in project_ids:
            bad.append((r, "unknown_project"))
        elif key in seen:
            bad.append((r, "duplicate"))
        else:
            seen.add(key)
            good.append(r)
    return good, bad


def ingest(db_path: Path = config.DB_PATH, raw_dir: Path = config.RAW_DIR) -> dict:
    """Load all exports. Returns counts of loaded and quarantined rows per rule."""
    con = sqlite3.connect(db_path)
    con.executescript(SCHEMA)

    projects = _read(raw_dir / "projects.csv")
    con.executemany("INSERT INTO projects VALUES (:project_id,:name,:department,:owner,"
                    ":start_date,:planned_end,:budget_hours)", projects)
    ids = {p["project_id"] for p in projects}

    summary: dict[str, dict] = {}
    for source, validator, sql in (
        ("milestones", validate_milestones,
         "INSERT INTO milestones VALUES (:milestone_id,:project_id,:name,:owner,:planned_date,"
         "NULLIF(:actual_date,''))"),
        ("risks", validate_risks,
         "INSERT INTO risks VALUES (:risk_id,:project_id,:title,:probability,:impact,:status,:owner)"),
        ("timesheets", validate_timesheets,
         "INSERT INTO timesheets VALUES (:week_start,:project_id,:employee,:hours)"),
    ):
        good, bad = validator(_read(raw_dir / f"{source}.csv"), ids)
        con.executemany(sql, good)
        con.executemany("INSERT INTO quarantine VALUES (?,?,?)",
                        [(source, json.dumps(r, ensure_ascii=False), reason) for r, reason in bad])
        summary[source] = {"loaded": len(good), "quarantined": dict(Counter(reason for _, reason in bad))}
    summary["projects"] = {"loaded": len(projects), "quarantined": {}}
    con.commit()
    con.close()
    return summary


def connect(db_path: Path = config.DB_PATH) -> sqlite3.Connection:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    return con
