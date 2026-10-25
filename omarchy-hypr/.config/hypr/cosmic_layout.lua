-- A COSMIC-style tiling layout for Hyprland, registered as "lua:cosmic".
--
-- Every window on a workspace stays on screen, arranged in a binary tree of
-- splits the way cosmic-comp does it. Compared with dwindle, the difference
-- is what happens when a window is moved:
--
--   * A window pushed past the edge of its workspace arrives on the next one
--     as a new root split at the edge it entered from, full height, with the
--     windows already there kept exactly as they were.
--   * A window moved within a workspace swaps with a neighbouring window,
--     joins a neighbouring stack, or steps out of its row or column to the
--     edge of the enclosing region. Nothing else is rearranged.
--
-- Loaded from looknfeel.lua (which selects the layout) and from
-- cosmic_move.lua (which drives it from keybindings).

local M = {}

M.options = {
  -- How a window opened normally is placed against the focused one.
  --   "columns": always beside it, as a new column.
  --   "auto":    COSMIC's rule -- a tile wider than it is tall splits into
  --              columns, a taller one into rows.
  new_split = "columns",
  -- Smallest share of a split either side can be resized down to.
  min_ratio = 0.1,
}

local trees = {} -- workspace id -> root node

-- Set by cosmic_move.lua just before it sends a window to another workspace:
-- { id = <tile id>, dir = "l"|"r"|"u"|"d" }. Consumed when that tile shows
-- up on its new workspace.
M.pending = nil

local AXIS = { l = "h", r = "h", u = "v", d = "v" }
local TOWARD_FIRST = { l = true, u = true, r = false, d = false }

-- Tiles ----------------------------------------------------------------------

-- A stacked (grouped) set of windows is a single tile. It is keyed by its
-- first member so that switching tabs does not look like a new tile.
function M.target_id(win)
  if not win then
    return nil
  end
  local ok, id = pcall(function()
    local g = win.group
    if g then
      local members = g.members
      if type(members) == "table" and members[1] and members[1].stable_id then
        return "g" .. tostring(members[1].stable_id)
      end
    end
    return tostring(win.stable_id)
  end)
  if ok and id then
    return id
  end
  return nil
end

-- Tree -----------------------------------------------------------------------
-- leaf:  { id = string, parent = group|nil, box = {x,y,w,h} }
-- group: { orient = "h"|"v", ratio = share of the first child, children = {a, b}, parent, box }

local function leaf(id)
  return { id = id }
end

local function group(orient, a, b)
  local g = { orient = orient, ratio = 0.5, children = { a, b } }
  a.parent, b.parent = g, g
  return g
end

local function index_in_parent(node)
  local p = node.parent
  if not p then
    return nil
  end
  return p.children[1] == node and 1 or 2
end

local function leaves(node, out)
  out = out or {}
  if node then
    if node.id then
      out[#out + 1] = node
    else
      leaves(node.children[1], out)
      leaves(node.children[2], out)
    end
  end
  return out
end

local function find(node, id)
  if not node or not id then
    return nil
  end
  if node.id then
    return node.id == id and node or nil
  end
  return find(node.children[1], id) or find(node.children[2], id)
end

-- Put `new` where `old` is.
local function replace(ws, old, new)
  local p = old.parent
  new.parent = p
  if p then
    p.children[index_in_parent(old)] = new
  else
    trees[ws] = new
  end
end

-- Take a leaf out; its sibling takes over the parent's slot.
local function detach(ws, node)
  local p = node.parent
  if not p then
    trees[ws] = nil
  else
    local sibling = p.children[3 - index_in_parent(node)]
    replace(ws, p, sibling)
  end
  node.parent = nil
end

-- Split `anchor`'s slot between it and `node`.
local function insert_beside(ws, anchor, node, orient, node_first)
  local p, idx = anchor.parent, index_in_parent(anchor)
  local g = node_first and group(orient, node, anchor) or group(orient, anchor, node)
  g.parent = p
  if p then
    p.children[idx] = g
  else
    trees[ws] = g
  end
end

local function clamp(x, lo, hi)
  return math.max(lo, math.min(hi, x))
end

-- Placement ------------------------------------------------------------------

local function add(ws, id)
  local root = trees[ws]
  local node = leaf(id)
  if not root then
    trees[ws] = node
    return
  end

  local pending = M.pending
  if pending and pending.id == id then
    -- Arriving from another workspace: a new root split at the entry edge.
    M.pending = nil
    local first = pending.dir == "r" or pending.dir == "d"
    trees[ws] = first and group(AXIS[pending.dir], node, root) or group(AXIS[pending.dir], root, node)
    return
  end

  -- Otherwise split the focused tile, as COSMIC does. A window that has just
  -- been moved here with focus following is itself the active window, so
  -- fall back to the tile this workspace focused last.
  local anchor
  local active_id = M.target_id(hl.get_active_window())
  if active_id and active_id ~= id then
    anchor = find(root, active_id)
  end
  if not anchor then
    for _, w in ipairs(hl.get_workspaces()) do
      if w.id == ws then
        local last_id = M.target_id(w.last_window)
        if last_id and last_id ~= id then
          anchor = find(root, last_id)
        end
        break
      end
    end
  end
  if not anchor then
    local all = leaves(root)
    anchor = all[#all]
  end

  local orient = "h"
  if M.options.new_split == "auto" and anchor.box and anchor.box.h > anchor.box.w then
    orient = "v"
  end
  insert_beside(ws, anchor, node, orient, false)
end

-- Bring the tree in line with the targets Hyprland hands us: rename tiles
-- that turned into or out of a stack, drop the ones that left, add the new.
local function sync(ws, ctx)
  local present, by_id, order = {}, {}, {}
  for _, t in ipairs(ctx.targets) do
    local id = M.target_id(t.window) or ("t" .. tostring(t.index))
    present[id] = true
    by_id[id] = t
    order[#order + 1] = id
  end

  local root = trees[ws]

  for _, id in ipairs(order) do
    if root and not find(root, id) then
      local twin = id:sub(1, 1) == "g" and id:sub(2) or ("g" .. id)
      local old = find(root, twin)
      if old and not present[twin] then
        old.id = id
      end
    end
  end

  root = trees[ws]
  if root then
    for _, lf in ipairs(leaves(root)) do
      if not present[lf.id] then
        detach(ws, lf)
      end
    end
  end

  for _, id in ipairs(order) do
    if not find(trees[ws], id) then
      add(ws, id)
    end
  end

  return by_id
end

local function layout(node, box, by_id)
  node.box = box
  if node.id then
    local t = by_id[node.id]
    if t then
      t:place({ x = box.x, y = box.y, w = box.w, h = box.h })
    end
    return
  end

  local a, b = node.children[1], node.children[2]
  if node.orient == "h" then
    local w1 = math.floor(box.w * node.ratio + 0.5)
    layout(a, { x = box.x, y = box.y, w = w1, h = box.h }, by_id)
    layout(b, { x = box.x + w1, y = box.y, w = box.w - w1, h = box.h }, by_id)
  else
    local h1 = math.floor(box.h * node.ratio + 0.5)
    layout(a, { x = box.x, y = box.y, w = box.w, h = h1 }, by_id)
    layout(b, { x = box.x, y = box.y + h1, w = box.w, h = box.h - h1 }, by_id)
  end
end

local function workspace_of(ctx)
  for _, t in ipairs(ctx.targets) do
    local ok, ws = pcall(function()
      local win = t.window
      return win and win.workspace and win.workspace.id
    end)
    if ok and ws then
      return ws
    end
  end
  return nil
end

-- Operations -----------------------------------------------------------------

-- Move tile `id` one step in `dir` inside its workspace. Returns true when
-- something moved, false when the tile is already at the edge and the move
-- should carry on to the next workspace.
function M.move(ws, id, dir)
  local axis, toward_first = AXIS[dir], TOWARD_FIRST[dir]
  local node = axis and find(trees[ws], id)
  if not node then
    return false
  end

  local a = node
  while a.parent do
    local p = a.parent
    if p.orient == axis then
      local ai = index_in_parent(a)
      local sibling = p.children[toward_first and ai - 1 or ai + 1]
      if sibling then
        if a == node and sibling.id then
          -- Two tiles side by side: trade places.
          p.children[1], p.children[2] = p.children[2], p.children[1]
          return true
        end

        detach(ws, node)

        -- Same-axis nesting reads as one row or column; step past its
        -- nearest member rather than wrapping the whole thing.
        while not sibling.id and sibling.orient == axis do
          sibling = sibling.children[toward_first and 2 or 1]
        end

        if sibling.id then
          -- Past the neighbouring tile.
          insert_beside(ws, sibling, node, axis, toward_first)
        else
          -- Into the neighbouring stack, at its near end.
          insert_beside(ws, sibling, node, sibling.orient, not toward_first)
        end
        return true
      end
      a = p
    else
      -- Crosswise parent: leave the row or column and take the edge of the
      -- region it occupies.
      local slot = p
      if a == node then
        slot = p.children[3 - index_in_parent(node)]
      end
      detach(ws, node)
      insert_beside(ws, slot, node, axis, toward_first)
      return true
    end
  end

  return false
end

-- Grow (positive px) or shrink the tile along "x" or "y" by moving the
-- nearest split on that axis.
function M.resize(ws, id, axis_name, px)
  local node = find(trees[ws], id)
  if not node or not px then
    return false
  end
  local axis = axis_name == "y" and "v" or "h"

  local a = node
  while a.parent do
    local p = a.parent
    if p.orient == axis and p.box then
      local total = axis == "h" and p.box.w or p.box.h
      if total > 0 then
        local delta = px / total
        if index_in_parent(a) == 2 then
          delta = -delta
        end
        p.ratio = clamp(p.ratio + delta, M.options.min_ratio, 1 - M.options.min_ratio)
      end
      return true
    end
    a = p
  end
  return false
end

function M.toggle_split(ws, id)
  local node = find(trees[ws], id)
  local p = node and node.parent
  if not p then
    return false
  end
  p.orient = p.orient == "h" and "v" or "h"
  return true
end

function M.swap_split(ws, id)
  local node = find(trees[ws], id)
  local p = node and node.parent
  if not p then
    return false
  end
  p.children[1], p.children[2] = p.children[2], p.children[1]
  return true
end

function M.is_active(ws)
  return ws ~= nil and ws.tiled_layout == "lua:cosmic"
end

-- Ask Hyprland to lay the active workspace out again after a tree change.
function M.relayout()
  hl.dispatch(hl.dsp.layout("relayout"))
end

-- Text form of a workspace's tree, for debugging and tests.
function M.dump(ws, names)
  local function show(node)
    if node.id then
      return names and names[node.id] or node.id
    end
    return "(" .. node.orient .. " " .. show(node.children[1]) .. " " .. show(node.children[2]) .. ")"
  end
  local root = trees[ws]
  return root and show(root) or "empty"
end

-- Registration ---------------------------------------------------------------

local function active_tile(ctx)
  for _, t in ipairs(ctx.targets) do
    local win = t.window
    if win and win.active then
      return M.target_id(win)
    end
  end
  return M.target_id(hl.get_active_window())
end

hl.layout.register("cosmic", {
  recalculate = function(ctx)
    if #ctx.targets == 0 then
      return
    end
    local ws = workspace_of(ctx)
    if not ws then
      return
    end
    local by_id = sync(ws, ctx)
    if trees[ws] then
      layout(trees[ws], ctx.area, by_id)
    end
  end,

  layout_msg = function(ctx, msg)
    local cmd, arg1, arg2 = msg:match("^(%S+)%s*(%S*)%s*(%S*)")
    if cmd == "relayout" then
      return true
    end

    local ws = workspace_of(ctx)
    if not ws then
      return true
    end
    local id = active_tile(ctx)

    if cmd == "move" then
      M.move(ws, id, arg1)
    elseif cmd == "resize" then
      M.resize(ws, id, arg1, tonumber(arg2))
    elseif cmd == "togglesplit" then
      M.toggle_split(ws, id)
    elseif cmd == "swapsplit" then
      M.swap_split(ws, id)
    else
      return "cosmic: unknown layout message '" .. tostring(cmd) .. "'"
    end
    return true
  end,
})

return M
