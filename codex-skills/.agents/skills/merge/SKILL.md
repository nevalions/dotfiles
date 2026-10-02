---
name: merge
description: Squash merge feature branch to the default branch and cleanup
---


Merge the current feature branch to the repository default branch:

1) Verify branch is ready:
   - Confirm linked bd (beads) issue exists (bd show <id>)

2) Squash merge:
   - Resolve the default branch with `git symbolic-ref --short refs/remotes/origin/HEAD`; then `git checkout <base>` and `git pull --ff-only origin <base>`
   - git merge --squash <feature-branch>
   - git commit -F <message-file>
   - git push origin <base>

3) Create release tag if appropriate:
   - git tag -a vX.Y.Z -m "vX.Y.Z - <description>"
   - git push origin <base> --follow-tags

4) Cleanup:
   - git branch -D <feature-branch>
     (-D, not -d: a squash merge leaves no merge commit, so -d always fails with
     "the branch is not fully merged". Only run it after step 2's push succeeded.)
   - git push origin -d <feature-branch>

5) Close the linked bd issue: bd close <id>
