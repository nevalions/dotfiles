---
description: "Commit changes and close a bd (beads) issue (e.g. /commit-task sb-5)"
---

Commit changes and update bd issue $ARGUMENTS.

Steps:
1. Show the issue: `bd show $ARGUMENTS`
2. Review changes: git status && git diff
3. Stage and commit (stage explicit files, not `-A`):
   - git add <file> ...
   - git commit -m "<conventional commit message>"
4. Update the bd issue:
   - If work is complete: `bd close $ARGUMENTS`
   - If partial: `bd update $ARGUMENTS --append-notes "<progress>"` (leave open)
5. Confirm completion.

Conventional commit prefixes:
- feat: new feature
- fix: bug fix
- refactor: code cleanup
- docs: documentation
- chore: maintenance
