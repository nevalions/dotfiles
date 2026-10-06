---
name: tools-audit
description: Use when auditing installed Codex skills, agents, MCP servers, plugins, hooks, or observed local tool usage. Read-only.
---

## Model selection

Default: `gpt-6.1-sol / medium` (standard). Inventory/counts only: easy; security judgment: review. Apply the task routes and runtime limits in `~/.codex/model-policy.md` when available; skill text does not switch the session model.


Audit the Codex setup without modifying it. Run:

```sh
python3 ~/.agents/skills/tools-audit/scripts/usage_scan.py --days <window>
```

The default window is 30 days. Inventory skills, custom agents, configured MCP servers, plugins and hooks. Count tool calls in local Codex JSONL sessions; report malformed or inaccessible transcripts and the limits of this evidence. Skill reads and deferred tools do not reliably prove invocation or non-use. Do not expose credentials, prompts, tool arguments, or conversation text.

Report duplicated names, dangling symlinks, missing dependencies, large instruction files, and rarely observed tools. Rank actionable findings with evidence. Context-cost estimates are approximate; explicit-only skills are omitted from implicit selection. Recommend changes, leave cleanup to an explicit user request.
