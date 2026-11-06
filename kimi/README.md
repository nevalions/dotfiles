# Kimi Code

Kimi Code counterpart to `codex/` and `openclaude/`. Global instructions for the
Kimi Code CLI main agent are tracked here; skills and agents are shared with the
other tools (see `codex-skills/` and `~/.agents/`).

## Install

Requires GNU Stow and Kimi Code CLI.

```sh
stow kimi
```

This links `kimi/.kimi-code/AGENTS.md` into `~/.kimi-code/AGENTS.md` and the
contents of `kimi/.kimi-code/skills/` into `~/.kimi-code/skills/`. Stow folds
per entry, so Kimi Code runtime data in `~/.kimi-code/` (sessions, cache,
credentials, oauth) stays out of the repo while the instruction file is tracked.

`config.toml`, `tui.toml`, `mcp.json` and `credentials/` stay local: they hold
machine-specific OAuth bindings and runtime state, like Codex private config.
Carry portable changes into a tracked file by hand if they are needed on every
machine.

Kimi Code reads skills from `~/.agents/skills/` (already stowed from
`codex-skills/`) and from `~/.kimi-code/skills/`; custom agents from
`~/.agents/agents/` and `~/.kimi-code/agents/`. Nothing else to deploy.

## Skills

`kimi/.kimi-code/skills/` exposes the Superpowers skill set to Kimi. Each entry
is a relative symlink into `codex/plugin-marketplace/plugins/superpowers/skills/`
— the single vendored copy that the Codex `dotfiles` marketplace installs, so
Kimi, Codex and Claude all read identical skill content. Keep the symlinks
relative: stow recreates them verbatim, and relative targets keep the repo
portable across machines and checkout locations.

When a Superpowers release adds or removes skills, mirror the change here:

```sh
cd kimi/.kimi-code/skills
for d in ../../../codex/plugin-marketplace/plugins/superpowers/skills/*/; do
  ln -sfn "${d#../../../}" "$(basename "$d")"
done
```

Kimi-only skills can live alongside the symlinks as real directories.
