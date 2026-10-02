# KNIME workflow: portfolio KPIs without code

This guide rebuilds the core of the Python pipeline in KNIME Analytics Platform, so the
same KPIs can be produced and maintained by colleagues who prefer a visual tool. Results
should match `out/exports/project_health.csv` exactly, which makes the KNIME version easy
to check.

Build it yourself step by step; it takes about 1.5 to 2 hours the first time.

## 0. Setup

1. Install KNIME Analytics Platform (free) from knime.com.
2. Run `python -m rdpa build` once so that `data/raw/*.csv` and `data/portfolio.db` exist.
3. In KNIME: File > New > New KNIME Workflow, name it `rd_portfolio_kpis`.

## 1. Read the raw exports

Add four **CSV Reader** nodes, one each for `projects.csv`, `milestones.csv`, `risks.csv`,
`timesheets.csv` in `data/raw/`. In each: header row on, column delimiter `,`, encoding UTF-8.

## 2. Validate and quarantine (milestones)

1. **String to Date&Time** on `planned_date` and `actual_date` (format `yyyy-MM-dd`, fail on
   error off). Rows whose date did not parse become missing values.
2. **Rule-based Row Splitter**: `MISSING $planned_date$ => FALSE`, `TRUE => TRUE`. Bottom port = invalid dates.
3. **Reference Row Splitter** against the projects table on `project_id`. Rows without a
   match = unknown project.
4. **Duplicate Row Filter** (all columns) with "remove duplicates". Keep the "duplicates" output too.
5. **Constant Value Column** on each rejected branch with a `reason` column
   (`invalid_date`, `unknown_project`, `duplicate`), then **Concatenate** them into one quarantine table.

Check: the quarantine table must have 2 + 2 + 3 = 7 milestone rows (see `data/manifest.json`).

Repeat the pattern for risks (`probability`/`impact` between 1 and 5 with **Rule-based Row
Filter**, owner not missing) and timesheets (`hours >= 0`, duplicates).

## 3. KPIs

1. **Overdue milestones**: **Rule Engine** creating `overdue`:
   `MISSING $actual_date$ AND $planned_date$ < "2026-09-30" => 1`, `TRUE => 0`.
   Then **GroupBy** on `project_id` with Sum(`overdue`).
2. **Hours used**: **GroupBy** timesheets on `project_id`, Sum(`hours`).
3. **Max open risk**: **Math Formula** `$probability$ * $impact$` as `score`, **Row Filter**
   `status = open`, **GroupBy** `project_id` with Max(`score`).
4. **Joiner** (three times) to bring the KPI tables onto the projects table.
5. **Math Formula** for the burn index:
   `($hours_used$ / $budget_hours$) / min(1, max(0.01, (date("2026-09-30") - $start_date$) / ($planned_end$ - $start_date$)))`
   (or compute the day differences first with **Date&Time Difference** nodes, which is easier to read).
6. **Rule Engine** for the status, same rules as the Python code:
   ```
   $overdue$ >= 2 => "red"
   $overdue$ >= 1 AND $max_risk_score$ >= 15 => "red"
   $overdue$ >= 1 OR $burn_index$ > 1.15 OR $max_risk_score$ >= 15 => "amber"
   TRUE => "green"
   ```

## 4. Output

1. **CSV Writer** to `out/knime/project_health_knime.csv`.
2. **Table Difference Finder** (or a Joiner + Rule Engine) against
   `out/exports/project_health.csv` on `project_id` and `status`. Expect zero differences.
3. Optional: **Bar Chart** node on `burn_index` coloured by `status`, and a **Component**
   with a simple view so the workflow can be opened as a small dashboard.

## 5. Add it to the repository

1. File > Export KNIME Workflow, save as `workflows/knime/rd_portfolio_kpis.knwf`.
2. Take one screenshot of the workflow canvas and save it as `docs/images/knime_workflow.png`.
3. Add a short "KNIME version" section to the README with the screenshot and the result of
   the comparison in step 4.
