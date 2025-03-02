-- Keymaps are automatically loaded on the VeryLazy event
-- Default keymaps that are always set: https://github.com/LazyVim/LazyVim/blob/main/lua/lazyvim/config/keymaps.lua
-- Add any additional keymaps here
local map = vim.keymap.set

map("v", "<C-c>", '"+y', { desc = "Copy" })
map("i", "<C-v>", "<C-r><C-o>+", { desc = "Paste from clipboard" })

map("n", "Y", "y$", { desc = "Yank to end of line" })

map("i", "<C-Left>", "<C-o>b", { desc = "Move left on e word" })
map("i", "<C-Right>", "<C-o>w", { desc = "Move right one word" })
map("v", "<C-Left>", "b", { desc = "Move left one word" })
map("v", "<C-Right>", "w", { desc = "Move right one word" })
map("n", "<C-Left>", "b", { desc = "Move left one word" })
map("n", "<C-Right>", "w", { desc = "Move right one word" })

map("n", "<A-Up>", ":m .-2<CR>==", { desc = "Move line up", silent = true })
map("n", "<A-Down>", ":m .+1<CR>==", { desc = "Move line down", silent = true })
map("v", "<A-Up>", ":m '<-2<CR>gv=gv", { desc = "Move selection up", silent = true })
map("v", "<A-Down>", ":m '>+1<CR>gv=gv", { desc = "Move selection down", silent = true })

-- Tab line or selection
map("n", "<Tab>", ">>", { desc = "Indent line" })
map("n", "<S-Tab>", "<<", { desc = "Unindent line" })

-- Indent selected block in visual mode
map("v", "<Tab>", ">gv", { desc = "Indent selection" })
map("v", "<S-Tab>", "<gv", { desc = "Unindent selection" })
