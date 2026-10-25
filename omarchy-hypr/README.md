# Omarchy Hyprland overrides

This package saves the COSMIC-style bindings and their two layout modules for
an installed Omarchy desktop with Lua-based Hyprland configuration. Omarchy's
`hyprland.lua` must load `hypr.bindings` after its defaults. The separate
`hyprland/` package contains the older standalone `.conf` setup; do not install
both packages for the same desktop.

From a permanent checkout such as `~/dotfiles`, back up any existing regular
`~/.config/hypr/bindings.lua`, `cosmic_move.lua`, and `cosmic_layout.lua` files
outside `~/.config/hypr/`, then remove only those backed-up originals before
installing their links:

```bash
cd ~/dotfiles
stow --no-folding -n -v -t ~ omarchy-hypr
stow --no-folding -t ~ omarchy-hypr
hyprctl reload
hyprctl configerrors
```

Stow leaves the other Omarchy configuration files local. Avoid linking a
temporary task worktree that may later be removed.

| Shortcut | Action |
| --- | --- |
| Super+Shift+H / L | Move the focused window left / right inside its workspace; stop at the edge |
| Super+Ctrl+H / L | Switch to the previous / next existing workspace |
| Super+Ctrl+Shift+H / L | Move the focused window to the previous / next existing workspace and follow it |
| Super+N | Switch to an empty workspace |
| Super+Shift+N | Move the focused window to an empty workspace and follow it |

Existing-workspace shortcuts wrap at the ends. Arrow bindings retain their
separate movement behavior, including crossing workspaces at an edge.

The modules register the `lua:cosmic` tiling layout. To select it as the default,
add this to the local `~/.config/hypr/looknfeel.lua`:

```lua
require("hypr.cosmic_layout")
hl.config({
  general = {
    layout = "lua:cosmic",
  },
  binds = {
    allow_workspace_cycles = true,
  },
})
```

Existing per-workspace layout choices may override the default. Super+Y
switches the active workspace between COSMIC and dwindle and saves that
choice under the local Omarchy state directory. Workspace state, backups,
monitor/input preferences, themes, and compiled plugins are not part of this
package.
