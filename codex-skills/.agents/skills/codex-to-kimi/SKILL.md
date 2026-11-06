---
name: codex-to-kimi
description: Use when adding or refreshing Kimi Code support in a repository or machine that has Codex instructions, skills, agents, hooks, plugins, or MCP configuration while retaining the Codex setup.
---

# Codex to Kimi

Add a Kimi Code companion to an existing Codex setup. Preserve Codex files and behavior; translate intent rather than claiming identical runtime behavior.

## Scope and discovery

A request to migrate or sync authorizes local companion files and validation. An audit request is read-only. It does not authorize global configuration changes, installing dependencies, executing imported hooks, MCP login, commits, pushes, or publishing. Follow the repository's worktree and tracker rules.

1. Confirm the target (a repository or machine-level dotfiles) from context. Ask only if ambiguous. Check applicable AGENTS.md instructions and Git status; preserve unrelated work.
2. Inventory tracked and relevant untracked Codex files, including ignored local configuration, without printing secrets. Start with `rg --files --hidden` and targeted directory listings; exclude Git internals, dependencies, and generated output. Inspect root/nested AGENTS.md, AGENTS.override.md, .codex/config.toml, .codex/agents/, ~/.codex/model-policy.md, .agents/skills, and plugin manifests or marketplaces. Follow referenced files and symlinks without modifying their targets.
3. Inventory existing Kimi equivalents: AGENTS.md and .kimi-code/AGENTS.md, ~/.kimi-code/AGENTS.md, ~/.agents/AGENTS.md, ~/.kimi-code/config.toml and tui.toml, ~/.kimi-code/agents/, ~/.kimi-code/skills/, ~/.kimi-code/mcp.json, and project .kimi-code/{skills,agents,mcp.json}. Global ~/.kimi-code and ~/.codex data are outside a repository migration unless explicitly included. Never dump credential files or environment values.
4. Inventory model and effort intent in config defaults, model-policy.md, agent/profile definitions, and task/delegation instructions. Include workflows without explicit models.
5. Record a source-to-destination plan, existing conflicts, imported dependencies, model routes, and gaps. For ordinary migrations, state the plan and continue within authorization. Resolve genuine semantic conflicts with the user while completing independent parts.

## Mapping

| Source | Kimi companion |
| --- | --- |
| Root or nested AGENTS.md | AGENTS.md in the same directory; Kimi reads it natively, preserve scope |
| AGENTS.override.md | No direct equivalent; merge into that directory's AGENTS.md or add .kimi-code/AGENTS.md, and note the precedence change |
| ~/.codex/AGENTS.md global | ~/.kimi-code/AGENTS.md global, or shared ~/.agents/AGENTS.md for cross-tool text |
| .agents/skills/<name> | Same path; Kimi scans ~/.agents/skills natively — only adjust frontmatter |
| ~/.codex/skills/<name> | ~/.kimi-code/skills/<name> (Kimi-specific user skills) |
| .codex/agents/*.toml or role files | Markdown agent files in ~/.kimi-code/agents/ or ~/.agents/agents/ (frontmatter: description, tools, disallowedTools, subagents) |
| .codex/config.toml profiles (<name>.config.toml) | No profile files; use default_model in config.toml, --agent/--agent-file at launch, or separate models tables |
| mcp_servers TOML tables | mcp.json: ~/.kimi-code/mcp.json (user) or .kimi-code/mcp.json (project, workspace-trust gated) |
| model-policy.md and per-agent model fields | Guidance only. Kimi selects model/effort at runtime (default_model, picker, effort levels); record recommendations, never claim prose enforces them |
| Codex hooks | [[hooks]] in config.toml (event/matcher/command/timeout); verify payload and semantics before adapting, do not execute imported hooks |
| Codex plugins/marketplaces | Kimi plugin manifests (skills/agents/mcp fields); verify manifest layout, never copy blindly |

Read [translation.md](references/translation.md) for the relevant conversions and current documentation links before writing companions.

## Model and effort selection

Before writing companions, use the model-selection section of [translation.md](references/translation.md). Assess each skill, agent, and task category by scope, ambiguity, risk, context, tools, and validation needs. Preserve Codex model intent (cheap mechanical → scoped → workhorse → hardest) as Kimi effort intent (low/high/max on supporting models), not literal model IDs. Respect explicit user choices and existing overrides.

Record a compact source-to-route table with model/effort intent, rationale, escalation trigger, and whether the choice is recommended, configured, or runtime-verified. Put a short default/escalation note in each companion skill; do not repeat the full catalog. Skill prose and frontmatter do not switch the session model; state the enforcement limit explicitly.

## Preservation and repeat runs

Never rename, delete, rewrite, or hard-link Codex source files. Prefer adapted copies over symlinks when tool names, metadata, or paths differ. Shared source references are appropriate only when they work in both runtimes and do not require editing Codex data.

Preserve existing Kimi guidance, config comments, unrelated settings, and skill customizations. Reuse an existing equivalent instead of creating duplicates. Do not silently resolve contradictory instructions or same-name MCP servers with different definitions.

For imported prose, use a stable source-specific managed block, such as `<!-- codex-to-kimi: AGENTS.md begin -->` and matching `end`. Reconcile only that block on later runs, preserving surrounding edits. Inspect edits inside it before replacing; compare against source and retain intentional Kimi adaptations. Malformed or duplicate markers require reconciliation, not broad replacement. mcp.json uses a `"//"` source comment key instead. For skills, record the source in the skill body and treat existing contents as customized until compared. Do not remove companions merely because a source disappeared; report stale output.

## Validate and report

Parse changed TOML/YAML/JSON with available parsers. Directory-form SKILL.md files must have both `name` and `description` frontmatter or they fail parsing. Check instruction scope, resource paths, tool references, duplicate skill names, MCP fields, credential indirection, and model/effort pairs against the target catalog/client. Confirm every inventoried workflow has a route, mixed tasks have escalation, and unavailable models have an explicit fallback or reported gap. Preserve user overrides; unchanged sources and availability must not churn model choices. Compare source hashes/status before and after; verify no Codex file changed, including ignored files.

Inspect the final diff for secrets, overwritten Kimi content, unresolved placeholders, or expanded permission policies. Do not launch servers or execute imported workflows just to validate syntax. Report configured versus connected separately; project mcp.json may require workspace trust and a fresh session. A repeat with unchanged sources should propose no edits.

Before reporting skills as usable, verify discovery in the target Kimi client: start a new session and check the `/skills` selector (or the model's skill listing) for each expected name, resolved path, and load errors. For symlinked installations, note that the user-level `~/.agents/skills` directory is commonly a Stow directory link; skill files inside it resolve normally. A valid file or successful Stow run is insufficient. `disableModelInvocation: true` or `type: flow` skills stay out of automatic invocation but remain selectable. If runtime verification is unavailable, report the skills as installed but discovery unverified, with the concrete remaining check.

Finish with changed paths, reused equivalents, conflicts/gaps, checks actually run, model routes and their enforcement status, and any user action needed. Do not claim hooks, MCP authentication, OAuth sessions, or agent behavior transferred without evidence.
