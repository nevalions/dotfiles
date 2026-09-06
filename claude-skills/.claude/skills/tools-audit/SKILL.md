---
name: tools-audit
description: "Audit the Claude Code setup: which skills, agents, plugins, MCP servers and hooks exist, what they cost in context, and which are stale or never used (usage counted from session transcripts)"
disable-model-invocation: true
argument-hint: "[--days N]"
---

Audit the installed skills, agents, plugins, MCP servers and hooks, and report what is stale, duplicated, or draining context. Read-only: recommend, do not delete.

## 1. Measure

Run the scanner and read its output in full:

```bash
python3 ~/.claude/skills/tools-audit/scripts/usage_scan.py $ARGUMENTS
```

It inventories `~/.claude` and `~/.claude.json`, counts every tool, skill and agent invocation across all session transcripts, and marks obvious problems inline (`<- never used`, `<- never dispatched`, `<- missing`, dangling symlinks, stale project entries, oversized skills).

Then look at what the scanner cannot see:
- Repo-level `.claude/{skills,commands,agents}` and `.mcp.json` under `~/code` and `~/ansible`: names that shadow a global skill, references to servers or tools that no longer exist (grep for old MCP server names, retired repos, retired commands).
- `AGENTS.md` / `CLAUDE.md` instructions that mandate a tool the transcripts show is never called.
- Plugin metadata that is always loaded: each enabled plugin's skill and command descriptions sit in every session's skill list; a plugin with many entries and zero calls is the single biggest saving.

## 2. Judge

Cost is what is loaded every session (skill and command descriptions, agent descriptions, MCP tool names, hook processes per tool call, context injected at session start). Value is invocations. Weigh them per item and rank findings by tokens saved per session, then by per-call latency. Overlap counts too: several skills with near-identical descriptions dilute triggering even when each is cheap.

Keep in mind what does not cost context: skills with `disable-model-invocation: true` (loaded only when the user invokes them) and MCP tools behind deferred loading (only names are loaded until ToolSearch fetches a schema).

## 3. Report

- Ranked list of stale or duplicated items, each with the evidence (calls / dispatches / missing file) and the concrete action.
- What is healthy and should stay, in one line, so the user is not tempted to over-prune.
- A short table of estimated tokens recoverable per session start.
- Open decisions (an item that is costly but might be valued) separately from clear deletions.

Do not change anything in this skill. The user decides; the cleanup is a follow-up they ask for explicitly.
