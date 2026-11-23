# Pipeline Contract

See root `SKILL.md`:
1. Work in an isolated Git worktree (`--workspace dir:/absolute/path`).
2. `main-implementer` implements and runs tests, then calls `kanban_request_review(reviewer="reviewer")`.
3. `reviewer` verifies the diff and tests, then calls `kanban_complete` (approve) or `kanban_request_changes` (fixable bug).
4. `commiter` handles authorized commits, PRs, and `scripts/ship.sh` delivery.
