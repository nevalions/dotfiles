---
name: create
description: Use when the user requests creating or recording a bd (beads) issue for a task, bug, or feature.
---

## Model selection

Default: `gpt-6-luna / low` (easy). Ambiguous requirements or design: standard. Apply the task routes and runtime limits in `~/.codex/model-policy.md` when available; skill text does not switch the session model.



Create a new bd (beads) issue for: <arguments supplied by the user>

## Scope: recording a task is not doing it

A request to *create / record / add* a task or ticket is creation only. Write
the issue from evidence already in hand and stop — do not run the diagnosis,
dispatch a worker, or change the target system in the same turn. This user
treats a status flip or a spawned worker as "you started work I did not ask
for" and will delete the ticket and re-create it under the bot they wanted.

What the description should carry, so the eventual owner needs no second
round-trip: the observed symptom with its verbatim error, what was already
verified (with the command or query that produced it), ranked hypotheses,
the concrete reproduction/diagnostic commands, and acceptance criteria.

## Which tracker

"Kanban", "board", or "column" means the **Hermes kanban board**
(`hermes kanban [--board <slug>] create ...`, no `.beads/` needed) — not
beads. Beads is the `bd` CLI plus a per-repo `.beads/` store. When the user
names a column they want the task parked in, read the board mechanics before
creating: `todo` is not a resting state in Hermes kanban, so pick `--triage`,
`block`, or an assignee instead of forcing a status. Mechanics live in the
`hermes-agent` skill's background-systems reference (kanban section).

bd notes:
- Descriptions, acceptance, and notes are plain text / markdown (no HTML).
- Priority `-p 0..4`, 0 = highest. 0=Urgent 1=High 2=Medium (default) 3=Low 4=Trivial.

Steps:
1. Confirm bd is initialized here: `bd ready` (or check for a `.beads/` dir). If none, tell the user to run `bd init` first and stop.
2. Draft the issue, then create it:
   - title: descriptive, action-oriented, imperative
   - description: what the task is, why it's needed, how to verify it's done
   - acceptance criteria when applicable
   - priority: infer from urgency using the scale above
   - labels: bug, feature, enhancement, documentation, etc.
3. Create it:
   ```
   bd create "<title>" \
     -p <0-4> \
     -l <comma,separated,labels> \
     -d "<description>" \
     --acceptance "<acceptance criteria>"
   ```
4. Confirm creation with the returned issue id.
