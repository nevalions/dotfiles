---
description: "Re-run /worklist analysis and file results as bd and/or Vikunja tasks"
argument-hint: "bd | vikunja | both"
agent: "plan"
---

Re-run the `/worklist` analysis on `nevalions/agent` and file the results as tasks in the chosen tracker(s). Output is a structured summary of what was filed, skipped, or errored. Do not write files. Do not modify code. Do not auto-close existing tasks.

## Step 1 — Resolve the tracker from `$ARGUMENTS`

`$ARGUMENTS` is one of:
- `bd` — file only to bd
- `vikunja` — file only to Vikunja
- `both` — file to both
- empty — ask the operator: "File to bd, vikunja, or both?" Wait for a one-word reply, then proceed.

Anything else: print `> /file-tasks: invalid argument '<x>' — expected: bd | vikunja | both` and stop.

## Step 2 — Fetch reports (same as /worklist)

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

## Step 3 — Synthesize the worklist

Read the fetched report contents. Apply this ranking heuristic to identify items worth filing:

1. User-impacting cluster firing — active Alertmanager alerts, non-running pods in watchdog report, cert expiry within 7 days
2. Security high/critical — Trivy CRITICAL or HIGH on running workloads
3. Self-diagnostics broken plumbing — stale `state.json`, missing tunnels, bd DB-vs-JSONL drift
4. Hygiene high — Semgrep ERROR severity findings
5. Refactor hot-spot — top-ranked file in latest refactor index

Build a combined list of Top 3 + Backlog items, capped at **15 total**. Each item has: `title` (one-line, imperative form), `severity` (high/med/low), `evidence` (one-line citing source path + finding), `suggested_action` (one-line, concrete), `source` (the source path).

Severity → priority map:
- `high` → 4 (Urgent)
- `med`  → 3 (High)
- `low`  → 2 (Medium)

## Step 4 — File to bd (only if tracker is bd or both)

### 4a. Verify bd is available

Run via Bash:
```
command -v bd
```
If exit code is non-zero, skip the entire bd half. Record one error line: `bd CLI not available on this host`.

### 4b. List existing open tasks with the worklist label

Run via Bash:
```
bd list --label worklist --status open --json
```
Parse the JSON output. Build a set of existing titles.

### 4c. For each item in the combined list

- If item title (string-equal) is in the existing-titles set → skip, increment `dupe` counter, record `Skipped dupe <existing-id> "<title>"`.
- Otherwise, create:
  ```
  bd create \
    --title "<title>" \
    --priority <priority-from-map> \
    --label worklist \
    --description "Evidence: <evidence>
Suggested action: <suggested_action>
Source: <source>"
  ```
  On success: record `Created <new-id> <severity> "<title>"`, increment `filed` counter.
  On non-zero exit: record `Error: <stderr>`, increment `errors` counter, continue with next item.

## Step 5 — File to Vikunja (only if tracker is vikunja or both)

### 5a. List Vikunja projects (once)

Call `mcp__vikunja__projects_list`. Build a list of `{id, title}` pairs.

If the call returns 401: skip the entire Vikunja half. Record one error line: `Vikunja MCP unauthenticated`.

### 5b. Ensure the `worklist` label exists

Call `mcp__vikunja__labels_list`. If no label has title `worklist`, create one via `mcp__vikunja__label_create` with title `worklist`. Capture the label's `id`.

### 5c. For each item in the combined list

1. **Pick a project by judgment:** Read project titles + identifiers and pick the best fit for the item's `title` and `source`:
   - Items with source under `memory/ops/`, `memory/alerts/`, or `memory/logs/` → cluster/ops project if one exists, else agent project.
   - Items with source under `memory/refactor/` → if the refactor index mentions a specific repo and a Vikunja project matches that repo, use it; else agent project.
   - Items with source under `memory/diagnostics/` or `memory/security/` → agent project.
   - Items with source under `memory/hygiene/` or `memory/triage/` → agent project.
   - When no clean fit: agent project (operator's catch-all).
   The "agent project" is the project whose title contains "agent" (case-insensitive).

2. **Dedup:** Call `mcp__vikunja__tasks_list` with `projectId=<chosen-id>`. Filter results to tasks whose `labels` array contains the `worklist` label id and `done=false`. If any such task has the same title (string-equal), skip and increment `dupe` counter.
   Note: the agent's reconciler may auto-prefix titles with `ANS-N:` after creation. When dedup-comparing, strip a leading `^[A-Z]+-\d+:\s*` from existing titles before equality check.

3. **Create:** Call `mcp__vikunja__task_create` with:
   - `project_id`: chosen project id
   - `title`: the item title
   - `priority`: severity-mapped (4 / 3 / 2)
   - `description`: HTML, exactly:
     ```html
     <ul><li><b>Evidence:</b> <evidence></li><li><b>Suggested:</b> <suggested_action></li><li><b>Source:</b> <source></li></ul>
     ```
     (escape the evidence/action/source text for HTML if they contain `<` `>` `&`).
   On 401 or 5xx: record `Error: <status> <message>`, increment `errors` counter, continue.

4. **Attach the worklist label:** Call `mcp__vikunja__label_add_to_task` with the new task's id and the `worklist` label id. On error, record but do not fail the item.

5. Record `Created project=<title> id=<task-id> <severity> "<title>"`, increment `filed` counter.

## Step 6 — Print the summary

Use exactly this format. Show only the section(s) for tracker(s) that were attempted (skip a section entirely if its tracker was not in the resolved choice).

```
## /file-tasks summary

- Tracker(s): <bd | vikunja | both>
- Filed: <N>
- Skipped (dupe): <M>
- Errors: <X>
```

Then per-tracker breakdown (only present sections that ran):

```
### bd
- Created <id> <severity> "<title>"
- Skipped dupe <id> "<title>"
- Error: <message>
...

### vikunja
- Created project=<title> id=<id> <severity> "<title>"
- Skipped dupe id=<id> "<title>"
- Error: <message>
...
```

If any forgejo source was skipped during Step 2, append a final footer line:
```
> source skipped: memory/refactor/ (empty), memory/security/ (HTTP 500)
```

Do not add preamble or trailing prose. The summary is the entire output.
