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
Everything installed uses Stow with `--no-folding`, so auth files, databases,
sessions, logs and managed plugins stay outside the repo. README and installer
files are excluded from Stow. Do not stow the entire `~/.codex` directory.
Use a separate checkout per machine. Custom `CODEX_HOME` layouts need an adapted
Stow package; the installer rejects a mismatched layout.

## Migration map

| Claude | Codex counterpart |
|---|---|
| Global instructions | Native Codex global instructions, with adapted worktree and tool guidance |
| 13 dotfiles skills | Adapted skills at `~/.agents/skills`; invoke `$work <id>`, `$create <title>`, `$commit-task <id>`, `$search <topic>`, etc. |
| Explicit-only skills | `agents/openai.yaml`: `allow_implicit_invocation: false` |
| Explore, code-reviewer | Read-only TOML custom agents, inheriting the selected Codex model |
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
