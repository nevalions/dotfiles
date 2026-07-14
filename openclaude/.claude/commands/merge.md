---
description: "Squash merge feature branch to master and cleanup"
---

Merge the current feature branch to master:

1) Verify branch is ready:
   - Confirm linked bd (beads) issue exists (bd show <id>)

2) Squash merge:
   - git checkout master && git pull origin master
   - git merge --squash <feature-branch>
   - git commit -m "feat: <summary>"
   - git push origin master

3) Create release tag if appropriate:
   - git tag -a vX.Y.Z -m "vX.Y.Z - <description>"
   - git push origin master --follow-tags

4) Cleanup:
   - git branch -d <feature-branch>
   - git push origin -d <feature-branch>

5) Close the linked bd issue: bd close <id>
