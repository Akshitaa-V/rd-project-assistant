"""Static KPI dashboard (single HTML file with embedded SVG charts)."""
from __future__ import annotations

import io
from contextlib import closing
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from . import config, kpis  # noqa: E402
from .ingest import connect  # noqa: E402

STATUS_COLOR = {"red": "#c0392b", "amber": "#d68910", "green": "#1e8449"}
DEPT_COLOR = {"Power": "#2f6db5", "Sensors": "#8e44ad", "MCU": "#16a085", "Security": "#7f8c8d"}


def _svg(fig) -> str:
    buf = io.StringIO()
    fig.savefig(buf, format="svg", bbox_inches="tight")
    plt.close(fig)
    svg = buf.getvalue()
    return svg[svg.index("<svg"):]


def _style(ax):
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", color="#e5e5e5", linewidth=0.8)
    ax.set_axisbelow(True)


def build_dashboard(out_dir: Path = config.OUT_DIR) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    with closing(connect()) as con:
        health = kpis.project_health(con)
        weekly = kpis.weekly_hours(con)
    s = kpis.portfolio_summary(health)
    ids = [r["project_id"] for r in health]
    colors = [STATUS_COLOR[r["status"]] for r in health]

    fig, ax = plt.subplots(figsize=(8, 3))
    ax.bar(ids, [r["burn_index"] for r in health], color=colors)
    ax.axhline(kpis.BURN_LIMIT, color="#444", linestyle="--", linewidth=1)
    ax.text(-0.4, kpis.BURN_LIMIT + 0.03, "amber limit 1.15", ha="left", fontsize=8)
    ax.set_ylabel("Burn index")
    ax.set_title("Budget burn vs. timeline (bar colour = project status)", fontsize=10, loc="left")
    ax.tick_params(axis="x", labelrotation=45, labelsize=8)
    _style(ax)
    burn_svg = _svg(fig)

    fig, ax = plt.subplots(figsize=(8, 3))
    ax.bar(ids, [r["avg_slip_days"] for r in health], color=colors)
    ax.axhline(0, color="#444", linewidth=0.8)
    ax.set_ylabel("Average slip (days)")
    ax.set_title("Average milestone slip per project", fontsize=10, loc="left")
    ax.tick_params(axis="x", labelrotation=45, labelsize=8)
    _style(ax)
    slip_svg = _svg(fig)

    fig, ax = plt.subplots(figsize=(8, 3))
    for dept in sorted({w["department"] for w in weekly}):
        pts = [w for w in weekly if w["department"] == dept][-26:]
        ax.plot([p["week_start"] for p in pts], [p["rolling_4w"] for p in pts],
                label=dept, color=DEPT_COLOR.get(dept, "#333"), linewidth=1.8)
    ax.set_ylabel("Hours / week (4-week avg)")
    ax.set_title("Engineering hours by department, last 26 weeks", fontsize=10, loc="left")
    ax.set_xticks(ax.get_xticks()[::4])
    ax.tick_params(axis="x", labelrotation=45, labelsize=8)
    ax.legend(frameon=False, fontsize=8, ncol=4)
    _style(ax)
    hours_svg = _svg(fig)

    c = s["status_counts"]
    tiles = "".join(
        f"<div class='tile'><div class='v'>{v}</div><div class='l'>{label}</div></div>" for v, label in [
            (s["projects"], "projects"), (c["red"], "red"), (c["amber"], "amber"), (c["green"], "green"),
            (f"{s['on_time_rate']:.0%}", "milestones on time"), (s["overdue_milestones"], "overdue milestones"),
            (s["high_risks"], "high risks")])
    page = f"""<!doctype html><html><head><meta charset="utf-8"><title>R&amp;D Portfolio Dashboard</title>
<style>body{{font-family:Arial,sans-serif;max-width:900px;margin:24px auto;color:#222}}
.tiles{{display:flex;flex-wrap:wrap;gap:10px;margin:12px 0 20px}}
.tile{{border:1px solid #ddd;border-radius:6px;padding:8px 14px;min-width:90px}}
.v{{font-size:22px;font-weight:bold}}.l{{font-size:12px;color:#555}} svg{{max-width:100%;height:auto}}</style>
</head><body><h1>R&amp;D Portfolio Dashboard</h1><p>Report date {config.REPORT_DATE.isoformat()}</p>
<div class="tiles">{tiles}</div>{burn_svg}{slip_svg}{hours_svg}</body></html>"""
    path = out_dir / "dashboard.html"
    path.write_text(page, encoding="utf-8")
    return path
