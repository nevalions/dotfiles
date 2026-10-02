---
name: claude-to-codex
description: Use when adding or refreshing Codex support in a repository with Claude Code instructions, skills, commands, agents, hooks, plugins, or MCP configuration while retaining the Claude setup.
---

## Model selection

Default: `gpt-6.1-sol / medium` (standard). Inventory or unchanged sync: easy; permission/model semantic conflicts: review. Apply the task routes and runtime limits in `~/.codex/model-policy.md` when available; skill text does not switch the session model.


# Claude to Codex

Add a Codex companion to an existing Claude Code repository. Preserve Claude files and behavior; translate intent rather than claiming identical runtime behavior.

## Scope and discovery

A request to migrate or sync authorizes local companion files and validation. An audit request is read-only. It does not authorize global configuration changes, installing dependencies, executing imported hooks, MCP login, commits, pushes, or publishing. Follow the repository's worktree and tracker rules.

1. Confirm the target repository from context. Ask for its path only if ambiguous. Check applicable AGENTS.md instructions and Git status; preserve unrelated work.
2. Inventory tracked and relevant untracked Claude files, including ignored local configuration, without printing secrets. Start with `rg --files --hidden` and targeted directory listings; exclude Git internals, dependencies, and generated output. Inspect root/nested CLAUDE.md, .claude/CLAUDE.md, CLAUDE.local.md, .claude/{skills,commands,agents}, settings files, .mcp.json, and repository plugin manifests. Follow referenced files and symlinks without modifying their targets.
3. Inventory existing AGENTS.md/AGENTS.override.md, .agents/skills, .codex/config.toml, and installed plugin equivalents. Global ~/.claude data is outside a repository migration unless explicitly included. Never dump ~/.claude.json or environment values.
4. Inventory model and reasoning intent in settings, profiles, skill/command frontmatter, agent definitions, and task/delegation instructions. Include workflows without explicit models.
5. Record a source-to-destination plan, existing conflicts, imported dependencies, model routes, and gaps. For ordinary migrations, state the plan and continue within authorization. Resolve genuine semantic conflicts with the user while completing independent parts.

## Mapping

| Source | Codex companion |
| --- | --- |
| Root or nested CLAUDE.md | AGENTS.md in the same directory; preserve scope |
| .claude/CLAUDE.md | Incorporate its repository guidance into root AGENTS.md |
| CLAUDE.local.md / local settings | Keep private; do not put local content into tracked output |
| .claude/skills/<name> | .agents/skills/<name>, including needed resources |
| .claude/commands/*.md | A Codex skill when it defines a reusable workflow |
| .claude/agents/*.md | Reusable specialist guidance; runtime agent config only if verified supported |
| .mcp.json / scoped MCP settings | Project .codex/config.toml MCP tables |
| Hooks, permissions, plugins, memory | Inspect dependencies and report/adapt supported pieces explicitly |

Read [translation.md](references/translation.md) for the relevant conversions and current documentation links before writing companions.

## Model and reasoning selection

Before writing companions, use the model-selection section of [translation.md](references/translation.md). Assess each skill, command, agent, and task category by scope, ambiguity, risk, context, tools/modalities, and validation needs. Preserve Claude model intent rather than silently dropping it or translating names literally. Choose the least costly adequate available Codex model and supported reasoning effort; respect explicit user choices and existing overrides.

Record a compact source-to-route table with model, effort, rationale, escalation trigger, and whether the choice is recommended, configured, or runtime-verified. Mixed workflows need stage-specific routes. Put a short default/escalation note in each companion skill and shared rules in one policy; do not repeat the full catalog. Use supported custom-agent/profile fields where in scope. Prose and UI metadata alone do not switch the session model or enforce delegation. Report runtime limitations without claiming automatic routing or measured savings.

## Preservation and repeat runs

Never rename, delete, rewrite, or hard-link Claude source files. Prefer adapted copies over symlinks when tool names, imports, metadata, or paths differ. Shared source references are appropriate only when they work in both runtimes and do not require editing Claude data.

Preserve existing Codex guidance, config comments, unrelated settings, and skill customizations. Reuse an existing equivalent instead of creating duplicates. Do not silently resolve contradictory instructions or same-name MCP servers with different definitions.

For imported prose, use a stable source-specific managed block, such as `<!-- claude-to-codex: CLAUDE.md begin -->` and matching `end`. Reconcile only that block on later runs, preserving surrounding edits. Inspect edits inside it before replacing; compare against source and retain intentional Codex adaptations. Malformed or duplicate markers require reconciliation, not broad replacement. MCP TOML uses `#` source comments instead. For skills, record the source in the skill body and treat existing contents as customized until compared. Do not remove companions merely because a source disappeared; report stale output.

## Validate and report

Parse changed TOML/YAML/JSON with available parsers. Check instruction scope, imports, resource paths, tool references, duplicate skill names, MCP fields, credential indirection, and model/effort pairs against the target catalog/client. Confirm every inventoried workflow has a model route, mixed tasks have escalation, and unavailable models have an explicit fallback or reported gap. Preserve user overrides; unchanged sources and availability must not churn model choices. Compare source hashes/status before and after; verify no Claude file changed, including ignored files.

Inspect the final diff for secrets, overwritten Codex content, unresolved placeholders, or expanded permission policies. Run the available skill validator for generated skills. Do not launch servers or execute imported workflows just to validate syntax. Report configured versus connected separately; project config may require trust and a fresh session. A repeat with unchanged sources should propose no edits.

Before reporting skills as usable, verify discovery in the target Codex client and environment using its skill selector or supported `skills/list` API. Compare expected names and paths, enabled state, and load errors after refreshing discovery. A valid file or successful Stow run is insufficient. Explicit-only skills can be absent from the automatic prompt list while still available in the selector. For symlinked installations and invocation checks, follow the discovery section of [translation.md](references/translation.md). If runtime verification is unavailable, report the skills as installed but discovery unverified, with the concrete remaining check.

Finish with changed paths, reused equivalents, conflicts/gaps, checks actually run, model routes and their enforcement status, and any user action needed. Do not claim hooks, memory, MCP authentication, or agent behavior transferred without evidence.
