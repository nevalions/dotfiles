---
name: pr
description: Use when the user explicitly requests a feature-branch-only push or pull request preparation; unqualified push uses merge.
disable-model-invocation: true
argument-hint: "<bd-issue-id>"
---

## Push routing

An unqualified `push` or `commit and push` means validate the task, squash-merge it locally into the actual default branch, and push the merged result. Use the `merge` workflow; for `commit and push`, commit the scoped task changes first. Do not create a PR unless explicitly requested or required by repository instructions. Explicit feature-branch-only pushes (for example, `push only this branch`) and PR requests use `pr` and retain the task branch/worktree. A commit-only request uses `commit-task` and does not authorize pushing or merging. Repository-specific integration rules take precedence, including kube-lvl47’s server-side PR merge through `scripts/ship.sh`.

The steps below apply only to an explicit branch-only push or PR preparation. An explicit PR request authorizes creating the requested PR after validation and branch push.

For bd (beads) issue $ARGUMENTS:

- Resolve the default branch first, never assume `master` (repos here mix `main`
  and `master`; `git rebase origin/master` in a `main` repo dies with
  "fatal: invalid upstream 'origin/master'"):
  `BASE=$(git symbolic-ref --short refs/remotes/origin/HEAD | sed 's|^origin/||')`
  If that errors, the clone has no origin/HEAD: run `git remote set-head origin -a` once.
- Guard — never rebase or force-push the default branch. `CUR=$(git rev-parse --abbrev-ref HEAD)`:
  - `"$CUR" = "$BASE"` → STOP. Do not fetch, rebase or push. Report it and propose
    moving the work onto `<feat|fix|refactor|docs|chore>/<slug>`
    (`git checkout -b <name>` carries uncommitted changes over). Wait for confirmation.
  - `"$CUR" = "HEAD"` (detached) → STOP and ask.
  - otherwise the branch is a feature branch: confirm the name suits the work, continue.
- Ensure branch is up-to-date: git fetch origin && git rebase origin/"$BASE"
- Summarize the changes made
- Push to remote: git push --force-with-lease -u origin <branch-name>
  (--force-with-lease, not -f: the rebase rewrote history, but a blind -f also
  discards anything pushed from the other PC. -u sets upstream so later bare
  `git push` works.)

Note: Explicit branch-only push/PR preparation keeps the task branch and worktree for review. The `merge` workflow targets the actual default branch and includes guarded local/remote branch and worktree cleanup after required CI passes on the exact merged commit.
