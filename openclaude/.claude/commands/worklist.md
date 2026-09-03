---
description: "Analyze agent repo reports via Forgejo MCP and produce a prioritized worklist"
agent: "plan"
---

Produce a decision-ready worklist from the latest observation reports fetched below from the agent repo `nevalions/agent`. Output goes to the conversation only — do not write files, do not create issues or tasks.

!`python3 ~/code/agent/scripts/worklist-fetch.py`

## Step 1 — Synthesize the worklist

Read the fetched report contents above. Identify problems worth working on. Apply this ranking heuristic to pick the Top 3 (in priority order):

1. User-impacting cluster firing — active Alertmanager alerts, non-running pods in watchdog report, cert expiry within 7 days
2. Security high/critical — Trivy CRITICAL or HIGH on running workloads
3. Self-diagnostics broken plumbing — stale `state.json`, missing tunnels, bd DB-vs-JSONL drift
4. Hygiene high — Semgrep ERROR severity findings
5. Refactor hot-spot — top-ranked file in latest refactor index

This is judgment, not a score. Pick the three items most worth doing now based on the reports. Backlog is everything else flagged, capped at 12 entries.

## Step 2 — Print the output

Use exactly this format:

```
## Top 3 to work on now

1. <one-line title> — severity: <high|med|low>
   Evidence: <1 line citing the source report path and the specific finding>
   Suggested action: <1 line, concrete>

2. <one-line title> — severity: <high|med|low>
   Evidence: ...
   Suggested action: ...

3. <one-line title> — severity: <high|med|low>
   Evidence: ...
   Suggested action: ...

## Backlog

- [<severity>] <title> — <source path>
- [<severity>] <title> — <source path>
- ...
```

If the `## Sources` list above contains any `skipped: ...` entries, append a single footer line listing them:
```
> skipped: memory/refactor/ (empty), memory/security/ (HTTP 500)
```

Do not add any preamble, summary, or trailing prose. The two sections (and optional skipped footer) are the entire output.
