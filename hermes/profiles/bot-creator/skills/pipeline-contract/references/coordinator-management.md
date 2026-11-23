# Coordinator Management

Use the canonical `orchestrator` Bot Chat and native Kanban tools/HTTP API (`/api/plugins/kanban/tasks/{task_id}?board={board}`) to manage cards. Always assign an explicit `assignee` before moving a card to `ready`. To recover a card from `triage` or `blocked`, PATCH `{"status": "ready"}` (or `todo`) once the blocker is addressed.
