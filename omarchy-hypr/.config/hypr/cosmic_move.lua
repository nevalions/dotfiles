-- COSMIC-style window movement, driving the "lua:cosmic" layout from
-- keybindings. Loaded from bindings.lua.
--
-- Modelled on cosmic-comp's Action::Move: a move that finds nothing in its
-- direction carries the window over to the neighbouring workspace, where it
-- enters from the side it left through and the windows already there keep
-- their arrangement. Past the last workspace it continues to the next
-- monitor.

local layout = require("hypr.cosmic_layout")

local M = {}

-- Workspace ids on the active monitor, sorted. COSMIC keeps its workspaces
-- as a gapless list, so "next" here is the next existing workspace rather
-- than id + 1: a push right lands where SUPER + CTRL + RIGHT would switch to.
local function workspace_ids()
  local mon = hl.get_active_monitor()
  local ids = {}
  for _, ws in ipairs(hl.get_workspaces()) do
    if not ws.special and ws.id > 0 and mon and ws.monitor and ws.monitor.name == mon.name then
      ids[#ids + 1] = ws.id
    end
  end
  table.sort(ids)
  return ids
end

-- The workspace one step in `dir` from the active one, or nil at the ends.
-- With `wrap`, the ends cycle round like the e+1/e-1 selectors do under
-- allow_workspace_cycles. Without it, a step right past the last workspace
-- returns a fresh id, the way COSMIC keeps one empty workspace after the
-- last used one.
function M.workspace_in(dir, wrap)
  local ids = workspace_ids()
  local active = hl.get_active_workspace()
  if not active or #ids == 0 then
    return nil
  end

  local pos = 1
  for i, id in ipairs(ids) do
    if id == active.id then
      pos = i
      break
    end
  end

  if dir == "l" then
    if pos > 1 then return ids[pos - 1] end
    if wrap then return ids[#ids] end
    return nil
  end

  if pos < #ids then return ids[pos + 1] end
  if wrap then return ids[1] end
  return ids[#ids] + 1
end

-- Is there another monitor in `dir` from the active one? Hyprland's own
-- monitor fallback complains when there is none, so it is only asked when
-- one exists.
local function monitor_in(dir)
  local active = hl.get_active_monitor()
  if not active then
    return false
  end
  for _, m in ipairs(hl.get_monitors()) do
    if m.name ~= active.name then
      local overlaps_rows = m.y < active.y + active.height and active.y < m.y + m.height
      if dir == "l" and overlaps_rows and m.x + m.width <= active.x then return true end
      if dir == "r" and overlaps_rows and m.x >= active.x + active.width then return true end
    end
  end
  return false
end

-- Send the active window to workspace `target`, entering from the side it
-- left through: pushed right ("r") it becomes the leftmost column, pushed
-- left ("l") the rightmost. Focus follows, as in COSMIC. The layout reads
-- the hint when the window shows up on the new workspace.
function M.send_to_workspace(target, dir)
  local win = hl.get_active_window()
  if not target or not win then
    return
  end

  if not win.floating then
    layout.pending = { id = layout.target_id(win), dir = dir }
  end
  hl.dispatch(hl.dsp.window.move({ workspace = tostring(target) }))
  layout.pending = nil
end

-- Move the active window one step in `dir`. Inside the workspace this
-- swaps with a neighbour, joins a neighbouring stack, or steps out to the
-- edge of the enclosing region. At the edge, left and right carry the
-- window to the neighbouring workspace, creating one past the last; up and
-- down stay put. Left of the first workspace there is nowhere to go unless
-- another monitor sits there.
function M.move_or_send(dir)
  return function()
    local win = hl.get_active_window()
    local ws = hl.get_active_workspace()
    if not win or not ws then
      return
    end

    if win.floating or not layout.is_active(ws) then
      hl.dispatch(hl.dsp.window.swap({ direction = dir }))
      return
    end

    if layout.move(ws.id, layout.target_id(win), dir) then
      layout.relayout()
      return
    end

    if dir == "u" or dir == "d" then
      return
    end

    local target = M.workspace_in(dir, false)
    if target then
      M.send_to_workspace(target, dir)
    elseif monitor_in(dir) then
      hl.dispatch(hl.dsp.window.move({ monitor = dir }))
    end
  end
end

-- Explicit "move to previous/next workspace", cycling round at the ends and
-- entering from the matching side.
function M.send_prev()
  M.send_to_workspace(M.workspace_in("l", true), "l")
end

function M.send_next()
  M.send_to_workspace(M.workspace_in("r", true), "r")
end

return M
