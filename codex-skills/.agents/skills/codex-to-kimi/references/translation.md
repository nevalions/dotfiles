# Translation reference

Use only the sections relevant to the repository. Verify version-dependent fields in current official documentation or `kimi --help` before generating runtime configuration. Do not assume a Codex feature has a Kimi equivalent. Facts below reflect the Kimi Code CLI documentation as of 2026-11.

## Instructions

Kimi reads workspace instruction files as reference data (not as a system-prompt override):

- Project level: `AGENTS.md` or `.kimi-code/AGENTS.md` in the project root (nearest directory containing `.git`, searching upward from the working directory). Nested-directory AGENTS.md files apply when tools access paths under them.
- User level: `~/.kimi-code/AGENTS.md` (moves with `KIMI_CODE_HOME`), and the cross-tool `~/.agents/AGENTS.md` in the real OS home.

There is no AGENTS.override.md and no combined size-limit documentation; translate an override file by merging its content into that directory's AGENTS.md, or into `.kimi-code/AGENTS.md` when the Codex tree must stay untouched. State the precedence change in the report.

`$KIMI_CODE_HOME/SYSTEM.md` fully replaces the main agent's system prompt while it exists and is non-empty. Do not create it as a side effect of a repository migration; it is machine-level main-agent customization, outranks user/project agent files for the default prompt, and is rendered with template variables (`${base_prompt}`, `${agents_md}`, `${skills}`, `${cwd}`, ...).

## Skills

Kimi skills use the same on-disk convention Codex does: directory form `<name>/SKILL.md` (recommended, supporting files alongside) or flat `<name>.md` directly in a skills directory. Both register.

- Directory-form `SKILL.md` requires YAML frontmatter with both `name` and `description`; omitting either fails parsing. Flat form falls back to the filename and first body line.
- Supported frontmatter: `type` (`prompt` default, `inline`, `flow` for manual invocation only), `whenToUse` (also `when-to-use`/`when_to_use`), `disableModelInvocation`, `arguments` (named `$<name>` params). Unknown fields are ignored: Codex- or Claude-style fields such as `model`, `allowed-tools`, `context`, `hooks`, `argument-hint` are not enforceable. Express argument semantics with `$ARGUMENTS`/`$0`/`$1`/`$<name>` and `${KIMI_SKILL_DIR}` in the body instead.
- Locations by scope (more specific wins): project `.kimi-code/skills/` and `.agents/skills/`; user `~/.kimi-code/skills/` and `~/.agents/skills/`; extra via top-level `extra_skill_dirs` in config.toml; built-in last.
- Invocation: `/skill:<name>` (with arguments) manually; the model invokes automatically from `description`/`whenToUse` unless `disableModelInvocation: true` or `type: flow`. Nesting limit: 3 levels.

A skill shared at `~/.agents/skills/<name>` works in Codex and Kimi with no copy. Adjust only unsupported frontmatter and tool-name references.

## Agents

Kimi discovers custom agents as Markdown files with YAML frontmatter; each file is one agent, the body is its system prompt:

- Frontmatter fields: `name` (kebab-case, defaults to filename), `description` (required, guides delegation), `whenToUse`, `override` (may replace a same-name built-in agent), `tools` (allowlist, e.g. `Read`, `Bash`, `mcp__github__*` globs; omit or `*` for all, `[]` for none), `disallowedTools` (deny list applied after), `subagents` (delegation allowlist; default inherited built-in set).
- Locations: user `~/.kimi-code/agents/` and `~/.agents/agents/`; project `.kimi-code/agents/` and `.agents/agents/`; extra via `extra_agent_dirs`; plugin agents last. Project files in untrusted repositories are prompt configuration and can take over same-name built-ins with `override: true` — review before running.
- Built-in sub-agents: `coder` (general, edits and commands), `explore` (read-only search/reading), `plan` (read-only planning, no shell). Built-ins cannot dispatch further sub-agents.
- Template variables in the body: `${base_prompt}` (embed the effective default prompt), `${plugin_sections}`, `${var}` context values. A body without `${base_prompt}` or `${plugin_sections}` owns the entire prompt and excludes plugin instructions.
- Launch selection: `kimi --agent <name>` or `kimi --agent-file <path>` (highest priority, current launch only); `--agent-file` cannot be combined with `--agent`, and neither works with `--session`/`--continue`. The bound agent is fixed at session creation.
- Sub-agent permissions inherit from the main Agent ("always allow" rules propagate); the Agent tool itself is allowed by default.

Translate Codex `.toml` agent/profile files into this Markdown format. There is no per-agent `model` field: `model`/`model_reasoning_effort`-style fields from other tools are ignored, so record model intent as guidance in the body and select via runtime controls (`default_model` in config.toml, the session picker, or `--agent` with a wrapper launch).

## Model and effort selection

1. Inventory Codex defaults (profiles, model-policy.md, per-agent model fields) only within the authorized scope. Preserve explicit user-selected models/effort and existing Kimi settings unless changes are requested.
2. Kimi runtime controls: `default_model` (must exist in `[models]`), model tables under `[models."<id>"]` with provider, capabilities, `support_efforts`, and `default_effort`; `[thinking] enabled/effort`. Efforts are `low`, `high`, `max` where the model declares them in `support_efforts`. The picker and `/model` switch at runtime; config sets defaults.
3. Classify the actual work and map Codex intent, not literal IDs: mechanical/exact work → low effort on an adequate model; bounded fixes and scoped prose → high; hardest architecture, subtle security reasoning, or demonstrated reasoning limits → max (or the strongest configured model). Validate against the actual configured catalog; a catalog entry is not a successful inference call.
4. Record source/workflow, selected model/effort, rationale, escalation trigger, fallback, and enforcement status (recommended vs configured vs runtime-verified). Mixed workflows get stage-specific routes.
5. Put a concise default/escalation note in each migrated skill/agent body and keep the shared catalog in one policy file. Never manufacture frontmatter fields to simulate enforcement, and never silently replace an explicit user choice.

## MCP

Kimi writes MCP configuration to `mcp.json` (JSON, not TOML), at two levels:

- User: `~/.kimi-code/mcp.json` (moves with `KIMI_CODE_HOME`).
- Project: `.kimi-code/mcp.json` in the project root, gated by workspace trust: stdio servers in an untrusted folder execute commands only after trust is granted; headless runs keep project servers disabled unless the workspace is already trusted (`KIMI_CODE_TRUST_WORKSPACE=1` for one process, or `[workspace] require_trust = false` globally, which lowers security for every workspace).

Structure:

```json
{
  "mcpServers": {
    "docs": {
      "command": "docs-mcp",
      "args": ["--read-only"],
      "env": { "DOCS_TOKEN": "..." }
    },
    "remote": {
      "url": "https://remote.example/mcp",
      "bearerTokenEnvVar": "REMOTE_TOKEN"
    },
    "legacy": {
      "transport": "sse",
      "url": "https://legacy.example/sse"
    }
  }
}
```

- stdio entries: `command`/`args`/`env`/`cwd`; `environment_id` runs the server in a named remote environment declared in `[environments]` in config.toml.
- HTTP entries: `url` plus `headers` / `bearerTokenEnvVar`. Legacy SSE requires explicit `"transport": "sse"`.
- Optional: `enabled`, `deferred` (experimental on-demand tool loading; requires the `tool-select` experimental flag and a model with `dynamically_loaded_tools`), `startupTimeoutMs`, `toolTimeoutMs`, `enabledTools`, `disabledTools`.
- MCP tools are named `mcp__<server>__<tool>`; pre-configure permanent allow/deny rules with `[[permission.rules]]` patterns such as `mcp__github__*` in config.toml. Prefer `bearerTokenEnvVar` over literal `Authorization` headers; never write resolved tokens into tracked files.

Same-name project entries override user entries. Adding or editing servers mid-session does not register them in open sessions; new sessions pick them up. OAuth-based servers authorize via `/mcp-config login <server>`. `/mcp-config` manages entries interactively; `/mcp` shows live connection status.

A config parses without proving command availability, network access, credentials, or connectivity. Redact secrets from output and diff; only connect or authenticate when authorized.

## Hooks, permissions, and memory

Kimi hooks are declared in `config.toml` as `[[hooks]]` with `event` (e.g. `PreToolUse`), `matcher` (e.g. `Bash`), `command`, and `timeout`. Hook payloads, working directory, and environment differ from Codex hooks: verify semantics before adapting, never execute an imported hook as a validation step, and never broaden approvals as a side effect.

Permissions: `default_permission_mode` (`manual`, `yolo`, `auto`), per-call approval dialogs with "Approve for this session", and permanent `[[permission.rules]]` with `decision`/`pattern` (`*` and `**` wildcards). "Ask When Needed" mode auto-approves MCP calls — only for fully trusted servers. Sub-agents inherit the main Agent's rules.

Memory plugins and external trackers (Beads, claude-mem) keep their own stores; do not dump conversation history or credentials into AGENTS.md. Reference the shared tracker and report runtime-only context as unavailable.

## Installation discovery and invocation

- User-level skills/agents under `~/.agents/` are meant to be shared across tools and commonly deployed as a Stow directory link (`~/.agents/skills -> <dotfiles>/.agents/skills`). Kimi resolves skill files through the link normally; individual broken symlinks or same-name duplicates across scopes are the usual failure mode.
- Project-level skills/agents load automatically from the discovered project root; changes reload the catalog, but a fresh session is the reliable verification target.
- Verify discovery with `/skills` (and `/agents` where available) in a new session: expected names, resolved paths, enabled state, load errors. Explicit-only skills (`type: flow`, `disableModelInvocation: true`) appear in the selector but are not auto-invoked.
- Report file validation, runtime discovery, explicit selection, and MCP connectivity separately.

## Official sources

- [Agents and sub-agents (agent files, SYSTEM.md, instruction files)](https://www.kimi.com/code/docs/en/kimi-code-cli/customization/agents.html)
- [Agent Skills (format, locations, invocation)](https://www.kimi.com/code/docs/en/kimi-code-cli/customization/skills.html)
- [Configuration files (config.toml field reference)](https://www.kimi.com/code/docs/en/kimi-code-cli/configuration/config-files.html)
- [Model Context Protocol (mcp.json, transports, permissions)](https://www.kimi.com/code/docs/en/kimi-code-cli/customization/mcp.html)
- [Hooks](https://www.kimi.com/code/docs/en/kimi-code-cli/customization/hooks.html)
- [Plugins](https://www.kimi.com/code/docs/en/kimi-code-cli/customization/plugins.html)
- [Providers and models](https://www.kimi.com/code/docs/en/kimi-code-cli/configuration/providers.html)
- [Environment variables and data locations](https://www.kimi.com/code/docs/en/kimi-code-cli/configuration/env-vars.html)
