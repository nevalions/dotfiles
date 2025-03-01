-- Keymaps are automatically loaded on the VeryLazy event
-- Default keymaps that are always set: https://github.com/LazyVim/LazyVim/blob/main/lua/lazyvim/config/keymaps.lua
-- Add any additional keymaps here
--

vim.api.nvim_set_keymap("n", "<C-z>", "u", { noremap = true, silent = true })

vim.keymap.set("v", "<C-c>", '"+y', { desc = "Copy" })

vim.keymap.set("i", "<C-v>", "<C-r><C-o>+", { desc = "Paste from clipboard" })

-- Move one word left with Ctrl + Left
vim.keymap.set("i", "<C-Left>", "<C-o>b", { desc = "Move left one word" })

-- Move one word right with Ctrl + Right
vim.keymap.set("i", "<C-Right>", "<C-o>w", { desc = "Move right one word" })

-- Move one word left with Ctrl + Left
vim.keymap.set("n", "<C-Left>", "b", { desc = "Move left one word" })

-- Move one word right with Ctrl + Right
vim.keymap.set("n", "<C-Right>", "w", { desc = "Move right one word" })

-- Move line up with Alt + Up
vim.keymap.set("n", "<A-Up>", ":m .-2<CR>==", { desc = "Move line up", silent = true })

-- Move line down with Alt + Down
vim.keymap.set("n", "<A-Down>", ":m .+1<CR>==", { desc = "Move line down", silent = true })

-- Move selected lines up with Alt + Up in visual mode
vim.keymap.set("v", "<A-Up>", ":m '<-2<CR>gv=gv", { desc = "Move selection up", silent = true })

-- Move selected lines down with Alt + Down in visual mode
vim.keymap.set("v", "<A-Down>", ":m '>+1<CR>gv=gv", { desc = "Move selection down", silent = true })
