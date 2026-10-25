-- Keep only your personal keybinding overrides here. Add new bindings or
-- unbind defaults before replacing them.

-- See current bindings and descriptions:
--   omarchy menu keybindings --print

-- To disable every Omarchy default binding, set this in
-- ~/.config/hypr/hyprland.lua before require("default.hypr.omarchy"), then add
-- only the bindings you want below:
--   omarchy_default_bindings = false

-- To disable all preinstalled app/webapp bindings, set:
--   omarchy_preinstalled_bindings = false

-- Add a new binding.
-- o.bind("SUPER + SHIFT + R", "SSH", "alacritty -e ssh your-server")

-- Change an existing binding by unbinding it first, then binding the key again.
-- This example changes SUPER+SPACE from the launcher to the Omarchy root menu.
-- hl.unbind("SUPER + SPACE")
-- o.bind("SUPER + SPACE", "Omarchy menu", "omarchy-menu toggle root")

-- Disable a default binding without replacing it.
-- hl.unbind("SUPER + SHIFT + B")

-- Logitech MX Keys examples:
-- o.bind("SUPER + SHIFT + S", nil, "omarchy-capture-screenshot")
-- o.bind("SUPER + H", nil, "voxtype record toggle")
-- o.bind("SUPER + PERIOD", nil, "omarchy-shell shell toggle omarchy.emojis")

-- ===========================================================================
-- COSMIC-style keybindings
--
-- Matches the COSMIC desktop defaults documented at
-- https://system76.com/support/articles/pop-cosmic-keyboard-shortcuts
--
-- COSMIC and Omarchy disagree most on SUPER + F/T/W: COSMIC spends them on
-- applications (Files, Terminal, Workspaces) where Omarchy spends them on
-- window operations (fullscreen, float, close). Following COSMIC therefore
-- means moving those window operations elsewhere, which is what most of the
-- unbinds below are for.
-- ===========================================================================

-- --- Applications ----------------------------------------------------------
hl.unbind("SUPER + T") -- was: Toggle window floating/tiling (now SUPER + G)
o.bind("SUPER + T", "Terminal", { omarchy = "terminal" })

hl.unbind("SUPER + F") -- was: Full screen (now SUPER + F11)
o.bind("SUPER + F", "File manager", { omarchy = "nautilus" })

o.bind("SUPER + B", "Browser", { omarchy = "browser" })

hl.unbind("SUPER + SLASH") -- was: Monitor scaling up
o.bind("SUPER + SLASH", "Launcher", "omarchy-menu toggle apps")
o.bind("SUPER + A", "App library", "omarchy-menu toggle apps")

-- --- Window management -----------------------------------------------------
o.bind("SUPER + Q", "Close window", hl.dsp.window.close())
hl.unbind("SUPER + W") -- was: Close window (now SUPER + Q)

o.bind("SUPER + M", "Maximize window", hl.dsp.window.fullscreen({ mode = "maximized" }))
o.bind("SUPER + F11", "Full screen", hl.dsp.window.fullscreen({ mode = "fullscreen" }))

hl.unbind("SUPER + G") -- was: Toggle window grouping (now SUPER + S, as stacking)
o.bind("SUPER + G", "Toggle window floating", hl.dsp.window.float({ action = "toggle" }))

hl.unbind("SUPER + O") -- was: Pop window out (float & pin)
o.bind("SUPER + O", "Toggle orientation", hl.dsp.layout("togglesplit"))

hl.unbind("SUPER + S") -- was: Toggle scratchpad
o.bind("SUPER + S", "Toggle window stacking", hl.dsp.group.toggle())

-- Omarchy's own toggle only knows dwindle and scrolling, so a workspace
-- would end up on scrolling after two presses. This one goes between the
-- COSMIC layout and dwindle, recording the choice where Omarchy does so it
-- survives a reload.
o.bind("SUPER + Y", "Toggle tiling", function()
  local ws = hl.get_active_workspace()
  if not ws then
    return
  end
  local new = ws.tiled_layout == "lua:cosmic" and "dwindle" or "lua:cosmic"
  hl.workspace_rule({ workspace = tostring(ws.id), layout = new })

  local dir = (os.getenv("XDG_STATE_HOME") or (os.getenv("HOME") .. "/.local/state")) .. "/omarchy/workspace-layouts"
  os.execute("mkdir -p '" .. dir .. "'")
  local f = io.open(dir .. "/" .. ws.id .. ".lua", "w")
  if f then
    f:write(string.format('hl.workspace_rule({ workspace = "%d", layout = "%s" })\n', ws.id, new))
    f:close()
  end
  hl.dispatch(hl.dsp.exec_cmd("omarchy-notification-send -g 󱂬 'Workspace layout set to " .. new .. "'"))
end)

-- --- Focus -----------------------------------------------------------------
-- SUPER + arrows already match COSMIC. These add COSMIC's vim-key aliases.
hl.unbind("SUPER + K") -- was: Keybindings menu (now SUPER + SHIFT + CTRL + SLASH)
hl.unbind("SUPER + J") -- was: Toggle window split (now SUPER + O, as orientation)
hl.unbind("SUPER + L") -- was: Toggle workspace layout (now SUPER + Y, as tiling)

o.bind("SUPER + H", "Focus on left window", hl.dsp.focus({ direction = "l" }))
o.bind("SUPER + J", "Focus on below window", hl.dsp.focus({ direction = "d" }))
o.bind("SUPER + K", "Focus on above window", hl.dsp.focus({ direction = "u" }))
o.bind("SUPER + L", "Focus on right window", hl.dsp.focus({ direction = "r" }))

o.bind("SUPER + SHIFT + CTRL + SLASH", "Keybindings", "omarchy-menu-keybindings")

-- --- Moving windows --------------------------------------------------------
-- COSMIC lets a move keep going: with nothing in that direction it hands the
-- window to the neighbouring workspace, where it enters from the side it left
-- through and the windows already there keep their arrangement. The logic
-- lives in hypr/cosmic_move.lua, on top of the tree layout in
-- hypr/cosmic_layout.lua.
local cosmic = require("hypr.cosmic_move")

hl.unbind("SUPER + SHIFT + LEFT")
hl.unbind("SUPER + SHIFT + RIGHT")
hl.unbind("SUPER + SHIFT + UP")
hl.unbind("SUPER + SHIFT + DOWN")

o.bind("SUPER + SHIFT + LEFT", "Move window left, or to previous workspace", cosmic.move_or_send("l"))
o.bind("SUPER + SHIFT + RIGHT", "Move window right, or to next workspace", cosmic.move_or_send("r"))
-- Vertical stays inside the workspace: only left and right cross over.
o.bind("SUPER + SHIFT + UP", "Move window up", cosmic.move_or_send("u"))
o.bind("SUPER + SHIFT + DOWN", "Move window down", cosmic.move_or_send("d"))

local function move_within_workspace(dir)
  return function()
    local win = hl.get_active_window()
    local ws = hl.get_active_workspace()
    if not win or not ws then
      return
    end
    if not win.floating and ws.tiled_layout == "lua:cosmic" then
      hl.dispatch(hl.dsp.layout("move " .. dir))
      return
    end
    local target, distance
    local sign = dir == "l" and -1 or 1
    for _, other in ipairs(hl.get_windows({ workspace = tostring(ws.id), mapped = true })) do
      if other.stable_id ~= win.stable_id and other.workspace and other.workspace.id == ws.id and not other.hidden then
        local dx = (other.at.x + other.size.x / 2 - win.at.x - win.size.x / 2) * sign
        local overlap = other.at.y < win.at.y + win.size.y and win.at.y < other.at.y + other.size.y
        if dx > 0 and overlap and (not distance or dx < distance) then
          target, distance = other, dx
        end
      end
    end
    if target then
      hl.dispatch(hl.dsp.window.swap({ target = target }))
    end
  end
end

hl.unbind("SUPER + SHIFT + H")
o.bind("SUPER + SHIFT + H", "Move window left within workspace", move_within_workspace("l"))
hl.unbind("SUPER + SHIFT + L")
o.bind("SUPER + SHIFT + L", "Move window right within workspace", move_within_workspace("r"))
o.bind("SUPER + SHIFT + K", "Move window up", cosmic.move_or_send("u"))
o.bind("SUPER + SHIFT + J", "Move window down", cosmic.move_or_send("d"))

-- --- Resizing --------------------------------------------------------------
-- A Lua layout does not get Hyprland's resize dispatcher, so the same keys
-- (SUPER + minus/equals) move the nearest split through the layout instead.
hl.unbind("SUPER + code:20")
hl.unbind("SUPER + code:21")
hl.unbind("SUPER + SHIFT + code:20")
hl.unbind("SUPER + SHIFT + code:21")
hl.unbind("SUPER + ALT + code:20")
hl.unbind("SUPER + ALT + code:21")
hl.unbind("SUPER + SHIFT + ALT + code:20")
hl.unbind("SUPER + SHIFT + ALT + code:21")

o.bind("SUPER + code:20", "Shrink window width", hl.dsp.layout("resize x -100"))
o.bind("SUPER + code:21", "Expand window width", hl.dsp.layout("resize x 100"))
o.bind("SUPER + SHIFT + code:20", "Shrink window height", hl.dsp.layout("resize y -100"))
o.bind("SUPER + SHIFT + code:21", "Expand window height", hl.dsp.layout("resize y 100"))
o.bind("SUPER + ALT + code:20", "Shrink window width a little", hl.dsp.layout("resize x -25"))
o.bind("SUPER + ALT + code:21", "Expand window width a little", hl.dsp.layout("resize x 25"))
o.bind("SUPER + SHIFT + ALT + code:20", "Shrink window height a little", hl.dsp.layout("resize y -25"))
o.bind("SUPER + SHIFT + ALT + code:21", "Expand window height a little", hl.dsp.layout("resize y 25"))

-- --- Workspaces ------------------------------------------------------------
hl.unbind("SUPER + CTRL + LEFT")  -- was: Move grouped window focus left
hl.unbind("SUPER + CTRL + RIGHT") -- was: Move grouped window focus right
o.bind("SUPER + CTRL + LEFT", "Previous workspace", hl.dsp.focus({ workspace = "e-1" }))
o.bind("SUPER + CTRL + UP", "Previous workspace", hl.dsp.focus({ workspace = "e-1" }))
o.bind("SUPER + CTRL + RIGHT", "Next workspace", hl.dsp.focus({ workspace = "e+1" }))
o.bind("SUPER + CTRL + DOWN", "Next workspace", hl.dsp.focus({ workspace = "e+1" }))

-- Same arrival rule as the edge moves above: the window enters the previous
-- workspace as the rightmost column and the next one as the leftmost.
o.bind("SUPER + SHIFT + CTRL + LEFT", "Move window to previous workspace", cosmic.send_prev)
o.bind("SUPER + SHIFT + CTRL + UP", "Move window to previous workspace", cosmic.send_prev)
o.bind("SUPER + SHIFT + CTRL + RIGHT", "Move window to next workspace", cosmic.send_next)
o.bind("SUPER + SHIFT + CTRL + DOWN", "Move window to next workspace", cosmic.send_next)

-- --- Displays --------------------------------------------------------------
hl.unbind("SUPER + ALT + LEFT")  -- was: Move window to group on left
hl.unbind("SUPER + ALT + RIGHT") -- was: Move window to group on right
hl.unbind("SUPER + ALT + UP")    -- was: Move window to group on top
hl.unbind("SUPER + ALT + DOWN")  -- was: Move window to group on bottom
o.bind("SUPER + ALT + LEFT", "Focus on left monitor", hl.dsp.focus({ monitor = "l" }))
o.bind("SUPER + ALT + RIGHT", "Focus on right monitor", hl.dsp.focus({ monitor = "r" }))
o.bind("SUPER + ALT + UP", "Focus on above monitor", hl.dsp.focus({ monitor = "u" }))
o.bind("SUPER + ALT + DOWN", "Focus on below monitor", hl.dsp.focus({ monitor = "d" }))

-- --- Window switcher -------------------------------------------------------
-- COSMIC cycles windows with SUPER + TAB. Omarchy cycled workspaces there;
-- those moved to SUPER + CTRL + arrows above. ALT + TAB already matches.
hl.unbind("SUPER + TAB")         -- was: Next workspace
hl.unbind("SUPER + SHIFT + TAB") -- was: Previous workspace
o.bind("SUPER + TAB", "Focus on next window", hl.dsp.window.cycle_next())
o.bind("SUPER + SHIFT + TAB", "Focus on previous window", hl.dsp.window.cycle_next({ next = false }))

-- --- Session ---------------------------------------------------------------
hl.unbind("SUPER + ESCAPE") -- was: System menu (now SUPER + CTRL + ESCAPE)
o.bind("SUPER + ESCAPE", "Lock system", "omarchy-system-lock")
o.bind("SUPER + SHIFT + ESCAPE", "Log out", "omarchy-system-logout")
o.bind("SUPER + CTRL + ESCAPE", "System menu", "omarchy-menu toggle system")

-- ===========================================================================
-- Directional bindings: hjkl alongside the arrow keys
--
-- Every SUPER variant that moves or switches something directionally gets a
-- vim-key twin, so the whole set stays on the home row:
--
--   SUPER                + hjkl   focus window
--   SUPER + SHIFT        + hjkl   move window
--   SUPER + CTRL         + hjkl   switch workspace
--   SUPER + SHIFT + CTRL + hjkl   move window to workspace
--   SUPER + ALT          + hjkl   switch screen
--   SUPER + SHIFT + ALT  + hjkl   move window to screen
--
-- The first two rows are bound in the COSMIC section above. h and k go back,
-- l and j go forward, matching LEFT/UP and RIGHT/DOWN.
-- ===========================================================================

-- --- Menus displaced by the rows below -------------------------------------
hl.unbind("SUPER + CTRL + H") -- was: Hardware menu
o.bind("SUPER + SHIFT + CTRL + D", "Hardware menu", "omarchy-menu toggle hardware")

hl.unbind("SUPER + CTRL + K") -- was: Herdr keybindings
o.bind("SUPER + SHIFT + CTRL + RETURN", "Herdr keybindings", "omarchy-menu-herdr-keybindings")

hl.unbind("SUPER + ALT + K") -- was: Tmux keybindings
o.bind("SUPER + SHIFT + ALT + RETURN", "Tmux keybindings", "omarchy-menu-tmux-keybindings")

hl.unbind("SUPER + CTRL + L") -- was: Lock system (now SUPER + ESCAPE)

-- --- Switch workspace ------------------------------------------------------
o.bind("SUPER + CTRL + H", "Previous workspace", hl.dsp.focus({ workspace = "e-1" }))
o.bind("SUPER + CTRL + K", "Previous workspace", hl.dsp.focus({ workspace = "e-1" }))
o.bind("SUPER + CTRL + J", "Next workspace", hl.dsp.focus({ workspace = "e+1" }))
o.bind("SUPER + CTRL + L", "Next workspace", hl.dsp.focus({ workspace = "e+1" }))

-- --- Move window to workspace ----------------------------------------------
-- Cycles among workspaces that already have windows, wrapping at the ends to
-- match the switch keys above. To send a window to a fresh empty workspace,
-- use SUPER+SHIFT+N.
hl.unbind("SUPER + SHIFT + CTRL + H")
o.bind("SUPER + SHIFT + CTRL + H", "Move window to previous workspace", cosmic.send_prev)
o.bind("SUPER + SHIFT + CTRL + K", "Move window to previous workspace", cosmic.send_prev)
o.bind("SUPER + SHIFT + CTRL + J", "Move window to next workspace", cosmic.send_next)
hl.unbind("SUPER + SHIFT + CTRL + L")
o.bind("SUPER + SHIFT + CTRL + L", "Move window to next workspace", cosmic.send_next)

-- --- Switch screen ---------------------------------------------------------
o.bind("SUPER + ALT + H", "Focus on left monitor", hl.dsp.focus({ monitor = "l" }))
o.bind("SUPER + ALT + J", "Focus on below monitor", hl.dsp.focus({ monitor = "d" }))
o.bind("SUPER + ALT + K", "Focus on above monitor", hl.dsp.focus({ monitor = "u" }))
o.bind("SUPER + ALT + L", "Focus on right monitor", hl.dsp.focus({ monitor = "r" }))

-- --- Move window to screen -------------------------------------------------
-- COSMIC moves the window between displays here. Omarchy moved the whole
-- workspace instead, which is what these unbinds drop.
hl.unbind("SUPER + SHIFT + ALT + LEFT")  -- was: Move workspace to left monitor
hl.unbind("SUPER + SHIFT + ALT + RIGHT") -- was: Move workspace to right monitor
hl.unbind("SUPER + SHIFT + ALT + UP")    -- was: Move workspace to up monitor
hl.unbind("SUPER + SHIFT + ALT + DOWN")  -- was: Move workspace to down monitor

o.bind("SUPER + SHIFT + ALT + LEFT", "Move window to left monitor", hl.dsp.window.move({ monitor = "l" }))
o.bind("SUPER + SHIFT + ALT + RIGHT", "Move window to right monitor", hl.dsp.window.move({ monitor = "r" }))
o.bind("SUPER + SHIFT + ALT + UP", "Move window to above monitor", hl.dsp.window.move({ monitor = "u" }))
o.bind("SUPER + SHIFT + ALT + DOWN", "Move window to below monitor", hl.dsp.window.move({ monitor = "d" }))

o.bind("SUPER + SHIFT + ALT + H", "Move window to left monitor", hl.dsp.window.move({ monitor = "l" }))
o.bind("SUPER + SHIFT + ALT + J", "Move window to below monitor", hl.dsp.window.move({ monitor = "d" }))
o.bind("SUPER + SHIFT + ALT + K", "Move window to above monitor", hl.dsp.window.move({ monitor = "u" }))
o.bind("SUPER + SHIFT + ALT + L", "Move window to right monitor", hl.dsp.window.move({ monitor = "r" }))

-- --- Pull a window out into its own column ---------------------------------
-- Moving a window at the edge of the layout does nothing: dwindle's move walks
-- the tree, and at the edge there is no neighbour to trade places with. What
-- promotes a window to a full-height column of its own is a dwindle layout
-- message, not a move, so it needs its own key.
o.bind("SUPER + ALT + O", "Move window to its own column", hl.dsp.layout("movetoroot"))

-- --- Next empty workspace --------------------------------------------------
-- "empty" is a workspace selector, so this lands on the first workspace with
-- no windows rather than a fixed number.
o.bind("SUPER + N", "Next empty workspace", hl.dsp.focus({ workspace = "empty" }))
hl.unbind("SUPER + SHIFT + N") -- was: Editor (now SUPER + ALT + N)
o.bind("SUPER + SHIFT + N", "Move window to next empty workspace", hl.dsp.window.move({ workspace = "empty" }))
o.bind("SUPER + ALT + N", "Editor", { omarchy = "editor" })
