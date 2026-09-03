---
description: "Re-run /worklist analysis and file the results as bd (beads) issues"
agent: "plan"
---

Re-run the `/worklist` analysis on `nevalions/agent` and file the results as bd (beads) issues. Output is a structured summary of what was filed, skipped, or errored. Do not write files other than the temp item file below. Do not modify code. Do not auto-close existing issues.

!`python3 ~/code/agent/scripts/worklist-fetch.py`

## Step 1 — Synthesize the worklist

Read the fetched report contents above. Apply this ranking heuristic to identify items worth filing:

1. User-impacting cluster firing — active Alertmanager alerts, non-running pods in watchdog report, cert expiry within 7 days
2. Security high/critical — Trivy CRITICAL or HIGH on running workloads
3. Self-diagnostics broken plumbing — stale `state.json`, missing tunnels, bd DB-vs-JSONL drift
4. Hygiene high — Semgrep ERROR severity findings
5. Refactor hot-spot — top-ranked file in latest refactor index

Build a combined list of Top 3 + Backlog items, capped at **15 total**. Each item has: `title` (one-line, imperative form), `severity` (high/med/low), `evidence` (one-line citing source path + finding), `suggested_action` (one-line, concrete), `source` (the source path).

## Step 2 — File the items

Write the items as a JSON array to a temp file under the scratchpad directory and run:
```
python3 ~/code/agent/scripts/file-tasks.py < <file>
```
Relay the script's summary verbatim, followed by the skipped-sources footer (built from any `skipped: ...` entries in the `## Sources` list above) if any source was skipped.
