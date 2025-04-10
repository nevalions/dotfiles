-- Set leader key
vim.g.mapleader = ' '
vim.g.maplocalleader = ' '

-- Disable the spacebar key's default behavior in Normal and Visual modes
vim.keymap.set({ 'n', 'v' }, '<Space>', '<Nop>', { silent = true })

-- For conciseness
local opts = { noremap = true, silent = true }
local map = vim.keymap.set

-- save file
map('n', '<C-s>', '<cmd> w <CR>', opts)

-- save file without auto-formatting
map('n', '<leader>sn', '<cmd>noautocmd w <CR>', opts)

-- quit file
map('n', '<C-q>', '<cmd> q <CR>', opts)
-- save all and quit
map('n', '<leader>Q', '<cmd> wqa <CR>', opts)

-- copy paste
map('v', '<C-c>', '"+y', { desc = 'Copy' })
map('i', '<C-v>', '<C-r><C-o>+', { desc = 'Paste from clipboard' })
map('n', 'Y', 'y$', { desc = 'Yank to end of line' })

-- select
map('n', '<leader>a', 'ggVG', { desc = 'Select All' })

-- delete single character without copying into register
map('n', 'x', '"_x', opts)

-- Vertical scroll and center
map('n', '<C-d>', '<C-d>zz', opts)
map('n', '<C-u>', '<C-u>zz', opts)

-- Find and center
map('n', 'n', 'nzzzv', opts)
map('n', 'N', 'Nzzzv', opts)

-- Resize with arrows
map('n', '<C-Up>', ':resize -2<CR>', opts)
map('n', '<C-Down>', ':resize +2<CR>', opts)
map('n', '<C-Left>', ':vertical resize -2<CR>', opts)
map('n', '<C-Right>', ':vertical resize +2<CR>', opts)

-- Buffers management
map('n', '<Tab>', ':bnext<CR>', opts)
map('n', '<S-Tab>', ':bprevious<CR>', opts)
map('n', '<leader>x', ':Bdelete<CR>', opts) -- close buffer
map('n', '<leader>b', '<cmd> enew <CR>', opts) -- new buffer

-- Window management
map('n', '<leader>|', '<C-w>v', opts) -- split window vertically
map('n', '<leader>-', '<C-w>s', opts) -- split window horizontally
map('n', '<leader>=', '<C-w>=', opts) -- make split windows equal width & height
map('n', '<leader>q', ':close<CR>', opts) -- close current split window

-- Navigate between splits
map('n', '<C-k>', ':wincmd k<CR>', opts)
map('n', '<C-j>', ':wincmd j<CR>', opts)
map('n', '<C-h>', ':wincmd h<CR>', opts)
map('n', '<C-l>', ':wincmd l<CR>', opts)

-- Tabs
map('n', '<leader>to', ':tabnew<CR>', opts) -- open new tab
map('n', '<leader>tx', ':tabclose<CR>', opts) -- close current tab
map('n', '<leader>tn', ':tabn<CR>', opts) --  go to next tab
map('n', '<leader>tp', ':tabp<CR>', opts) --  go to previous tab

-- Toggle line wrapping
map('n', '<leader>lw', '<cmd>set wrap!<CR>', opts)

-- Stay in indent mode
map('v', '<', '<gv', opts)
map('v', '>', '>gv', opts)

-- Tab line or selection
map('v', '<Tab>', '>>', { desc = 'Indent line' })
map('v', '<S-Tab>', '<<', { desc = 'Unindent line' })

-- Move lines
map('n', '<A-Up>', ':m .-2<CR>==', { desc = 'Move line up', silent = true })
map('n', '<A-Down>', ':m .+1<CR>==', { desc = 'Move line down', silent = true })
map('v', '<A-Up>', ":m '<-2<CR>gv=gv", { desc = 'Move selection up', silent = true })
map('v', '<A-Down>', ":m '>+1<CR>gv=gv", { desc = 'Move selection down', silent = true })

-- Keep last yanked when pasting
map('v', 'p', '"_dP', opts)

-- Diagnostic keymaps
map('n', '[d', function()
  vim.diagnostic.jump { count = -1 }
end, { desc = 'Go to previous diagnostic message' })
map('n', ']d', function()
  vim.diagnostic.jump { count = 1 }
end, { desc = 'Go to next diagnostic message' })
map('n', '<leader>d', vim.diagnostic.open_float, { desc = 'Open floating diagnostic message' })

-- Map to Home and End functionality
map('n', '<C-a>', '^', { noremap = true })
map('n', '<C-e>', '$', { noremap = true })
map('i', '<C-a>', '<Home>', { noremap = true })
map('i', '<C-e>', '<End>', { noremap = true })
map('v', '<C-a>', '^', { noremap = true })
map('v', '<C-e>', '$', { noremap = true })

-- No Neck Pain
map('n', '<leader>nn', ':NoNeckPain<CR>', { desc = 'NoNeckPain' })

-- Yanky
vim.keymap.set({ 'n', 'x' }, 'p', '<Plug>(YankyPutAfter)')
vim.keymap.set({ 'n', 'x' }, 'P', '<Plug>(YankyPutBefore)')
vim.keymap.set({ 'n', 'x' }, 'gp', '<Plug>(YankyGPutAfter)')
vim.keymap.set({ 'n', 'x' }, 'gP', '<Plug>(YankyGPutBefore)')

vim.keymap.set('n', '<c-p>', '<Plug>(YankyPreviousEntry)')
vim.keymap.set('n', '<c-n>', '<Plug>(YankyNextEntry)')
vim.keymap.set('n', ']p', '<Plug>(YankyPutIndentAfterLinewise)')
vim.keymap.set('n', '[p', '<Plug>(YankyPutIndentBeforeLinewise)')
vim.keymap.set('n', ']P', '<Plug>(YankyPutIndentAfterLinewise)')
vim.keymap.set('n', '[P', '<Plug>(YankyPutIndentBeforeLinewise)')

vim.keymap.set('n', '>p', '<Plug>(YankyPutIndentAfterShiftRight)')
vim.keymap.set('n', '<p', '<Plug>(YankyPutIndentAfterShiftLeft)')
vim.keymap.set('n', '>P', '<Plug>(YankyPutIndentBeforeShiftRight)')
vim.keymap.set('n', '<P', '<Plug>(YankyPutIndentBeforeShiftLeft)')

vim.keymap.set('n', '=p', '<Plug>(YankyPutAfterFilter)')
vim.keymap.set('n', '=P', '<Plug>(YankyPutBeforeFilter)')

-- Floating terminal
map('n', '<leader>tt', ':Floaterminal<CR>i')
