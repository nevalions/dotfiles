---
description: "Analyze agent repo reports via Forgejo MCP and produce a prioritized worklist"
agent: "plan"
---

Produce a decision-ready worklist by reading the latest observation reports from the agent repo `nevalions/agent` via Forgejo MCP. Output goes to the conversation only — do not write files, do not create issues or tasks.

## Step 1 — List the eight source directories

Call `mcp__forgejo__get_file_contents` once per directory below to list its contents. Use `owner: "nevalions"`, `repo: "agent"`, and the directory path as `path`. Run the eight calls in parallel.

Source directories:
- `memory/ops`         (cluster-watchdog, hourly)
- `memory/alerts`      (cluster-alerts, hourly)
- `memory/logs`        (cluster-logs, hourly)
- `memory/security`    (security-audit, daily)
- `memory/diagnostics` (self-diagnostics, daily)
- `memory/hygiene`     (repo-hygiene, weekly)
- `memory/refactor`    (refactor-nightly index — top-level files only, NOT per-repo subdirs)
- `memory/triage`      (forgejo-triage, daily)

For each directory, pick the lexicographically last `.md` file at the top level (filenames use `YYYY-MM-DD[-HHMM]-*.md`, so latest sorts last). For `memory/refactor`, ignore subdirectories — only consider top-level `*.md` files (the daily index).

If a directory listing returns empty, returns no `.md` files, or the call errors (404, 500, network), record the path and reason and skip it.

## Step 2 — Fetch the latest file from each non-skipped directory

Call `mcp__forgejo__get_file_contents` once per selected file, in parallel. Same `owner`/`repo`, `path` is the full file path (e.g. `memory/ops/2026-05-05-1400-cluster.md`).

If a fetch fails, mark that source as skipped with the HTTP status and continue.

If ALL eight sources end up skipped, print exactly this single line and stop:
```
> /worklist: no sources reachable — check forgejo MCP connectivity
```

## Step 3 — Synthesize the worklist

Read the fetched report contents. Identify problems worth working on. Apply this ranking heuristic to pick the Top 3 (in priority order):

1. User-impacting cluster firing — active Alertmanager alerts, non-running pods in watchdog report, cert expiry within 7 days
2. Security high/critical — Trivy CRITICAL or HIGH on running workloads
3. Self-diagnostics broken plumbing — stale `state.json`, missing tunnels, bd DB-vs-JSONL drift
4. Hygiene high — Semgrep ERROR severity findings
5. Refactor hot-spot — top-ranked file in latest refactor index

This is judgment, not a score. Pick the three items most worth doing now based on the reports. Backlog is everything else flagged, capped at 12 entries.

## Step 4 — Print the output

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

If any sources were skipped, append a single footer line listing them with the reason:
```
> skipped: memory/refactor/ (empty), memory/security/ (HTTP 500)
```

Do not add any preamble, summary, or trailing prose. The two sections (and optional skipped footer) are the entire output.
