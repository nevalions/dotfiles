-- Formatting, in place of none-ls + none-ls-extras + mason-null-ls.
--
-- none-ls wrapped every formatter in a fake LSP client so it could ride
-- vim.lsp.buf.format; conform just runs the binary. Which formatters a profile
-- gets, and the Mason packages behind them, come from core/profiles.lua --
-- the same table that decides which language servers are enabled.
return {
  'stevearc/conform.nvim',
  event = { 'BufWritePre' },
  cmd = { 'ConformInfo' },

  config = function()
    local profile = require('core.profiles').current()

    require('conform').setup {
      formatters_by_ft = profile.formatters_by_ft,

      -- Filetypes with no formatter above fall through to the language
      -- server, which is what formats TypeScript, SQL and the rest.
      format_on_save = {
        timeout_ms = 1000,
        lsp_format = 'fallback',
      },

      formatters = {
        shfmt = { prepend_args = { '-i', '4' } },
      },
    }

    vim.keymap.set({ 'n', 'v' }, '<leader>f', function()
      require('conform').format { async = true, lsp_format = 'fallback' }
    end, { desc = 'Format buffer or selection' })
  end,
}
