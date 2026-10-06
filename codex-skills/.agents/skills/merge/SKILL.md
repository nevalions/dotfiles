---
name: merge
description: Use when the user requests integrating or squash-merging a feature branch into the repository default branch.
---

## Authorization

Automatic selection loads this workflow; it does not authorize mutations. Execute only the Git stages, remote writes, release actions, or issue filing covered by the user’s request and applicable repository instructions. Complete authorized read-only preparation before seeking any missing authorization.

## Model selection

Default: `gpt-6-luna / low` (easy). Conflicts or release consequences: standard/review. Apply the task routes and runtime limits in `~/.codex/model-policy.md` when available; skill text does not switch the session model.

## Delegation

Delegate this requested workflow to one `git-workflow` agent using the persistent Git routing instructions. Pass the issue, checkout, authorized files/actions and applicable repository rules, then wait and verify its result. If you are already the delegated Git executor, perform the steps directly; do not delegate again. Respect explicit user model choices and report unavailable routing instead of claiming a model switch.



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
