-- Insert-mode completion, built on Neovim's own (:help ins-autocompletion).
-- Replaces nvim-cmp, its four sources, LuaSnip and friendly-snippets.
--
-- One popup, one mechanism: 'autocomplete' collects from every source in
-- 'complete', and `o` in that list is the LSP omnifunc. `vim.lsp.completion`
-- is enabled *without* autotrigger on purpose — turning it on as well would
-- fire a second trigger on the server's triggerCharacters. Accepting with
-- <C-y> still expands snippets, applies auto-imports and runs the item's
-- commands, because those side effects also apply to omnifunc-driven
-- completion (:help vim.lsp.completion.enable()).

vim.o.autocomplete = true

-- `^N` caps a source at N candidates so no single source floods the menu.
-- LSP (`o`) gets the largest share; `t` (tags) is left out, LSP covers it.
vim.o.complete = '.^5,w^5,b^5,u^5,o^10'

-- popup  -> completionItem/resolve documentation next to the menu
-- fuzzy  -> match without a common prefix
-- nearest-> rank by distance from the cursor
vim.o.completeopt = 'menu,menuone,popup,fuzzy,noselect,nearest'
vim.o.pumborder = 'rounded'
vim.o.pummaxwidth = 60

vim.api.nvim_create_autocmd('LspAttach', {
  group = vim.api.nvim_create_augroup('user-lsp-completion', { clear = true }),
  callback = function(event)
    vim.lsp.completion.enable(true, event.data.client_id, event.buf)
  end,
})

---------------------------------------------------------------------------
-- Keymaps
---------------------------------------------------------------------------
-- Each of these falls back to the key's normal meaning when the popup is
-- closed, so <C-h> keeps deleting a character outside a snippet.
local function pum(key, fallback)
  return function()
    return vim.fn.pumvisible() == 1 and key or fallback
  end
end

local function snippet_jump(direction, fallback)
  return function()
    if vim.snippet.active { direction = direction } then
      return ('<Cmd>lua vim.snippet.jump(%d)<CR>'):format(direction)
    end
    return fallback
  end
end

local map = function(modes, lhs, rhs, desc)
  vim.keymap.set(modes, lhs, rhs, { expr = true, silent = true, desc = desc })
end

map('i', '<A-j>', pum('<C-n>', '<A-j>'), 'Next completion item')
map('i', '<A-k>', pum('<C-p>', '<A-k>'), 'Previous completion item')

-- <C-y> already accepts; these are the aliases nvim-cmp was configured with.
map('i', '<A-l>', pum('<C-y>', '<A-l>'), 'Accept completion')
map('i', '<C-CR>', pum('<C-y>', '<C-CR>'), 'Accept completion')

map({ 'i', 's' }, '<C-l>', snippet_jump(1, '<C-l>'), 'Next snippet placeholder')
map({ 'i', 's' }, '<C-h>', snippet_jump(-1, '<C-h>'), 'Previous snippet placeholder')

vim.keymap.set('i', '<C-Space>', vim.lsp.completion.get, { desc = 'Trigger LSP completion' })

---------------------------------------------------------------------------
-- Inline completion (Copilot)
---------------------------------------------------------------------------
-- Replaces github/copilot.vim; the suggestions come from the `copilot` LSP
-- server (:help lsp-copilot), which lsp-profiles.lua enables in every profile.
vim.lsp.inline_completion.enable()

-- <Tab> keeps copilot.vim's habit of accepting the ghost text, then falls back
-- through Neovim's own <Tab> meanings: jump a snippet placeholder, walk the
-- completion menu, insert a tab.
vim.keymap.set('i', '<Tab>', function()
  if vim.lsp.inline_completion.get() then
    return
  end
  if vim.snippet.active { direction = 1 } then
    return '<Cmd>lua vim.snippet.jump(1)<CR>'
  end
  if vim.fn.pumvisible() == 1 then
    return '<C-n>'
  end
  return '<Tab>'
end, { expr = true, silent = true, desc = 'Accept inline completion, else snippet/menu/tab' })

map('i', '<M-]>', function()
  return '<Cmd>lua vim.lsp.inline_completion.select({ count = 1 })<CR>'
end, 'Next inline completion')

map('i', '<M-[>', function()
  return '<Cmd>lua vim.lsp.inline_completion.select({ count = -1 })<CR>'
end, 'Previous inline completion')

vim.keymap.set('n', '<leader>zi', function()
  local enabled = not vim.lsp.inline_completion.is_enabled()
  vim.lsp.inline_completion.enable(enabled)
  vim.notify('Inline completion ' .. (enabled and 'enabled' or 'disabled'))
end, { desc = 'Toggle inline completion' })
