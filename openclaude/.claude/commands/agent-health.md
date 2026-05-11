---
description: "One-screen verdict on the agent's freshness and self-diagnostics state"
agent: "plan"
---

Produce a one-screen health verdict for the persistent agent on `claw`. Read the agent repo's pushed state on `nevalions/agent` via Forgejo MCP only. Output is a verdict line plus a short breakdown. Do not write files. Do not modify state. Do not attempt SSH or local-host probes.

## Step 1 — Fetch the four sources in parallel

Run these four MCP calls in parallel:

1. **state.json** — `mcp__forgejo__get_file_contents` with `owner=nevalions`, `repo=agent`, `path=memory/state.json`. Parse the returned content as JSON.
2. **Latest diagnostics report** — `mcp__forgejo__get_file_contents` with `path=memory/diagnostics`. From the listing, pick the lexicographically last `*.md` file (filenames are `YYYY-MM-DD-HHMM-diag.md`, latest sorts last). Then fetch that file's contents.
3. **Latest top-level daily log** — `mcp__forgejo__get_file_contents` with `path=memory`. From the listing, filter to top-level files matching `^\d{4}-\d{2}-\d{2}\.md$`, pick the lexicographically last one. Then fetch its contents.
4. **Newest commit on main** — `mcp__forgejo__list_repo_commits` with `owner=nevalions`, `repo=agent`, `sha=main`, `limit=1`. Capture the `created` (or commit timestamp) field of the single returned commit.

If ALL four fetches fail (Forgejo MCP unreachable or all 404), print exactly:
```
> /agent-health: forgejo MCP unreachable — cannot determine state
```
and stop.

If individual fetches fail, continue with degraded signal computation per Step 4's failure-handling rules.

## Step 2 — Parse `state.json`

`state.json` is a JSON object with per-routine entries containing at minimum `last_run` (ISO-8601 timestamp) and (optionally) `paused: true`. Build:
- `routines`: list of `{name, last_run, paused, expected_cadence}` where `expected_cadence` is inferred from the routine name:
  - hourly cadence: `cluster-watchdog`, `cluster-alerts`, `cluster-logs`
  - daily cadence: `forgejo-triage`, `morning-briefing`, `auto-triage`, `self-diagnostics`, `security-audit`, `brainstorm-nightly`
  - weekly cadence: `repo-hygiene`, `memory-compaction`, `velocity`, `reconciliation`
  - nightly cadence: `refactor-nightly`
  - any other routine name: skip cadence check (treat as `unknown`).

If `state.json` was missing or unparseable, set `state_status = "unparseable"` and continue.

## Step 3 — Parse the latest daily log

The daily log is markdown with timestamped entries (the heartbeat skill writes one line per beat). Find the latest entry's timestamp by:
- Looking for lines matching either `^## \d{2}:\d{2}` or `^- \d{2}:\d{2}` (h:mm prefix), and pairing the `HH:MM` with the date encoded in the filename (`YYYY-MM-DD.md`).
- The latest is the entry with the largest combined `YYYY-MM-DD HH:MM`.

Set `last_beat_ts` to that combined timestamp. If no timestamped entry was found, set `last_beat_ts = null`.

## Step 4 — Compute the signals

Given `now` = the current local time (use the conversation's date context):

1. **last_beat_age** — `now - last_beat_ts`. If `last_beat_ts` is null, treat as `unknown`.
2. **last_push_age** — `now - newest commit timestamp`. If commit fetch failed, treat as `unknown`.
3. **routines_status** — for each routine in `routines`, compare `last_run` to its expected cadence:
   - hourly: late if `now - last_run > 90 minutes`
   - daily: late if `now - last_run > 30 hours`
   - weekly: late if `now - last_run > 8 days`
   - nightly: late if `now - last_run > 30 hours`
   Tally `on_schedule` and `late` counts. Build `late_list = [{name, lateness_h}]`.
4. **bd_parity** — read the latest diagnostics report and search for the bd-parity verdict line. Map to `OK` / `drift` / `unknown` (use `unknown` if the diag report has no parity section).
5. **paused_flags** — list of routine names where `paused=true` in `state.json`.
6. **diag_note** — if the diagnostics report has any `WARN` or `FAIL` line not already covered by signals 1-5, capture the most prominent one as a single short string. Otherwise `null`.

## Step 5 — Classify the verdict

Compute the verdict tier:
- **UNHEALTHY** — any of:
  - `last_beat_age > 6h` OR `last_beat_age == unknown`
  - `state_status == "unparseable"`
  - Two or more of the DEGRADED conditions below are true.
- **DEGRADED** — none of the UNHEALTHY conditions, AND any of:
  - `last_beat_age` between 90min and 6h
  - `late_list` has at least one routine
  - `bd_parity == "drift"`
  - `paused_flags` is non-empty
  - `last_push_age > 6h` (push halt while beats might still happen locally — flag-worthy but not severe alone)
- **OK** — none of the above.

Reason string:
- For UNHEALTHY/DEGRADED, build a short reason from the worst single condition (e.g. `last beat 4h ago`, or `2 routines missed`, or `bd parity drift`). Pick the highest-severity condition first; if multiple tied, the first in the rule order above wins.

## Step 6 — Print the output

Use exactly this format:

```
> agent <OK | DEGRADED | UNHEALTHY> — <reason>

  - Last beat: <Nm ago | Nh ago | unknown> (<ISO timestamp or "unknown">)
  - Last push: <Nm ago | Nh ago | unknown> (<ISO timestamp or "unknown">)
  - Routines: <X on schedule, Y late>
    <if Y > 0, one indented sub-bullet per late routine: "    - <name>: <lateness_h>h late">
  - bd parity: <OK | drift | unknown>
  - Paused: <none | comma-separated routine names>
```

If `diag_note` is non-null, append:
```
  - Diag note: <diag_note>
```

Always finish with this caveat, on its own line block:
```
> Caveat: this view reflects PUSHED state on origin/main. Unpushed local
> commits on claw are invisible — a stale beat could be a heartbeat halt OR
> a push halt. Confirm on claw if in doubt.
```

Do not add a preamble. The verdict block + breakdown + caveat is the entire output.

## Failure-handling reference

| Source missing/failed | Effect on output |
|---|---|
| `state.json` | Verdict UNHEALTHY, reason `state.json missing/unparseable`. Routines line: `Routines: unknown (state.json unavailable)`. |
| Diagnostics dir empty / fetch failed | `bd parity: unknown — no recent diag report`. Use `unknown` for diag_note. Downgrade verdict per Step 5 rules. |
| No daily log file in current month | Verdict UNHEALTHY, reason `no recent daily log`. `Last beat: unknown`. |
| `list_repo_commits` failed | `Last push: unknown (commit lookup failed)`. Don't apply the `last_push_age > 6h` DEGRADED rule. |
