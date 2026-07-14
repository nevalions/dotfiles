---
description: "Prepare feature branch for merge (solo-owner workflow)"
---

For bd (beads) issue $ARGUMENTS:

- Verify current branch is appropriate or propose a new feature branch name
- Ensure branch is up-to-date: git fetch origin && git rebase origin/master
- Summarize the changes made
- Push to remote: git push -f origin <branch-name>

Note: This is a solo-owner workflow. PRs are optional. The `merge` command will perform a squash merge to master.
