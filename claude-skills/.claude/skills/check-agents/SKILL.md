---
name: check-agents
description: Verify whether global or project agents.md instructions are applied
disable-model-invocation: true
context: fork
agent: Plan
---

Are there any canary instructions active?

If yes:
- List all detected canary markers
- Summarize which agent instruction files are currently applied (global vs project)

If no:
- State explicitly that no canary instructions were detected.
