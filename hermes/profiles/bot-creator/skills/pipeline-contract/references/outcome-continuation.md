# Outcome Continuation

When a card finishes or wakes `orchestrator`:
1. Inspect `kanban_show` and the worktree state.
2. If approved (`done`) and the user requested delivery (commit/push/PR/deploy), dispatch the delivery step (`commiter` / `ci-watcher`).
3. If local completion is sufficient, report the verified result concisely to the user.
4. If blocked on a fixable technical issue, resolve it directly or return it to `main-implementer`.
