# Codex

Codex counterpart to `openclaude` and `claude-skills`. Personal instructions and
read-only custom agents are tracked here; skills live in `codex-skills`.

## Install

Requires Python 3.11+, GNU Stow, Codex, Node/npx, and Atuin for shell history.
Keep `~/.local/bin` on PATH. The installer also registers the bundled `dotfiles`
marketplace and installs Superpowers and frontend-design through Codex's plugin
CLI. Use `--skip-plugins` to install only config, agents and local skills.

```sh
python3 codex/install.py
codex mcp list
```

The installer merges `config.base.toml` with your current Codex config, preserving
existing settings, model choice, project trust, plugin settings and hook trust.
It backs up an existing regular config to `~/.codex/backups/` before replacing
it with a Stow symlink. Existing settings take precedence. Re-run it after
changing the tracked defaults; it adds new defaults without overwriting local
choices. Resolve existing skill or agent conflicts yourself; files are never
adopted over unrelated local files. Use `--check` for a Stow simulation.

`codex/.codex/config.toml` is generated, private, and Git-ignored: Codex itself
writes machine-specific state into it. Only `config.base.toml` is committed.
Codex config uses Stow with `--no-folding`, so auth files, databases, sessions,
logs and managed plugins stay outside the repo. Skills use a folded
`~/.agents/skills` directory link: Codex 0.160.0 skips individual symlinked
skill files during discovery. The installer removes old managed skill links
and empty directories before relinking them. README and installer files are
excluded from Stow. Do not stow the entire `~/.codex` directory.
Use a separate checkout per machine. Custom `CODEX_HOME` layouts need an adapted
Stow package; the installer rejects a mismatched layout.

## Execution visibility

The native CLI footer shows the current directory, model and reasoning effort,
context usage, used tokens, Git branch, and five-hour and weekly limits.
Configure its items with `/statusline`; local choices take precedence over
the tracked `tui.status_line` defaults when the installer runs. Restart the
CLI after installing to load the footer settings.

Delegation and first use of a skill get a concise announcement of the task,
owning agent, known model and effort, skill, and purpose. Unknown runtime
details are stated explicitly. Skills do not switch models, and each tool
runs in its calling agent. The footer reports session metrics; announcements
describe execution choices rather than every tool call.

## Model selection

Each local skill includes a default model/effort and escalation criteria.
`~/.codex/model-policy.md` covers generic tasks, plugin skills and delegation.
Use native profiles with the installed CLI:

```sh
codex -p easy
codex -p standard
codex -p review
codex -p deep
```

They select Luna low, Sol medium, Sol high and Astra high respectively.
The base model remains your existing choice. An active session needs a supported
runtime control or model picker; invoking a skill does not switch its model.
Model and effort choices are workload recommendations, not benchmarked optima.
`claude-to-codex` now inventories model intent and verifies target availability,
reasoning effort and runtime support before translating each workflow.

Requested commit, branch push/preparation and merge workflows delegate to one
`git-workflow` agent using Luna low. Plain requests such as "commit issue X"
and `$commit-task X` use the same route; no repeated subagent instruction is
needed. The parent keeps its model and verifies the worker's result. When the
client cannot spawn the custom role, it uses a general agent with explicit
model/effort settings and the same Git instructions. Explicit user model
choices take precedence. Conflicts and failed checks return to the parent for
deeper analysis; dependent Git stages run sequentially and stay within the
requested scope. Reload Codex after installing new agent configuration.

## Migration map

| Claude | Codex counterpart |
|---|---|
| Global instructions | Native Codex global instructions, with adapted worktree and tool guidance |
| 13 dotfiles skills | Adapted skills at `~/.agents/skills`; invoke `$work <id>`, `$create <title>`, `$commit-task <id>`, `$search <topic>`, etc. |
| Explicit-only skills | `agents/openai.yaml`: `allow_implicit_invocation: false` |
| Explore, code-reviewer | Read-only TOML custom agents: explorer uses Luna low, reviewer uses Sol high |
| bd tasks | Same `.beads/` database; no duplicate task store or task migration |
| Context7, Perplexity, Forgejo, Atuin MCP | Native Codex MCP config |
| Enabled Playwright plugin | Playwright MCP connection |
| Superpowers, frontend-design | Vendored Codex plugins installed from the local `dotfiles` marketplace |
| Herdr SessionStart hook | Existing Codex integration preserved; installed/maintained by Herdr |
| tools-audit | Native Codex inventory and local JSONL tool-usage scanner |

MCP credentials come from environment variables. For Perplexity and Forgejo,
`codex-mcp-env` also reads missing values from the matching server's `env` in
`~/.claude.json` at process startup. It supports `${VAR}` references, passes
secrets directly to the child process, and never prints or writes their values.
Environment values take precedence. On a machine without Claude, provide
`PERPLEXITY_API_KEY`, `FORGEJO_URL`, and `FORGEJO_TOKEN` through your existing
vault/environment setup. The public repo contains no tokens or private URLs.
Atuin can query existing Claude history; recording new Codex commands needs an
Atuin integration compatible with Codex, not `atuin hook claude-code`.

Claude's model names, permissions, status line, UI settings, local todos,
conversation transcripts and plugin lifecycle settings are not interchangeable
with Codex. Scheduled jobs were not found in the tracked Claude packages.
Project MCP definitions remain project-specific and are not promoted to global
configuration. Disabled Claude plugins are not enabled in Codex.

Superpowers 5.1.0 uses its upstream Codex manifest and skills. Frontend-design
uses a Codex manifest added here; its skill changes only the agent name and
license path. Both snapshots include their licenses and are tracked under
`plugin-marketplace/plugins/`; `snapshot.json` records their content hashes.
Updates are reviewed in Git, then installed by re-running the installer.
Installed plugin caches are managed by Codex outside dotfiles, rather than
Stow. Codex already supplies its own Skill Creator. Claude's clangd plugin has
no direct migration here; editor language tooling stays separate.

See the official [skills documentation](https://learn.chatgpt.com/docs/build-skills),
[MCP configuration](https://learn.chatgpt.com/docs/extend/mcp?surface=cli), and
[custom agents](https://learn.chatgpt.com/docs/agent-configuration/subagents).

## Remove

```sh
stow --no-folding -D codex codex-skills
codex plugin remove superpowers@dotfiles
codex plugin remove frontend-design@dotfiles
codex plugin marketplace remove dotfiles
```

Restore a saved config from `~/.codex/backups/` if desired. Authentication and
runtime data remain in place. Restart Codex after installing or removing MCPs.
