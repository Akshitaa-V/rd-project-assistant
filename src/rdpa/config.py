"""Shared paths and settings."""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

ROOT = Path(os.environ.get("RDPA_HOME", Path(__file__).resolve().parents[2]))
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"          # CSV exports as they would come from a PM tool
DOCS_DIR = DATA_DIR / "docs"        # project documents for the knowledge base
DB_PATH = DATA_DIR / "portfolio.db"
OUT_DIR = ROOT / "out"

# Fixed reporting date so every run (and every test) gives the same numbers.
REPORT_DATE = date.fromisoformat(os.environ.get("RDPA_REPORT_DATE", "2026-09-30"))
SEED = int(os.environ.get("RDPA_SEED", "7"))


def ensure_dirs() -> None:
    for d in (RAW_DIR, DOCS_DIR, OUT_DIR):
        d.mkdir(parents=True, exist_ok=True)
