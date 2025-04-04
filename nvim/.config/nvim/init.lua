require 'core.options' -- Load general options
require 'core.keymaps' -- Load general keymaps
require 'core.snippets' -- Custom code snippets
require 'core.autocmds' -- Custom autocommands
require 'core.floaterminal' -- Custom floaterminal

-- Set up the Lazy plugin manager
local lazypath = vim.fn.stdpath 'data' .. '/lazy/lazy.nvim'
if not (vim.uv or vim.loop).fs_stat(lazypath) then
  local lazyrepo = 'https://github.com/folke/lazy.nvim.git'
  local out = vim.fn.system { 'git', 'clone', '--filter=blob:none', '--branch=stable', lazyrepo, lazypath }
  if vim.v.shell_error ~= 0 then
    error('Error cloning lazy.nvim:\n' .. out)
  end
end
vim.opt.rtp:prepend(lazypath)

-- Set up plugins
require('lazy').setup {
  require 'plugins.neotree',
  require 'plugins.colortheme',
  require 'plugins.bufferline',
  require 'plugins.lualine',
  require 'plugins.treesitter',
  require 'plugins.telescope',
  require 'plugins.lsp',
  require 'plugins.autocompletion',
  require 'plugins.none-ls',
  require 'plugins.vgit',
  -- require 'plugins.gitsigns',
  require 'plugins.alpha',
  require 'plugins.indent-blankline',
  require 'plugins.misc',
  -- require 'plugins.comment',
  require 'plugins.noice',
  require 'plugins.no-neck-pain',
  require 'plugins.neoscroll',
  require 'plugins.yanky',
  require 'plugins.trouble',
  require 'plugins.copilot',
  require 'plugins.mini',
  require 'plugins.mini-ai',
  require 'plugins.mini-surround',
  require 'plugins.mini-comment',
  require 'plugins.mini-operators',
  require 'plugins.mini-bracketed',
  -- require 'plugins.mini-icons',
}
