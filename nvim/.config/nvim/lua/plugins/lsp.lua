-- nvim-lspconfig is kept only as a *data provider*: since v3.0.0 it ships one
-- `lsp/<server>.lua` spec per server on the runtimepath and no longer exposes
-- `require('lspconfig').<server>.setup()`. Our overrides live in
-- `after/lsp/<server>.lua`, which Neovim merges last (:help lsp-config).
return {
  'neovim/nvim-lspconfig',
  dependencies = {
    { 'williamboman/mason.nvim', config = true },
    'WhoIsSethDaniel/mason-tool-installer.nvim',
  },

  config = function()
    ---------------------------------------------------------------------------
    -- Profile: which servers to enable (see core/profiles.lua)
    ---------------------------------------------------------------------------
    local profile = require('core.profiles').current()

    require('mason-tool-installer').setup {
      ensure_installed = profile.ensure_installed,
    }

    -- No `capabilities` override: the builtin client advertises its own, and
    -- `vim.lsp.completion` adds the completion ones (see core/completion.lua).
    vim.lsp.enable(profile.servers)

    ---------------------------------------------------------------------------
    -- Keymaps
    ---------------------------------------------------------------------------
    -- `K`, `grr`, `grn`, `gra`, `gri`, `grt`, `grx`, `gO` and insert-mode
    -- `<C-s>` are Neovim defaults now (:help lsp-defaults), so only the
    -- non-default ones are set here. `gr` is deliberately left alone: mapping
    -- it would put the whole `gr*` namespace behind 'timeoutlen'.
    vim.api.nvim_create_autocmd('LspAttach', {
      group = vim.api.nvim_create_augroup('user-lsp-attach', { clear = true }),
      callback = function(event)
        local map = function(lhs, rhs, desc)
          vim.keymap.set('n', lhs, rhs, { buffer = event.buf, desc = desc })
        end

        map('gd', vim.lsp.buf.definition, 'Go to definition')
        map('<leader>rn', vim.lsp.buf.rename, 'Rename')
        map('<leader>ca', vim.lsp.buf.code_action, 'Code action')
      end,
    })
  end,
}
