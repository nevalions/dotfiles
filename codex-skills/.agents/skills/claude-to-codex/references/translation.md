# Translation reference

Use only the sections relevant to the repository. Verify version-dependent fields in current official documentation or local `codex --help` before generating runtime configuration. Do not assume a Claude feature has a Codex equivalent.

## Instructions

Preserve task commands, conventions, constraints, and nested overrides. Keep nested rules in their directory; do not flatten them into root rules. Check AGENTS.override.md, which can take precedence over AGENTS.md. Codex reads one instruction file per directory, with a combined size limit; report guidance that would be shadowed or truncated.

Claude `@path` imports are not automatically equivalent to Codex imports. Read imported guidance, resolve relative paths from its source, and either incorporate the necessary text or explicitly instruct Codex to read the referenced file at the right time. Do not leave essential rules accessible only through an assumed import mechanism. Preserve links to shared docs when useful; avoid copying private imports into tracked files.

Do not symlink AGENTS.md to CLAUDE.md when adaptation or existing Codex guidance is required. A configured `CLAUDE.md` fallback can be an alternative when requested, but it does not merge with an existing AGENTS.md in that directory. Do not change global fallback settings as a side effect of repository migration.

## Skills, commands, agents, and plugins

Codex repository skills live under `.agents/skills/<name>/SKILL.md`. Include YAML `name` and `description`. Keep needed scripts, templates, assets, and references together. Resolve paths relative to each source file; dependencies outside the source skill directory may need companion copies or corrected references. Never assume copying the skill folder preserves `../shared/` references.

Translate Claude Read/Grep/Glob/Edit/Bash and AskUserQuestion instructions into available Codex read/search/edit/shell/input capabilities. Describe the desired operation when no stable tool name exists. Translate Task/subagent instructions only where delegation exists and is authorized; otherwise perform the scoped work directly. Match MCP tool intent to tools actually exposed by the target server; do not mechanically rename namespaces.

Preserve workflow intent and execution gates. Claude-only frontmatter such as allowed-tools, model, context, hooks, and argument-hint must be checked for target support; unsupported fields are not enforceable by prose. Express useful argument semantics in the skill body. Avoid replacing a supported field with a weaker behavior without reporting the difference.

Convert `/ship` references into invocation of the corresponding migrated skill when available. Commands or agents without a reusable workflow may remain referenced guidance with a reported gap. A specialist skill does not automatically create an isolated runtime agent. Check collisions before naming converted command/agent skills.

Inspect plugin manifests and relative resources if the repo uses plugins. An already installed Codex counterpart may satisfy the need. Do not copy a Claude manifest into a Codex plugin and claim it works. Verify manifest layout and package dependencies before creating an actual Codex plugin.

### Installation discovery and invocation

Check the installed layout in the actual client environment, including remote hosts and any custom configuration home. Verify the target version's discovery behavior rather than assuming a path or symlink is supported. In the observed Codex CLI 0.160.0 installation, Stow `--no-folding` produced individual `SKILL.md` symlinks that were skipped; linking the entire `.agents/skills` root to directories containing regular skill files exposed all migrated skills. For this layout, keep Codex runtime/config directories unfolded and stow the skills package separately with folding. Migrate only managed links and empty directories; preserve unrelated skills and files. Recheck on other versions instead of treating this workaround as universal.

Refresh the skill selector or, where supported, call `skills/list` with the target working directory and `forceReload: true`. Check every expected skill's name, resolved source/path, enabled state, and reported load errors. `codex debug prompt-input` alone is insufficient: `policy.allow_implicit_invocation: false` intentionally excludes explicit-only skills from the automatic prompt list. Preserve invocation policies rather than enabling implicit invocation to make that list pass.

Verify explicit selection without executing a workflow: in Codex CLI/IDE, check `/skills` or the `$skill-name` picker and the actual registered name, including plugin namespaces. Do not promise Claude-style `/skill-name` aliases. MCP servers expose tools; they do not automatically become skill commands. Report file validation, runtime discovery, explicit selection, and MCP connectivity separately. When the client UI cannot be checked, state that limitation and give the remaining selection check; do not execute imported hooks, skill workflows, or MCP actions as a discovery test.

## Model and reasoning selection

1. Within the authorized scope, inventory project defaults (and global defaults only when explicitly included), skill/command `model` frontmatter, agent settings, reasoning/budget instructions, and model choices in delegation prompts. Absence of a model still requires workload assessment. Preserve explicit user-selected Codex models and existing settings unless changes are requested.
2. Check the target client's current model picker/catalog and supported reasoning levels. For unknown model IDs, pricing, or runtime fields, consult current official OpenAI documentation. Reuse evidence from this migration; do not research every simple task again. Availability is account/client/provider-specific; a catalog entry is not a successful inference call.
3. Classify the actual work. Exact lookup, extraction, scanner execution and mechanical changes usually need an efficient model with low effort. Multi-file implementation, integration and planning need a workhorse with medium effort. Security interpretation, subtle bugs and complex review may need the workhorse at high effort. Reserve the strongest model for hardest architecture or a demonstrated reasoning limitation. File count alone and the skill name do not determine difficulty. Choose a modality/tool-capable model, including a separate image generator where needed.
4. Translate Claude Haiku/Sonnet/Opus as efficiency/balanced/deep intent, not identical capability, pricing or literal Codex IDs. Validate candidate choices for the actual workload. As of 2026-10-02, examples are `gpt-6-luna` for focused work, `gpt-6.1-sol` for implementation/review, and `gpt-6-astra` for the hardest work, only where available. These are refreshable examples, not mandatory future pins. Luna's general documented starting effort is high; lower effort is a workload-specific choice for mechanical steps, with escalation if results are inadequate.
5. Record each source/workflow, selected model and effort, rationale, escalation trigger, fallback and enforcement status. For a mixed work skill, route a fully specified edit cheaply, normal integration to a workhorse, and hard architecture to a deeper route. Escalate after inadequate reasoning; missing context, unavailable tools or command failures require fixing evidence/execution first.
6. Put a concise default and escalation note in each migrated skill, and link a shared policy for generic tasks, phases, and delegation. Claude-only `model` frontmatter or `agents/openai.yaml` does not select the parent runtime model. A skill should explain this limit rather than claim enforcement. Do not manufacture unsupported frontmatter fields.
7. Where authorized and verified supported, configure custom agents using `model` and `model_reasoning_effort`. Verify native profile syntax using the target CLI: Codex 0.160.0 uses `<name>.config.toml` loaded by `codex -p <name>`; do not blindly emit legacy profile tables. Omitted settings can inherit a costly parent, so state inheritance deliberately. Do not create an isolated specialist agent unless that behavior is intended. Preserve existing permissions, tools and user overrides.
8. Runtime selection must use an exposed supported control, the user's picker, a native profile, or an authorized child-agent override. A running skill cannot switch models merely by reading instructions. Do not spawn trivial tasks solely for savings, expand delegation authorization, or promise that less expensive models reduce token count. Report recommended versus configured versus verified behavior and any unavailable fallback explicitly. Never silently replace an explicit user choice.

Example migration assessment (target availability must be verified):

| Source/workflow | Candidate model / effort | Escalation / enforcement |
| --- | --- | --- |
| Haiku shell-history lookup | Luna low | Incident causality: Sol medium/high; skill recommendation, picker/profile applies it |
| Opus security audit agent | Sol high | Hard unresolved threat reasoning: Astra; native agent config only if verified supported |
| Mixed work skill | Luna low for mechanical edits; Sol medium for integration | Hard architecture: Sol high/Astra; phase recommendations, runtime control required |

Validate model IDs and effort together against the target catalog; parse runtime config and check actual client acceptance where possible without paid inference. A syntax check does not prove model access or quality. Check lookup, review/security, mixed-workflow and unavailable-model scenarios, verify preserved overrides, and repeat with unchanged inputs to confirm no churn. The final report includes the route table and enforcement gaps.

## MCP

Prefer project `.codex/config.toml` for repository servers. Preserve existing server definitions and unrelated config. TOML table names may need quoting. Validate the final parsed structure as well as syntax; inserting text under the wrong table changes its meaning.

For stdio, translate verified command/args/env/cwd fields. Claude `${VAR}` or `${VAR:-default}` expansion is not a portable TOML interpolation mechanism. A same-name secret reference `TOKEN=${TOKEN}` can use `env_vars = ["TOKEN"]`. A renamed reference `TOKEN=${VAULT_TOKEN}` needs a reviewed environment mapping or wrapper, such as the user's existing rbw-env helper; `env_vars = ["VAULT_TOKEN"]` alone does not rename it. Check `command -v rbw` before obtaining credentials, and hand secrets to consumers without printing or writing them into tracked files. Preserve nonsecret literal env values separately. Defaults need explicit handling rather than silent removal.

For HTTP, translate a verified URL and transport. Prefer `bearer_token_env_var` for Authorization bearer tokens and `env_http_headers` for header-to-environment mappings when supported. Keep verified nonsecret headers in `http_headers`. Do not emit `Authorization = "Bearer ${TOKEN}"` and assume expansion. URLs, args, env entries, and headers can all contain secrets; redact output and avoid embedding their literal values into companions. Legacy SSE, custom authentication, and plugin substitutions require explicit compatibility checks. Do not assume OAuth sessions transfer between clients.

Example of a same-name stdio token reference and an HTTP bearer reference:

```toml
[mcp_servers.docs]
command = "docs-mcp"
args = ["--read-only"]
env_vars = ["DOCS_TOKEN"]

[mcp_servers.remote_docs]
url = "https://docs.example.test/mcp"
bearer_token_env_var = "REMOTE_DOCS_TOKEN"
```

A config parses without proving command availability, network access, credentials, or server connectivity. List unresolved requirements; only connect or authenticate when authorized.

## Hooks, permissions, and memory

Claude permissions, settings, and lifecycle hooks do not become Codex policy by copying JSON. Verify event payloads, working directory, environment, and execution semantics before proposing an equivalent hook. Do not run imported hooks or broaden approvals. Reuse an existing repository check entry point when appropriate.

Memory plugins may expose the same backing store through MCP if supported and explicitly in scope. Do not dump conversation history, private memory, or credentials into AGENTS.md. Reference an existing shared tracker or memory source; report runtime-only context that is unavailable.

## Official sources

- [Models and workload/effort guidance](https://learn.chatgpt.com/docs/models)
- [Subagent models and reasoning configuration](https://learn.chatgpt.com/docs/agent-configuration/subagents)

- [Instruction discovery and precedence](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
- [Skill discovery, packaging, and authoring](https://learn.chatgpt.com/docs/build-skills)
- [MCP transport and environment configuration](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)
- [Codex configuration reference](https://developers.openai.com/codex/config-reference)
- [Plugin packaging](https://developers.openai.com/plugins/build/plugins)
