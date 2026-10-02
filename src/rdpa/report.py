"""Weekly status report and BI exports, generated in one step.

Produces the Markdown/HTML report the PMO would otherwise assemble by hand,
plus flat CSV extracts that KNIME, Power BI or Tableau can read directly.
"""
from __future__ import annotations

import csv
import html
import json
from contextlib import closing
from datetime import datetime
from pathlib import Path

from . import config, kpis
from .ingest import connect

ICON = {"red": "RED", "amber": "AMBER", "green": "GREEN"}


def build_report(out_dir: Path = config.OUT_DIR) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    with closing(connect()) as con:
        health = kpis.project_health(con)
        overdue = kpis.overdue_milestones(con)
        all_risks = kpis.open_risks(con)
        high = [r for r in all_risks if r["score"] >= kpis.HIGH_RISK]
        weekly = kpis.weekly_hours(con)
        quarantine = [dict(r) for r in con.execute(
            "SELECT source, reason, COUNT(*) AS n FROM quarantine GROUP BY source, reason ORDER BY source")]
    summary = kpis.portfolio_summary(health)

    md = _markdown(health, overdue, high, quarantine, summary)
    (out_dir / "weekly_status_report.md").write_text(md, encoding="utf-8")
    (out_dir / "weekly_status_report.html").write_text(_html(md), encoding="utf-8")

    exports = out_dir / "exports"
    exports.mkdir(exist_ok=True)
    flat = [{k: (", ".join(v) if isinstance(v, list) else v) for k, v in r.items()} for r in health]
    _csv(exports / "project_health.csv", flat)
    _csv(exports / "overdue_milestones.csv", overdue)
    _csv(exports / "open_risks.csv", all_risks)
    _csv(exports / "weekly_hours.csv", weekly)

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "report_date": config.REPORT_DATE.isoformat(),
        "summary": summary,
        "red_projects": [f"{r['project_id']} {r['name']}" for r in health if r["status"] == "red"],
        "report_path": str(out_dir / "weekly_status_report.html"),
    }
    (out_dir / "report_summary.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload | {"markdown": md}


def _csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def _markdown(health, overdue, high, quarantine, s) -> str:
    c = s["status_counts"]
    lines = [
        f"# R&D Portfolio - Weekly Status Report ({config.REPORT_DATE.isoformat()})", "",
        f"**{s['projects']} projects:** {c['red']} red, {c['amber']} amber, {c['green']} green. "
        f"Milestones on time: {s['on_time_rate']:.0%} of {s['milestones_done']} completed. "
        f"Overdue milestones: {s['overdue_milestones']}. High risks: {s['high_risks']}.", "",
        "## Projects", "",
        "| Status | Project | Lead | Overdue | Avg slip (days) | Budget used | Timeline | Burn index | Reasons |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    order = {"red": 0, "amber": 1, "green": 2}
    for r in sorted(health, key=lambda r: (order[r["status"]], r["project_id"])):
        lines.append(
            f"| {ICON[r['status']]} | {r['project_id']} {r['name']} | {r['owner']} | {r['overdue']} | "
            f"{r['avg_slip_days']} | {r['budget_used_share']:.0%} | {r['elapsed_share']:.0%} | "
            f"{r['burn_index']} | {'; '.join(r['reasons']) or '-'} |")
    lines += ["", "## Overdue milestones", ""]
    lines += [f"- {m['project_id']} {m['milestone']}: {m['days_overdue']} days overdue (owner {m['owner']})"
              for m in overdue] or ["- none"]
    lines += ["", "## High risks (score 15 or more)", ""]
    lines += [f"- {r['project_id']} {r['title']}: score {r['score']} (owner {r['owner']})" for r in high] or ["- none"]
    lines += ["", "## Data quality", "",
              "Rows rejected during import and kept in quarantine for the data owner:", ""]
    lines += [f"- {q['source']}: {q['n']} x {q['reason']}" for q in quarantine] or ["- none"]
    return "\n".join(lines) + "\n"


def _html(md: str) -> str:
    """Minimal Markdown-to-HTML for the report (headings, tables, bullets, bold)."""
    out, in_table, in_list = [], False, False
    for line in md.splitlines():
        esc = html.escape(line)
        esc = esc.replace("**", "<b>", 1).replace("**", "</b>", 1) if "**" in esc else esc
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if set("".join(cells)) <= {"-"}:
                continue
            if not in_table:
                out.append("<table>")
                in_table = True
                out.append("<tr>" + "".join(f"<th>{html.escape(c)}</th>" for c in cells) + "</tr>")
            else:
                cls = cells[0].lower()
                out.append(f'<tr class="{cls}">' + "".join(f"<td>{html.escape(c)}</td>" for c in cells) + "</tr>")
            continue
        if in_table:
            out.append("</table>")
            in_table = False
        if line.startswith("- "):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{esc[2:]}</li>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        if line.startswith("## "):
            out.append(f"<h2>{esc[3:]}</h2>")
        elif line.startswith("# "):
            out.append(f"<h1>{esc[2:]}</h1>")
        elif line:
            out.append(f"<p>{esc}</p>")
    if in_table:
        out.append("</table>")
    if in_list:
        out.append("</ul>")
    style = ("body{font-family:Arial,sans-serif;max-width:1100px;margin:24px auto;color:#222}"
             "table{border-collapse:collapse;width:100%;font-size:13px}"
             "th,td{border:1px solid #ccc;padding:4px 6px;text-align:left}th{background:#f2f2f2}"
             "tr.red td:first-child{background:#f4c7c3}tr.amber td:first-child{background:#fce8b2}"
             "tr.green td:first-child{background:#b7e1cd}")
    return f"<!doctype html><html><head><meta charset='utf-8'><title>Weekly Status Report</title>" \
           f"<style>{style}</style></head><body>{''.join(out)}</body></html>"
