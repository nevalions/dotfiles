# Admission Preflight

Before dispatching a coding card:
1. Ensure the target task worktree exists and is clean (run `git-freshness` once per repo).
2. Write a concise card body specifying the goal, worktree path (`--workspace dir:/path`), and test command.
3. Do not generate external `-evidence/` JSON preflight receipts.
