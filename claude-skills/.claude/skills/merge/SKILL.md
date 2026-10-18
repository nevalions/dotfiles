---
name: merge
description: Use when the user requests push, commit and push, or integrating a task into the default branch; respect explicit branch-only push/PR requests.
disable-model-invocation: true
---

An unqualified `push` or `commit and push` means validate the task, squash-merge it locally into the actual default branch, and push the merged result. Use the `merge` workflow; for `commit and push`, establish a proper isolated task branch before invoking `commit-task` where needed, then commit the scoped task changes. Do not create a PR unless explicitly requested or required by repository instructions. Explicit feature-branch-only pushes (for example, `push only this branch`) and PR requests use `pr` and retain the task branch/worktree. A commit-only request uses `commit-task` and does not authorize pushing or merging. Repository-specific integration rules take precedence, including kube-lvl47’s server-side PR merge through `scripts/ship.sh`.

Merge the task branch to the repository default branch, then clean up after required CI or the repository’s explicit no-CI validation policy:

1) Verify readiness and record evidence:
   - Confirm the linked bd issue when tracking is authorized (`bd show <id>`), scoped task changes and required pre-merge checks. Resolve the actual default branch from `origin/HEAD` and refresh its remote state; record the exact source SHA, source branch or detached state, remote and owned worktree paths. Never assume `master`.
   - Resolve source state before committing or squashing. If the source is the default branch or the task is already integrated, verify integration evidence and inspect every default-branch commit pending push against the authorized task scope. When no task diff remains to integrate, validate the scoped already-integrated result and normally push only the verified default-branch commits; do not squash the default branch into itself or create an empty commit. If no commits are pending push, report up to date. Never infer task ownership from branch position or push unrelated ahead commits; return unclear ownership or divergence to the parent.
   - For a detached source with unintegrated task work, record its exact SHA and establish a named task branch and isolated task worktree at that SHA before edits or commits. Reuse only a verified branch/worktree for this same task; preserve the original checkout. Do not pass an unnamed detached source into the squash step.
   - For uncommitted task changes, apply the existing task isolation rules and preserve unrelated changes. For `commit and push`, establish the proper task branch/worktree first where needed, then invoke `commit-task` for only the authorized task changes; its default-branch and detached-source guards remain in force. For `push` or `merge`, do not infer authorization to commit uncommitted changes. Require a clean task source before integration.
   - Follow repository-specific merge rules, including server-side PR merge for kube-lvl47. Preserve unrelated checkouts and changes.

2) Squash merge only when unintegrated task work remains, using the authorized repository workflow:
   - For a local merge, use a clean retained checkout where the default branch is available; update it with `git pull --ff-only origin <base>`, then `git merge --squash <task>` and `git commit -F <message-file>`. Read the message back and record the resulting merge SHA. Run the required local validation on that merged result before pushing the default branch with a normal fast-forward push. Never rebase or force-push the default branch. Preserve dirty/unrelated checkouts; return conflicts, failed checks or an unavailable clean integration checkout to the parent.
   - For a server-side merge, confirm the PR is merged into the intended base and record its source SHA and merge result SHA.
   - A requested merge or unqualified push includes the guarded cleanup below. A commit-only or explicit branch-only push/PR request does not. Create/push a release tag only when authorized by the request or explicit repository policy.

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
