---
name: work
description: "Work on a bd (beads) issue (e.g. /work sb-5)"
disable-model-invocation: true
argument-hint: "<bd-issue-id>"
---

Start working on bd issue $ARGUMENTS.

1. Show the issue: `bd show $ARGUMENTS`. If not found, run `bd ready` and ask the user which id they meant.
2. Claim it (sets assignee to you + status in_progress, idempotent): `bd update $ARGUMENTS --claim`
3. Do the work within the issue's scope. Record progress with `bd update $ARGUMENTS --append-notes "<progress>"`. Close only when the project's checks pass for the scope — use /commit-task or `bd close $ARGUMENTS`.
