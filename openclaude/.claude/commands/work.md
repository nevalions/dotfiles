---
description: "Work on a bd (beads) issue (e.g. /work sb-5)"
---

Start working on bd issue $ARGUMENTS.

1. Show the issue: `bd show $ARGUMENTS`. If not found, run `bd ready` and ask the user which id they meant.
2. Claim it (sets assignee to you + status in_progress, idempotent): `bd update $ARGUMENTS --claim`
3. Work on the task:
   - Only change files related to the issue
   - Follow project conventions and best practices
   - Run available checks after changes (tests/lint/typecheck if configured)
   - Record progress with `bd update $ARGUMENTS --append-notes "<progress>"`
   - Close only when tests pass and checks are green for the scope — use /commit-task or `bd close $ARGUMENTS`
