# ~/.config/herdr/config.toml

[Herdr](https://herdr.dev) — terminal workspace manager for AI coding agents.
Server/client split: a headless server owns the panes, clients attach to it.

## Install herdr

Not in the Arch repos, and no package manager owns it: herdr is a single static
binary that lands in `~/.local/bin/herdr`. Two routes to the same release asset.

```bash
# Upstream one-liner. Resolves the platform asset from a manifest and moves it
# into $HERDR_INSTALL_DIR (default ~/.local/bin), then chmod +x.
curl -fsSL https://herdr.dev/install.sh | sh

# Or by hand — same asset, no remote script in the shell.
curl -fsSL -o ~/.local/bin/herdr \
  https://github.com/ogulcancelik/herdr/releases/latest/download/herdr-linux-x86_64
chmod +x ~/.local/bin/herdr
```

Also packaged as `brew install herdr` and `mise use -g herdr`.

Neither route verifies what it downloaded: upstream ships no checksum or
signature beside these binaries, so there is nothing to check against. The
by-hand form at least keeps a remote script out of the shell and names the exact
asset. Worth knowing that the plugins are stricter than the app here — each one
verifies a SHA-256 from its own release before installing.

Upgrades come from herdr itself, no reinstall:

```bash
herdr update                # fetch and install the latest
herdr update --handoff      # and hand the live session over to the new binary
herdr --version
```

## Install this config

```bash
cd ~/dotfiles && stow herdr
herdr config check          # validate config.toml
```

`~/.config/herdr/` also holds runtime state herdr writes itself (`herdr*.log`,
`session.json`, `*.sock`) and the managed plugin installs under `plugins/github/`.
Only `config.toml` and the per-plugin files under `plugins/config/` are stowed —
stow folds per file, so the logs, sockets and downloaded binaries stay out of the
repo while the configs beside them are tracked.

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
herdr server reload-config  # or prefix+alt+r inside herdr
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
| `prefix Alt+r` | reload config |
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
| `prefix Shift+r` | resize mode |
| `prefix e` | edit scrollback in `$EDITOR` |
| `prefix [` | copy mode |
| `prefix Tab` / `Shift+Tab` | cycle panes |
| `prefix ,` / `.` | prev / next agent |
| `prefix Alt+1..9` | focus agent row |
| `prefix o` | open notification target |
| `prefix b` | toggle sidebar |
| `prefix Alt+g` | lazygit popup |
| `prefix Alt+k` | k9s popup |
| `prefix r` | reviewr diff sidebar (toggle) |
| `prefix f` | file viewer, split beside the pane |
| `prefix Alt+f` | file viewer, own tab |
| `prefix Shift+l` | apply workspace layout (plugin binding) |

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

## Review sidebar and file viewer

Two more plugins, both Rust TUIs that herdr opens in a pane:

```bash
herdr plugin install persiyanov/herdr-reviewr
herdr plugin install smarzban/herdr-file-viewer
```

| Plugin | id | Purpose |
| --- | --- | --- |
| [herdr-reviewr](https://github.com/persiyanov/herdr-reviewr) | `persiyanov.reviewr` | Read the agent's diff beside the chat, comment on lines, send the notes back |
| [herdr-file-viewer](https://github.com/smarzban/herdr-file-viewer) | `herdr-file-viewer` | Git-aware read-only file tree and preview |

Configs are stowed from this repo at
`plugins/config/persiyanov.reviewr/config.toml` and
`plugins/config/herdr-file-viewer/config.toml`, keyed by plugin id so they
survive an uninstall/reinstall.

Both install a prebuilt binary from the matching GitHub release and verify its
SHA-256; file-viewer falls back to `cargo` on any miss. The checksum ships from
the same release as the binary, so it covers transport, not a compromised
release — reinstalls are worth a glance at the upstream diff.

Keys are bound here in `config.toml`, not in the plugin manifests:

```toml
[[keys.command]]
key = "prefix+r"
type = "plugin_action"
command = "persiyanov.reviewr.toggle"   # <plugin_id>.<action_id>
```

List the ids with `herdr plugin action list`. Two gotchas:

- **reviewr rejects a config file whole.** One unknown key or bad value
  invalidates every key (`CFG-WHOLE-FILE`) and the sidebar then refuses to do any
  review work, showing the error instead. file-viewer is the opposite — a bad
  file silently falls back to defaults, flagged in its `?` overlay.
- **file-viewer's tree width takes two keys.** `tree_width` (percent) and
  `tree_max_cols` (hard column cap) both apply and the *smaller* wins, so raising
  only `tree_width` appears to do nothing.

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
