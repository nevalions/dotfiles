-- Workaround: nvim-treesitter master branch ships incompatible markdown queries
-- for Neovim 0.12. Stop the broken highlighter and restart with only bundled queries.
vim.treesitter.stop()
