"""Generate a reproducible, synthetic R&D project portfolio.

Writes CSV exports in the shape a project management tool would produce
(projects, milestones, risks, timesheets) plus the project documents that
feed the knowledge base. A known set of data errors is injected on purpose
and recorded in a manifest, so the validation step can be checked exactly.
All names and numbers are invented.
"""
from __future__ import annotations

import csv
import json
import random
from datetime import date, timedelta
from pathlib import Path

from . import config

PROJECTS = [
    # id, name, department, owner, start, planned_end, budget_hours, slip_profile
    ("RD-101", "SiC Power Module Gen3", "Power", "Lena Hofmann", "2025-10-06", "2026-12-18", 5200, "late"),
    ("RD-102", "Radar Sensor Front-End 77 GHz", "Sensors", "Jonas Weber", "2025-11-03", "2027-02-26", 6100, "ok"),
    ("RD-103", "Automotive MCU Bootloader 2.1", "MCU", "Mira Schneider", "2026-01-12", "2026-11-27", 2400, "slight"),
    ("RD-104", "Secure Element Firmware Update", "Security", "Tobias Klein", "2025-09-01", "2026-10-30", 3100, "late"),
    ("RD-105", "GaN Charger Reference Design", "Power", "Sara Becker", "2026-02-02", "2027-01-29", 2800, "ok"),
    ("RD-106", "Battery Management IC Calibration", "Power", "David Wolf", "2025-12-01", "2026-12-11", 3600, "slight"),
    ("RD-107", "Pressure Sensor Self-Test", "Sensors", "Anna Richter", "2026-03-02", "2027-03-26", 2200, "ok"),
    ("RD-108", "MCU Functional Safety Library", "MCU", "Felix Braun", "2025-08-04", "2026-11-13", 4800, "late"),
    ("RD-109", "Post-Quantum Crypto Evaluation", "Security", "Clara Neumann", "2026-04-06", "2027-04-30", 1900, "ok"),
    ("RD-110", "Motor Control Kit Software", "MCU", "Paul Zimmermann", "2026-01-05", "2026-12-04", 2600, "slight"),
    ("RD-111", "Current Sensor Packaging Study", "Sensors", "Julia Krüger", "2025-11-17", "2026-10-23", 1700, "late"),
    ("RD-112", "Wafer Test Time Reduction", "Power", "Max Hartmann", "2026-02-16", "2026-12-18", 2100, "ok"),
]

MILESTONES = ["Concept Freeze", "Design Review", "Prototype Ready",
              "Validation Complete", "Qualification", "Release"]

# Delay in days for completed milestones, and chance a past milestone is still open.
SLIP = {"ok": ((-3, 4), 0.0), "slight": ((2, 12), 0.15), "late": ((10, 35), 0.45)}

# Per project: design review finding + decision, top risk + mitigation.
FACTS = {
    "RD-101": ("the thermal simulation showed a hotspot of 148 °C at the die attach",
               "switch from wire bonds to copper clip bonding and rerun the simulation",
               "lead time for SiC substrates has grown to 26 weeks",
               "qualify a second substrate supplier and place a buffer order"),
    "RD-102": ("antenna-to-antenna coupling measured at -32 dB, above the -40 dB target",
               "add a ground via fence between the transmit and receive channels",
               "the 77 GHz test chamber is booked out until December",
               "share chamber time with the sensors lab and move tests to night shifts"),
    "RD-103": ("boot time is 41 ms against a 30 ms target",
               "move the CRC image check to the hardware crypto accelerator",
               "the new flash driver is not yet released by the platform team",
               "agree an interim driver drop and freeze its interface"),
    "RD-104": ("the security review found the update could be rolled back to an older image",
               "add a monotonic version counter that is checked before every install",
               "external penetration test slot may slip into the next quarter",
               "book a second test lab and prepare the test scope early"),
    "RD-105": ("efficiency reached 94.1 % at full load, short of the 95 % goal",
               "replace the wound transformer with a planar transformer",
               "planar transformer samples have an 8 week lead time",
               "order samples from two vendors in parallel"),
    "RD-106": ("calibration drifts by 3 mV across the temperature range",
               "use two-point calibration at -40 °C and 125 °C",
               "the climate chamber needed for calibration is shared with three projects",
               "batch calibration runs and publish a weekly chamber plan"),
    "RD-107": ("the self-test raised false alarms on 0.8 % of parts",
               "widen the threshold window and add a debounce of three samples",
               "field data for the new threshold is limited to one customer",
               "request anonymised field returns from a second customer"),
    "RD-108": ("the static analysis reported 27 open MISRA deviations",
               "plan a dedicated sprint to close the deviations before the safety assessment",
               "the external functional safety assessor is only available in November",
               "deliver the safety case documents two weeks before the assessment"),
    "RD-109": ("key generation for the lattice scheme takes 12 ms on the target core",
               "evaluate the hardware acceleration option before choosing the scheme",
               "standards for post-quantum algorithms may still change",
               "keep the crypto layer swappable behind one interface"),
    "RD-110": ("the field-oriented control loop shows 4 µs of jitter",
               "move the PWM update into DMA so the interrupt load drops",
               "the motor test bench is unreliable above 6000 rpm",
               "repair the bench encoder and add a speed limit in the test scripts"),
    "RD-111": ("parts showed delamination after 500 thermal cycles",
               "start qualification of an alternative mold compound",
               "a new mold compound needs full requalification",
               "run the requalification in parallel with the current build"),
    "RD-112": ("test time is 2.4 s per die on the current program",
               "test four sites in parallel on the existing tester",
               "parallel testing may raise correlation issues between sites",
               "run a site-to-site correlation study on 5 wafers first"),
}

PROCESS_DOCS = {
    "PROC-01": ("Stage gate review process",
                "Every R&D project passes five stage gates. A gate review needs the updated "
                "schedule, the risk register and the budget burn. The gate keeper is the head "
                "of the department. A project that misses two milestones in a row is moved to "
                "status red and must present a recovery plan at the next gate."),
    "PROC-02": ("Timesheet policy",
                "Engineers book their hours per project every Friday. Hours are booked in half "
                "hour steps. Corrections for past weeks are allowed until the 5th of the next "
                "month. Overtime above 10 hours per week needs approval from the line manager."),
    "PROC-03": ("How to request lab and chamber time",
                "Climate chambers, test benches and the RF chamber are booked through the lab "
                "planning sheet. Requests must be made at least two weeks ahead. Night shift "
                "slots can be requested for long-running tests. Cancellations free the slot for "
                "the waiting list automatically."),
    "PROC-04": ("Risk scoring guideline",
                "Risks are scored by probability and impact, each from 1 to 5. The risk score is "
                "probability times impact. A score of 15 or more is high and must be reported in "
                "the weekly status report with a mitigation and an owner. Risks are reviewed "
                "every two weeks."),
    "PROC-05": ("Weekly status report",
                "The weekly status report is sent every Monday at 8 am. It lists every project "
                "with a traffic-light status, overdue milestones, high risks and budget burn. "
                "Project leads review red projects in the Tuesday steering meeting."),
    "PROC-06": ("Budget burn and hours tracking",
                "Budget is planned in engineering hours. The burn index compares the share of "
                "hours used with the share of time elapsed. A burn index above 1.15 means the "
                "project is spending faster than planned and is flagged amber."),
}

ENGINEERS = ["A. Fischer", "B. Wagner", "C. Meyer", "D. Schulz", "E. Koch", "F. Bauer",
             "G. Lange", "H. Vogel", "I. Frank", "J. Berger", "K. Roth", "L. Peters"]


def _d(s: str) -> date:
    return date.fromisoformat(s)


def _write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def generate(seed: int = config.SEED, today: date = config.REPORT_DATE) -> dict:
    rng = random.Random(seed)
    config.ensure_dirs()
    injected: dict[str, dict[str, int]] = {"milestones": {}, "risks": {}, "timesheets": {}}

    # ---- projects -------------------------------------------------------
    proj_rows = [[pid, name, dept, owner, start, end, budget]
                 for pid, name, dept, owner, start, end, budget, _ in PROJECTS]
    _write_csv(config.RAW_DIR / "projects.csv",
               ["project_id", "name", "department", "owner", "start_date", "planned_end", "budget_hours"],
               proj_rows)

    # ---- milestones -----------------------------------------------------
    ms_rows: list[list] = []
    n = 0
    for pid, _, _, owner, start, end, _, profile in PROJECTS:
        s, e = _d(start), _d(end)
        span = (e - s).days
        (lo, hi), open_chance = SLIP[profile]
        blocked = False  # stage gates are sequential: once one is open, later ones cannot close
        for i, mname in enumerate(MILESTONES):
            n += 1
            planned = s + timedelta(days=round(span * (i + 1) / len(MILESTONES)))
            actual = ""
            if planned <= today and not blocked:
                # older gates were closed long ago (with slip); only recent ones can still be open
                recent = (today - planned).days <= 120
                if recent and rng.random() < open_chance:
                    blocked = True
                else:
                    done = planned + timedelta(days=rng.randint(lo, hi))
                    actual = (done if done <= today else today).isoformat()
            ms_rows.append([f"MS-{n:03d}", pid, mname, owner, planned.isoformat(), actual])

    # injected milestone errors
    for row in rng.sample(ms_rows, 3):
        ms_rows.append(list(row))                      # exact duplicates
    injected["milestones"]["duplicate"] = 3
    ms_rows.append(["MS-901", "RD-199", "Design Review", "Unknown", "2026-05-04", ""])
    ms_rows.append(["MS-902", "RD-198", "Release", "Unknown", "2026-08-10", ""])
    injected["milestones"]["unknown_project"] = 2
    ms_rows.append(["MS-903", "RD-105", "Prototype Ready", "Sara Becker", "2026-13-01", ""])
    ms_rows.append(["MS-904", "RD-107", "Design Review", "Anna Richter", "31.06.2026", ""])
    injected["milestones"]["invalid_date"] = 2
    rng.shuffle(ms_rows)
    _write_csv(config.RAW_DIR / "milestones.csv",
               ["milestone_id", "project_id", "name", "owner", "planned_date", "actual_date"], ms_rows)

    # ---- risks ----------------------------------------------------------
    risk_rows: list[list] = []
    n = 0
    for pid, _, _, owner, *_rest in PROJECTS:
        profile = _rest[-1]
        top = FACTS[pid][2]
        n += 1
        p, i = (4, 4) if profile == "late" else (3, 3) if profile == "slight" else (2, 3)
        risk_rows.append([f"RK-{n:03d}", pid, top[0].upper() + top[1:], p, i, "open", owner])
        for _ in range(rng.randint(1, 3)):
            n += 1
            risk_rows.append([f"RK-{n:03d}", pid, rng.choice([
                "Key engineer on parental leave in Q4", "Tool license renewal pending",
                "Customer specification still changing", "Test equipment calibration overdue",
                "Dependency on shared platform release"]),
                rng.randint(1, 4), rng.randint(1, 4), rng.choice(["open", "open", "closed"]), owner])
    risk_rows.append(["RK-901", "RD-102", "Supplier insolvency", 7, 3, "open", "Jonas Weber"])
    risk_rows.append(["RK-902", "RD-110", "Simulation model outdated", 2, 0, "open", "Paul Zimmermann"])
    injected["risks"]["score_out_of_range"] = 2
    risk_rows.append(["RK-903", "RD-104", "Certificate authority change", 3, 4, "open", ""])
    risk_rows.append(["RK-904", "RD-111", "Sample shortage", 2, 2, "open", ""])
    injected["risks"]["missing_owner"] = 2
    _write_csv(config.RAW_DIR / "risks.csv",
               ["risk_id", "project_id", "title", "probability", "impact", "status", "owner"], risk_rows)

    # ---- timesheets -----------------------------------------------------
    burn_factor = {"ok": 0.95, "slight": 1.08, "late": 1.25}
    ts_rows: list[list] = []
    monday = today - timedelta(days=today.weekday())
    for pid, _, _, _, start, end, budget, profile in PROJECTS:
        s, e = _d(start), _d(end)
        weekly = budget / max(1, (e - s).days / 7) * burn_factor[profile]
        team = rng.sample(ENGINEERS, 3)
        week = s - timedelta(days=s.weekday())
        while week <= monday:
            for eng in team:
                hours = max(0.0, round(weekly / 3 * rng.uniform(0.7, 1.3) * 2) / 2)
                ts_rows.append([week.isoformat(), pid, eng, hours])
            week += timedelta(days=7)
    for row in rng.sample(ts_rows, 3):
        ts_rows.append([row[0], row[1], row[2], -row[3] if row[3] else -4.0])
    injected["timesheets"]["negative_hours"] = 3
    for row in rng.sample(ts_rows[:-3], 2):
        ts_rows.append(list(row))
    injected["timesheets"]["duplicate"] = 2
    rng.shuffle(ts_rows)
    _write_csv(config.RAW_DIR / "timesheets.csv", ["week_start", "project_id", "employee", "hours"], ts_rows)

    # ---- documents ------------------------------------------------------
    for old in config.DOCS_DIR.glob("*.md"):
        old.unlink()
    docs = 0
    for pid, name, dept, owner, start, end, budget, _ in PROJECTS:
        finding, decision, risk, mitigation = FACTS[pid]
        _doc(f"{pid}-kickoff", f"{name}: kickoff notes",
             f"Project {pid} ({name}) in the {dept} department starts on {start} with {owner} "
             f"as project lead. The planned end date is {end} and the budget is {budget} "
             f"engineering hours. Milestones follow the standard stage gates from concept freeze "
             f"to release.")
        _doc(f"{pid}-design-review", f"{name}: design review minutes",
             f"In the design review for {name}, {finding}. Decision: {decision}. "
             f"Action owner is {owner}; the result is reviewed at the next gate.")
        _doc(f"{pid}-risk-review", f"{name}: risk review",
             f"Top risk for {name}: {risk}. Mitigation agreed with {owner}: {mitigation}. "
             f"The risk is tracked in the risk register and reviewed every two weeks.")
        docs += 3
    for did, (title, body) in PROCESS_DOCS.items():
        _doc(did, title, body)
        docs += 1

    manifest = {"seed": seed, "report_date": today.isoformat(), "injected_errors": injected,
                "rows": {"projects": len(proj_rows), "milestones": len(ms_rows),
                         "risks": len(risk_rows), "timesheets": len(ts_rows)},
                "documents": docs}
    (config.DATA_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def _doc(doc_id: str, title: str, body: str) -> None:
    (config.DOCS_DIR / f"{doc_id}.md").write_text(f"# {title}\n\n{body}\n", encoding="utf-8")
