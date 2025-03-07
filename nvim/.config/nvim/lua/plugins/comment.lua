-- Easily comment visual regions/lines
return {
  'numToStr/Comment.nvim',
  opts = {},
  config = function()
    local map = vim.keymap.set
    local opts = { noremap = true, silent = true }
    map('n', '<C-_>', require('Comment.api').toggle.linewise.current, opts)
    map('n', '<C-c>', require('Comment.api').toggle.linewise.current, opts)
    map('n', '<C-/>', require('Comment.api').toggle.linewise.current, opts)
    map('v', '<C-_>', "<esc><cmd>lua require('Comment.api').toggle.linewise(vim.fn.visualmode())<cr>", opts)
    map('v', '<C-c>', "<esc><cmd>lua require('Comment.api').toggle.linewise(vim.fn.visualmode())<cr>", opts)
    map('v', '<C-/>', "<esc><cmd>lua require('Comment.api').toggle.linewise(vim.fn.visualmode())<cr>", opts)
  end,
}
