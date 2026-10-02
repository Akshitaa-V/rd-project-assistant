import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rdpa import tools  # noqa: E402
from rdpa.dashboard import build_dashboard  # noqa: E402
from rdpa.generate import generate  # noqa: E402
from rdpa.ingest import ingest  # noqa: E402
from rdpa.report import build_report  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def built():
    manifest = generate()
    load = ingest()
    tools.reset_cache()
    report = build_report()
    build_dashboard()
    os.environ.setdefault("RDPA_WEBHOOK_TOKEN", "test-token")
    return {"manifest": manifest, "load": load, "report": report}
