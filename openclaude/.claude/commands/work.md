---
description: "Work on a Vikunja issue (e.g. /work ANS-5)"
---

Start working on Vikunja issue $ARGUMENTS.

Vikunja formatting rules:
- Task descriptions use HTML (e.g. <h2>, <ul>, <pre>, <code>)
- Task comments use plain text only

1. First, search for the task by prefix in the title using vikunja_tasks_list with search="$ARGUMENTS"
2. If found, get the task ID and proceed
3. Move the task to "Doing":
   - List the kanban view buckets with vikunja_buckets_list
   - Move the task to the "Doing" bucket using vikunja_tasks_bulk_update with bucketId of the Doing bucket
4. Work on the task:
   - Only change files related to the issue
   - Follow project conventions and best practices
   - Run available checks after changes (tests/lint/typecheck if configured)
   - Update the Vikunja issue with progress
   - Mark the issue as done only when tests pass and checks are green for the scope
