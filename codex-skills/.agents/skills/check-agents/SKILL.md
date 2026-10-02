---
name: check-agents
description: Verify whether global or project agents.md instructions are applied
---

## Model selection

Default: `gpt-6-luna / low` (easy). Conflicting instruction scopes: standard. Apply the task routes and runtime limits in `~/.codex/model-policy.md` when available; skill text does not switch the session model.



Are there any canary instructions active?

If yes:
- List all detected canary markers
- Summarize which agent instruction files are currently applied (global vs project)

If no:
- State explicitly that no canary instructions were detected.
