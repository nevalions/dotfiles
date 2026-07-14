---
description: "Re-run /worklist analysis and file the results as bd (beads) issues"
agent: "plan"
---

Re-run the `/worklist` analysis on `nevalions/agent` and file the results as bd (beads) issues. Output is a structured summary of what was filed, skipped, or errored. Do not write files. Do not modify code. Do not auto-close existing issues.

## Step 1 — Fetch reports (same as /worklist)

Call `mcp__forgejo__get_file_contents` once per directory below to list its contents. Use `owner: "nevalions"`, `repo: "agent"`. Run all eight calls in parallel.

Source directories:
- `memory/ops`
- `memory/alerts`
- `memory/logs`
- `memory/security`
- `memory/diagnostics`
- `memory/hygiene`
- `memory/refactor` (top-level files only — ignore per-repo subdirectories)
- `memory/triage`

For each directory, pick the lexicographically last `.md` file at the top level (filenames are `YYYY-MM-DD[-HHMM]-*.md`, latest sorts last). If a listing is empty, returns no `.md`, or errors, record the path + reason and skip it.

Then fetch the contents of each selected file in parallel via `mcp__forgejo__get_file_contents`. If a fetch fails, mark that source skipped with the HTTP status and continue.

If ALL eight sources end up skipped, print exactly:
```
> /file-tasks: no sources reachable — check forgejo MCP connectivity
```
and stop without filing anything.

## Step 2 — Synthesize the worklist

Read the fetched report contents. Apply this ranking heuristic to identify items worth filing:

1. User-impacting cluster firing — active Alertmanager alerts, non-running pods in watchdog report, cert expiry within 7 days
2. Security high/critical — Trivy CRITICAL or HIGH on running workloads
3. Self-diagnostics broken plumbing — stale `state.json`, missing tunnels, bd DB-vs-JSONL drift
4. Hygiene high — Semgrep ERROR severity findings
5. Refactor hot-spot — top-ranked file in latest refactor index

Build a combined list of Top 3 + Backlog items, capped at **15 total**. Each item has: `title` (one-line, imperative form), `severity` (high/med/low), `evidence` (one-line citing source path + finding), `suggested_action` (one-line, concrete), `source` (the source path).

Severity → bd priority map (bd is 0=highest):
- `high` → 1
- `med`  → 2
- `low`  → 3

## Step 3 — File to bd

### 3a. Verify bd is available

Run via Bash:
```
command -v bd
```
If exit code is non-zero, stop and print one error line: `bd CLI not available on this host`.

### 3b. List existing open issues with the worklist label

Run via Bash:
```
bd list --label worklist --status open --json
```
Parse the JSON output. Build a set of existing titles.

### 3c. For each item in the combined list

- If item title (string-equal) is in the existing-titles set → skip, increment `dupe` counter, record `Skipped dupe <existing-id> "<title>"`.
- Otherwise, create:
  ```
  bd create "<title>" \
    -p <priority-from-map> \
    -l worklist \
    -d "Evidence: <evidence>
Suggested action: <suggested_action>
Source: <source>"
  ```
  On success: record `Created <new-id> <severity> "<title>"`, increment `filed` counter.
  On non-zero exit: record `Error: <stderr>`, increment `errors` counter, continue with next item.

## Step 4 — Print the summary

Use exactly this format:

```
## /file-tasks summary

- Filed: <N>
- Skipped (dupe): <M>
- Errors: <X>

### bd
- Created <id> <severity> "<title>"
- Skipped dupe <id> "<title>"
- Error: <message>
...
```

If any forgejo source was skipped during Step 1, append a final footer line:
```
> source skipped: memory/refactor/ (empty), memory/security/ (HTTP 500)
```

Do not add preamble or trailing prose. The summary is the entire output.
