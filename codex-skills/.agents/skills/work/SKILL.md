---
name: work
description: Work on a bd (beads) issue (e.g. $work sb-5)
---

## Model selection

Default: `gpt-6.1-sol / medium` (standard). Fully specified mechanical work: easy; complex debugging: review; hardest architecture: deep. Apply the task routes and runtime limits in `~/.codex/model-policy.md` when available; skill text does not switch the session model.



Start working on bd issue <arguments supplied by the user>.

1. Show the issue: `bd show <issue-id>`. If not found, run `bd ready` and ask the user which id they meant.
2. Claim it (sets assignee to you + status in_progress, idempotent): `bd update <issue-id> --claim`
3. Do the work within the issue's scope. Record progress with `bd update <issue-id> --append-notes "<progress>"`. Close only when the project's checks pass for the scope — use $commit-task or `bd close <issue-id>`.
