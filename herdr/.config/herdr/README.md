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

| Key                          | Action                                                            |
| ---------------------------- | ----------------------------------------------------------------- | --------------------------- |
| `prefix ?`                   | help                                                              |
| `prefix s`                   | settings                                                          |
| `prefix q`                   | detach                                                            |
| `prefix Alt+r`               | reload config                                                     |
| `prefix w`                   | workspace picker                                                  |
| `prefix g`                   | goto                                                              |
| `prefix Shift+n`             | new workspace                                                     |
| `Ctrl+Alt+p` / `Ctrl+Alt+n`  | prev / next workspace (no prefix)                                 |
| `prefix Shift+1..9`          | switch workspace by index                                         |
| `prefix Shift+w` / `Shift+d` | rename / close workspace                                          |
| `prefix Shift+g`             | new git worktree                                                  |
| `prefix c`                   | new tab                                                           |
| `prefix p` / `n`             | prev / next tab                                                   |
| `prefix 1..9`                | switch tab by index                                               |
| `prefix Shift+t` / `Shift+x` | rename / close tab                                                |
| `prefix h j k l`             | focus pane (vim motions)                                          |
| `prefix Shift+h j k l`       | swap pane in that direction                                       |
| `prefix                      | `/`-`                                                             | split vertical / horizontal |
| `prefix x`                   | close pane                                                        |
| `prefix z`                   | zoom pane                                                         |
| `prefix Shift+r`             | resize mode                                                       |
| `prefix e`                   | edit scrollback in `$EDITOR`                                      |
| `prefix [`                   | copy mode                                                         |
| `prefix Tab` / `Shift+Tab`   | cycle panes                                                       |
| `prefix ,` / `.`             | prev / next agent                                                 |
| `prefix Alt+1..9`            | focus agent row                                                   |
| `prefix o`                   | open notification target                                          |
| `prefix b`                   | toggle sidebar                                                    |
| `prefix Alt+g`               | lazygit popup                                                     |
| `prefix Alt+k`               | k9s popup                                                         |
| `prefix r`                   | reviewr diff sidebar (toggle)                                     |
| `prefix f`                   | file viewer, split beside the pane                                |
| `prefix Alt+f`               | file viewer, own tab                                              |
| `prefix Up`                  | herdr-plus: projects picker (9 projects — see below)               |
| `prefix Down`                | herdr-plus: quick actions                                         |
| `prefix Shift+l`             | apply workspace layout (plugin binding)                           |

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

- **Trigger.** Layouts apply on _worktree creation_ for a mapped repo, not on a
  `tmuxinator start <project>` command. The repo's main checkout is never
  touched — only linked worktrees.
- **`prefix+Shift+l` applies a layout** (the plugin's own binding) and _rebuilds
  the first tab_, taking its panes and processes with it. Safe on a fresh
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
herdr plugin install cloudmanic/herdr-plus     # needs a Go toolchain
```

| Plugin                                                             | id                      | Purpose                                                                              |
| ------------------------------------------------------------------ | ----------------------- | ------------------------------------------------------------------------------------ |
| [herdr-reviewr](https://github.com/persiyanov/herdr-reviewr)       | `persiyanov.reviewr`    | Read the agent's diff beside the chat, comment on lines, send the notes back         |
| [herdr-file-viewer](https://github.com/smarzban/herdr-file-viewer) | `herdr-file-viewer`     | Git-aware read-only file tree and preview                                            |
| [herdr-plus](https://github.com/cloudmanic/herdr-plus)             | `cloudmanic.herdr-plus` | Projects (fuzzy-pick a workspace template) and Quick Actions (fuzzy script launcher) |

Configs are stowed from this repo at
`plugins/config/persiyanov.reviewr/config.toml` and
`plugins/config/herdr-file-viewer/config.toml`, keyed by plugin id so they
survive an uninstall/reinstall.

reviewr and file-viewer install a prebuilt binary from the matching GitHub
release and verify its SHA-256; file-viewer falls back to `cargo` on any miss.
The checksum ships from the same release as the binary, so it covers transport,
not a compromised release — reinstalls are worth a glance at the upstream diff.
herdr-plus is compiled from the cloned source with `go build` instead, so there
is nothing to verify but also no binary to trust; its manifest mentions a
prebuilt fallback that `scripts/build.sh` does not actually implement.

**herdr-plus config sits in the managed dir like the rest**, under
`plugins/config/cloudmanic.herdr-plus/` — `projects/`, `quick-actions/` and
`worktrees/` subdirs, plus an optional `config.toml`. It only falls back to
`~/.config/herdr-plus/` when the binary runs _outside_ herdr: under herdr,
`HERDR_PLUGIN_CONFIG_DIR` is set and wins over `$XDG_CONFIG_HOME`. Since the
`prefix Up` / `prefix Down` pickers run as plugin actions, the managed dir is
the one that counts. `projects/` is stowed from this repo; `worktrees/` is
deliberately left empty — see below.

**Projects follow one of two shapes.** Panes have no per-pane cwd in herdr-plus,
only the project-level `working_dir`, so every pane `cd`s into its own directory
as part of its command. None of them start an agent or an editor.

- **back/front** — one product with two halves: tabs `code`, `run`, `cli`, each
  split into two vertical panes. `code` and `cli` are bare shells; `run` starts
  the backend and the dev server. `news-lo`, `news-spb`, `news-writer`,
  `statsboard`. The halves are separate repos under `~/code` for `news-*` and
  subdirectories of one checkout for `statsboard` — the layout is identical
  either way.
- **tab-per-project** — a family of independent apps: the tab is the app, the
  panes are `code` and `run`. `portals` (Astro sites, no backend at all) and
  `scrimmage-line` (engine, UI, trainer). The four streaming repos started here
  and moved out to one project each — `stream-cms`, `stream-ui`, `uploader`,
  `stream-controller` — once it was clear you work on one of them at a time.

**A pane per half, only when there are two halves.** The test is whether the
half runs a process of its own, not whether it has its own directory. The Go
services carry a frontend but `go:embed` it into the same binary, and
`stills-bank` serves its htmx UI from the same FastAPI app — neither has a
second process to face the server or a second command to type, so `stream-cms`,
`stream-ui`, `uploader`, `stream-controller` and `stills-bank` are one pane per
tab. `news-writer/frontend` has no `AGENTS.md` of its own but does run its own
Vite server, so it stays a half. `kube-lvl47` fits no
shape at all — nothing runs locally, so it is a repo shell, two `flux --watch`
panes and `k9s`.

**Pane labels follow the tab.** herdr-plus takes an undocumented `label` per
pane and renames the pane with it. Where the tab is the role (`code`, `run`,
`cli`) the label names the half — `back`, `front` — so a lone pane gets no
label, the tab name already being the whole story. Where the tab is the repo
(`portals`, `scrimmage-line`) the label names the role instead.

**Dev ports are tracked in `~/code/PORTS.md`.** Several workspaces are usually
open at once, and a taken port either kills the pane (uvicorn, Go) or silently
moves (Vite, Astro). Pin new ones there before adding a project.

**Two plugins answer `worktree.created`.** workspace-manager applies layouts from
its `config.yml`, and herdr-plus would apply layouts from its own `worktrees/`
subdir on both `worktree.created` and `worktree.opened`. That subdir is empty on
purpose, so herdr-plus no-ops and only workspace-manager acts.

The division, and why: workspace-manager owns **worktree** layout because it
routes by branch name (`worktreePattern: "{bugfix,hotfix}/*"` → the trimmed
`hotfix` layout), and herdr-plus matches on repo name only — one layout per
repo, no branch routing. herdr-plus owns **on-demand start**, the tmuxinator
`start` verb workspace-manager has no answer for, plus Quick Actions.

Putting files in herdr-plus's `worktrees/` breaks that: both plugins then fire
on the same event with no defined ordering, and herdr-plus skips a workspace
that already has tabs, so the winner is whichever runs first. The empty
directory is the boundary.

Known cost of the split: workspace-manager only hooks `worktree.created`, never
`worktree.opened`, so _reopening_ an existing worktree gets no layout. Apply one
by hand with `prefix+Shift+l` — cheaper than giving up branch routing.

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
  `tree_max_cols` (hard column cap) both apply and the _smaller_ wins, so raising
  only `tree_width` appears to do nothing.

## Cleanup

```bash
herdr-workspace-manager remove-gone --dry-run  # worktrees whose upstream is gone
herdr-workspace-manager remove-gone
```

## Notes

- Theme is `catppuccin`, matching tmux, nvim and kitty. The accent is the one
  deliberate departure: `#fab387` (peach) rather than the `#89b4fa` blue used
  elsewhere. The focused pane's border and title are drawn in the accent, and
  both the file viewer and reviewr render blue chrome of their own, so a blue
  accent competed with the panes it had to stand out against.
- `[theme.custom]` overrides single palette tokens on top of the base theme.
  Only `overlay0` is set, dropped to `#45475a` (surface1): it colours _unfocused_
  pane borders, so darkening it widens the gap against the accent. Both halves of
  that contrast matter, because while you are typing the border colour is the
  only focus cue — herdr's DIM wash over unfocused panes applies solely outside
  terminal mode.
- Toasts render in-app (`ui.toast.delivery = "herdr"`); set `"system"` for desktop
  notifications, `"off"` to silence them.
- Worktrees are created under `~/.herdr/worktrees`.
- `allow_nested = false` — start a workspace or tab instead of a herdr inside herdr.
- Full option reference: `herdr --default-config`.
