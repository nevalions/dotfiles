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

Prefix is `Ctrl+b`. tmux keeps `Ctrl+a`, so the two nest without collisions.

| Key | Action |
| --- | --- |
| `prefix ?` | help |
| `prefix s` | settings |
| `prefix q` | detach |
| `prefix Shift+r` | reload config |
| `prefix w` | workspace picker |
| `prefix g` | goto |
| `prefix Shift+n` | new workspace |
| `prefix Shift+h` / `Shift+l` | prev / next workspace |
| `prefix Shift+1..9` | switch workspace by index |
| `prefix Shift+w` / `Shift+d` | rename / close workspace |
| `prefix Shift+g` | new git worktree |
| `prefix c` | new tab |
| `prefix p` / `n` | prev / next tab |
| `prefix 1..9` | switch tab by index |
| `prefix Shift+t` / `Shift+x` | rename / close tab |
| `prefix h j k l` | focus pane (vim motions) |
| `prefix v` / `-` | split vertical / horizontal |
| `prefix x` | close pane |
| `prefix z` | zoom pane |
| `prefix r` | resize mode |
| `prefix e` | edit scrollback |
| `prefix Tab` / `Shift+Tab` | cycle panes |
| `prefix ,` / `.` | prev / next agent |
| `prefix Alt+1..9` | focus agent row |
| `prefix o` | open notification target |
| `prefix b` | toggle sidebar |
| `prefix Alt+g` | lazygit popup |
| `prefix Alt+k` | k9s popup |

## Notes

- Theme is `catppuccin` with a `#89b4fa` accent, matching tmux, nvim and kitty.
- Toasts render in-app (`ui.toast.delivery = "herdr"`); set `"system"` for desktop
  notifications, `"off"` to silence them.
- Worktrees are created under `~/.herdr/worktrees`.
- `allow_nested = false` — start a workspace or tab instead of a herdr inside herdr.
- Full option reference: `herdr --default-config`.
