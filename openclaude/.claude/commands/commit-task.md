---
description: "Commit changes and close Vikunja issue (e.g. /commit-task ANS-5)"
---

Commit changes and update Vikunja issue $ARGUMENTS.

Vikunja formatting rules:
- Task descriptions use HTML (e.g. <h2>, <ul>, <pre>, <code>)
- Task comments use plain text only

Steps:
1. Find the task using vikunja_tasks_list with search="$ARGUMENTS"
2. Review changes: git status && git diff
3. Stage and commit:
   - git add -p
   - git commit -m "<conventional commit message>"
4. Update Vikunja task:
   - If work is complete: mark as done with vikunja_task_complete
   - If partial: add comment with vikunja_comment_create describing progress (plain text)
5. Confirm completion

Conventional commit prefixes:
- feat: new feature
- fix: bug fix
- refactor: code cleanup
- docs: documentation
- chore: maintenance
