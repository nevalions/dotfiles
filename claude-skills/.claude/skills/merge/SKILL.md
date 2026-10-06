---
name: merge
description: "Squash merge feature branch to master and cleanup"
disable-model-invocation: true
---

Merge the task branch to the repository default branch, then clean up only after verified CI:

1) Verify readiness and record evidence:
   - Confirm the linked bd issue (`bd show <id>`), clean task checkout and required pre-merge checks.
   - Resolve the actual default branch from `origin/HEAD`; record the task branch, exact source SHA, remote and owned worktree paths. Never assume `master`.
   - Follow repository-specific merge rules, including server-side PR merge for kube-lvl47. Preserve unrelated checkouts and changes.

2) Squash merge using the authorized repository workflow:
   - For a local merge, use a clean retained checkout where the default branch is available; update it with `git pull --ff-only origin <base>`, then `git merge --squash <task>` and `git commit -F <message-file>`. Read the message back, record the resulting merge SHA and push the default branch.
   - For a server-side merge, confirm the PR is merged into the intended base and record its source SHA and merge result SHA.
   - A requested merge includes the guarded cleanup below. A commit or branch push alone does not. Create/push a release tag only when authorized by the request or explicit repository policy.

3) Verify the merged result before cleanup:
   - Fetch the default branch; confirm the recorded merge result SHA is present on it and matches the merge evidence for the recorded source SHA.
   - Wait for all required CI on that exact merged commit to pass; record run IDs/results. Feature-branch CI alone is insufficient. Pending, failed, cancelled, skipped or unknown required checks block cleanup.
   - If CI is intentionally absent, use the repository's explicit validation policy; otherwise retain artifacts and report missing evidence. For frontend/backend repositories, verify each independently.

4) Clean the confirmed merged task only:
   - Recheck local/remote branch tips against the recorded source SHA; retain any changed ref. Squash merges require confirmed PR evidence or the recorded local squash/push result, never just ancestry or `git branch --merged`.
   - Inspect `git worktree list --porcelain` and each candidate's `git status --porcelain --untracked-files=all --ignored`. Preserve dirty/untracked work and valuable ignored files such as `.env`; only disposable setup artifacts may be removed with a clean worktree.
   - Preserve the main checkout, default/protected branches, active/locked worktrees and unrelated/unmerged tasks. Release finished sessions/processes and move execution to a retained checkout before cleanup. Never remove a worktree still hosting an active agent; report it as retained until released.
   - Remove eligible task worktrees with `git worktree remove <path>` without force. Recheck the worktree list; do not delete a branch checked out in any remaining worktree.
   - Use `git branch -d <task>` when ancestry proves the merge. For an evidenced squash merge, delete only the unchanged ref with `git update-ref -d refs/heads/<task> <recorded-source-sha>`; then remove its obsolete `branch.<task>` config section if present. Never use blind `-D` deletion.
   - Query `git ls-remote --heads origin refs/heads/<task>`; an absent ref is already cleaned. If its SHA matches the merged source, delete with `git push --force-with-lease=refs/heads/<task>:<recorded-source-sha> origin :refs/heads/<task>`. This exact-SHA deletion lease rejects concurrent new work; never retry with a blind force or broaden the ref scope.
   - Fetch/prune remote-tracking refs after remote deletion. Never bulk-delete by age/pattern, force-remove worktrees, reset or discard work.

5) Verify/report and close the linked issue when complete:
   - Verify task refs are absent locally and remotely and eligible task worktrees are removed. Report CI evidence, what was cleaned and anything retained with its reason; pending cleanup must remain explicit.
   - Close the linked bd issue only when its acceptance criteria are met: `bd close <id>`.
