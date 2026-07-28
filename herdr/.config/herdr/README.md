# ~/.config/herdr/config.toml

[Herdr](https://herdr.dev) — terminal workspace manager for AI coding agents.
Server/client split: a headless server owns the panes, clients attach to it.

## Install

```bash
cd ~/dotfiles && stow herdr
herdr config check          # validate config.toml
```

`~/.config/herdr/` also holds runtime state herdr writes itself (`herdr*.log`,
`session.json`, `*.sock`). Only `config.toml` is stowed — stow folds per file, so
the logs stay out of the repo.

Shell completions:

```bash
herdr completion zsh > ~/.local/share/zsh/site-functions/_herdr
```

## Run

```bash
herdr                       # launch or attach to the persistent session
herdr --session work        # named persistent session
herdr --remote nuc95060     # attach to a remote herdr server over ssh
herdr status                # client + server status
herdr server stop
```

## Reload config

```bash
herdr server reload-config  # or prefix+shift+r inside herdr
```

## Keys

Prefix is `Ctrl+a`, same as tmux.

Two consequences: `Ctrl+a` no longer reaches the shell as readline
beginning-of-line inside a herdr pane (herdr has no send-prefix binding — use
`Home`), and herdr and tmux must not be nested, because the outer one swallows
every `Ctrl+a`.

| Key | Action |
| --- | --- |
| `prefix ?` | help |
| `prefix s` | settings |
| `prefix q` | detach |
| `prefix Shift+r` | reload config |
| `prefix w` | workspace picker |
| `prefix g` | goto |
| `prefix Shift+n` | new workspace |
| `Ctrl+Alt+p` / `Ctrl+Alt+n` | prev / next workspace (no prefix) |
| `prefix Shift+1..9` | switch workspace by index |
| `prefix Shift+w` / `Shift+d` | rename / close workspace |
| `prefix Shift+g` | new git worktree |
| `prefix c` | new tab |
| `prefix p` / `n` | prev / next tab |
| `prefix 1..9` | switch tab by index |
| `prefix Shift+t` / `Shift+x` | rename / close tab |
| `prefix h j k l` | focus pane (vim motions) |
| `prefix Shift+h j k l` | swap pane in that direction |
| `prefix v` / `-` | split vertical / horizontal |
| `prefix x` | close pane |
| `prefix z` | zoom pane |
| `prefix r` | resize mode |
| `prefix e` | edit scrollback in `$EDITOR` |
| `prefix [` | copy mode |
| `prefix Tab` / `Shift+Tab` | cycle panes |
| `prefix ,` / `.` | prev / next agent |
| `prefix Alt+1..9` | focus agent row |
| `prefix o` | open notification target |
| `prefix b` | toggle sidebar |
| `prefix Alt+g` | lazygit popup |
| `prefix Alt+k` | k9s popup |

Copy mode (`prefix [`): `h j k l`, `w b e`, `{ }`, `Ctrl+u` / `Ctrl+d` to move,
`/` or `?` to search then `n` / `N`, `v` or `Space` to select, `y` or `Enter` to
copy, `q` or `Esc` to leave.

Bindings accept a list, so an action can have a prefix binding and a direct
chord: `focus_pane_left = ["prefix+h", "ctrl+alt+h"]`. `ctrl+alt` is the one
modifier family terminals and desktop environments leave alone.

## Project layouts (the tmuxinator equivalent)

herdr core has no layout file. Declarative layouts come from
[herdr-plugin-workspace-manager](https://github.com/razajamil/herdr-plugin-workspace-manager),
installed here:

```bash
herdr plugin install razajamil/herdr-plugin-workspace-manager
herdr plugin list
```

Layouts live in `plugins/config/herdr-plugin-workspace-manager/config.yml`,
stowed from this repo alongside the tmuxinator YAMLs it replaces. Currently
mapped: `news-backend`, `news-frontend`, `statsboard`, plus trimmed `hotfix`
and `docs` variants routed by branch prefix.

```bash
# validate after editing config.yml
herdr plugin action invoke validate --plugin herdr-plugin-workspace-manager
# apply a layout to the current workspace by hand
herdr plugin action invoke apply --plugin herdr-plugin-workspace-manager
# results are async — read them here
herdr plugin log list --plugin herdr-plugin-workspace-manager --limit 1
```

Differences from tmuxinator worth knowing:

- **Trigger.** Layouts apply on *worktree creation* for a mapped repo, not on a
  `tmuxinator start <project>` command. The repo's main checkout is never
  touched — only linked worktrees.
- **`prefix+Shift+l` applies a layout** (the plugin's own binding) and *rebuilds
  the first tab*, taking its panes and processes with it. Safe on a fresh
  worktree, destructive on one with live work. herdr's `swap_pane_*` were moved
  to `Ctrl+Alt+hjkl` to keep out of its way.
- **No `>-` block scalars.** The plugin's YAML parser rejects them; use a
  quoted one-line string.
- **Per-environment variants** (the old `-lo` / `-spb` split) can't both be a
  repo default. `news-backend` defaults to `lo`; `news-backend-spb` exists as a
  layout to apply by hand.

Beyond the plugin, workspaces/tabs/panes are fully scriptable — `herdr workspace
create`, `herdr tab create`, `herdr pane split`, `herdr pane run` — see
`herdr api schema`.

## Cleanup

```bash
herdr-workspace-manager remove-gone --dry-run  # worktrees whose upstream is gone
herdr-workspace-manager remove-gone
```

## Notes

- Theme is `catppuccin` with a `#89b4fa` accent, matching tmux, nvim and kitty.
- Toasts render in-app (`ui.toast.delivery = "herdr"`); set `"system"` for desktop
  notifications, `"off"` to silence them.
- Worktrees are created under `~/.herdr/worktrees`.
- `allow_nested = false` — start a workspace or tab instead of a herdr inside herdr.
- Full option reference: `herdr --default-config`.
