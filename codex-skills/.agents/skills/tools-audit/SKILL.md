---
name: tools-audit
description: Audit installed Codex skills, agents, MCP servers, plugins and hooks,
  with observed tool usage from local session transcripts. Read-only.
---

Audit the Codex setup without modifying it. Run:

```sh
python3 ~/.agents/skills/tools-audit/scripts/usage_scan.py --days <window>
```

The default window is 30 days. Inventory skills, custom agents, configured MCP servers, plugins and hooks. Count tool calls in local Codex JSONL sessions; report malformed or inaccessible transcripts and the limits of this evidence. Skill reads and deferred tools do not reliably prove invocation or non-use. Do not expose credentials, prompts, tool arguments, or conversation text.

Report duplicated names, dangling symlinks, missing dependencies, large instruction files, and rarely observed tools. Rank actionable findings with evidence. Context-cost estimates are approximate; explicit-only skills are omitted from implicit selection. Recommend changes, leave cleanup to an explicit user request.
