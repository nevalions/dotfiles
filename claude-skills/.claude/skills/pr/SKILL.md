---
name: pr
description: "Prepare feature branch for merge (solo-owner workflow)"
disable-model-invocation: true
argument-hint: "<bd-issue-id>"
---

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

Note: This is a solo-owner workflow. PRs are optional. The `merge` command will perform a squash merge to master.
