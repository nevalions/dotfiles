---
description: "Commit changes and close a bd (beads) issue (e.g. /commit-task sb-5)"
---

Commit changes and update bd issue $ARGUMENTS.

Steps:
1. Guard — do not commit onto the default branch without asking:
   - `BASE=$(git symbolic-ref --short refs/remotes/origin/HEAD | sed 's|^origin/||')`
     (if that errors the clone has no origin/HEAD: run `git remote set-head origin -a` once)
   - `CUR=$(git rev-parse --abbrev-ref HEAD)`
   - `"$CUR" = "$BASE"` → STOP before staging anything. Report it and propose a
     branch `<feat|fix|refactor|docs|chore>/<slug>`; `git checkout -b <name>`
     carries the uncommitted changes over, so nothing is lost by branching now.
     Proceed on the default branch only if the user confirms, or the repo's own
     documented flow commits there (kube-lvl47's Flux cutover bumps `newTag` on
     `master` directly — workspace CLAUDE.md, step 3).
   - `"$CUR" = "HEAD"` (detached) → STOP and ask; do not commit.
2. Show the issue: `bd show $ARGUMENTS`
3. Review changes: git status && git diff HEAD
   (`git diff HEAD`, not bare `git diff` — bare shows only unstaged changes and
   silently hides anything already staged.)
4. Stage and commit (stage explicit files, not `-A`):
   - git add <file> ...
   - git commit -m "<conventional commit message>"
5. Update the bd issue:
   - If work is complete: `bd close $ARGUMENTS`
   - If partial: `bd update $ARGUMENTS --append-notes "<progress>"` (leave open)
6. Make the bd change leave this machine (a closure after the last commit is
   otherwise stranded behind a clean worktree, with no warning):
   - dolt-native repos (most of them): run `bd dolt push`.
   - the six JSONL holdouts (`agent`, `lo-news-backend`, `lo-news-frontend`,
     `spb-news-backend`, `spb-news-frontend`, `scoreboard_clock`): the pre-commit
     hook is the export path, so close the issue BEFORE the final commit, or make
     a follow-up commit for the `.beads/issues.jsonl` export.
7. Confirm completion.

Conventional commit prefixes:
- feat: new feature
- fix: bug fix
- refactor: code cleanup
- docs: documentation
- chore: maintenance
