# Kimi Code

Kimi Code counterpart to `codex/` and `openclaude/`. Global instructions for the
Kimi Code CLI main agent are tracked here; skills and agents are shared with the
other tools (see `codex-skills/` and `~/.agents/`).

## Install

Requires GNU Stow and Kimi Code CLI.

```sh
stow kimi
```

This links `kimi/.kimi-code/AGENTS.md` into `~/.kimi-code/AGENTS.md`. Stow folds
per entry, so Kimi Code runtime data in `~/.kimi-code/` (sessions, cache,
credentials, oauth) stays out of the repo while the instruction file is tracked.

`config.toml`, `tui.toml`, `mcp.json` and `credentials/` stay local: they hold
machine-specific OAuth bindings and runtime state, like Codex private config.
Carry portable changes into a tracked file by hand if they are needed on every
machine.

Kimi Code reads skills from `~/.agents/skills/` (already stowed from
`codex-skills/`) and from `~/.kimi-code/skills/`; custom agents from
`~/.agents/agents/` and `~/.kimi-code/agents/`. Nothing else to deploy.
