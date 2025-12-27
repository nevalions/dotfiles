return {
  'nvimtools/none-ls.nvim',
  dependencies = {
    'nvimtools/none-ls-extras.nvim',
    'jayp0521/mason-null-ls.nvim',
  },
  config = function()
    local null_ls = require 'null-ls'
    local formatting = null_ls.builtins.formatting
    local diagnostics = null_ls.builtins.diagnostics

    local function load_local_config()
      local local_config_path = vim.fn.stdpath 'config' .. '/lsp-local.lua'
      if vim.fn.filereadable(local_config_path) == 1 then
        local ok, config = pcall(dofile, local_config_path)
        if ok then
          return config
        end
      end
      return nil
    end

    local local_config = load_local_config()
    local profile_name = 'minimal'

    if local_config then
      if type(local_config) == 'string' then
        profile_name = local_config
      elseif type(local_config) == 'table' then
        profile_name = local_config.profile or 'minimal'
      end
    end

    local profiles = {
      minimal = {
        ensure_installed = {
          'stylua',
          'shfmt',
        },
        sources = {
          formatting.stylua,
          formatting.shfmt.with { args = { '-i', '4' } },
        },
      },
      web = {
        ensure_installed = {
          'stylua',
          'shfmt',
          'prettier',
        },
        sources = {
          formatting.stylua,
          formatting.shfmt.with { args = { '-i', '4' } },
          formatting.prettier.with { filetypes = { 'json', 'yaml', 'markdown', 'ts', 'html', 'htmlangular' } },
        },
      },
      python = {
        ensure_installed = {
          'stylua',
          'shfmt',
          'ruff',
        },
        sources = {
          formatting.stylua,
          formatting.shfmt.with { args = { '-i', '4' } },
          require('none-ls.formatting.ruff').with { extra_args = { '--extend-select', 'I' } },
          require 'none-ls.formatting.ruff_format',
        },
      },
      angular = {
        ensure_installed = {
          'stylua',
          'shfmt',
          'prettier',
        },
        sources = {
          formatting.stylua,
          formatting.shfmt.with { args = { '-i', '4' } },
          formatting.prettier.with { filetypes = { 'json', 'yaml', 'markdown', 'ts', 'html', 'htmlangular' } },
        },
      },
      esp32 = {
        ensure_installed = {
          'stylua',
          'shfmt',
          'clang-format',
        },
        sources = {
          formatting.stylua,
          formatting.shfmt.with { args = { '-i', '4' } },
          formatting.clang_format.with { filetypes = { 'c', 'cpp', 'h', 'hpp' } },
        },
      },
      full = {
        ensure_installed = {
          'stylua',
          'shfmt',
          'prettier',
          'clang-format',
          'checkmake',
          'ruff',
        },
        sources = {
          formatting.stylua,
          formatting.shfmt.with { args = { '-i', '4' } },
          formatting.prettier.with { filetypes = { 'json', 'yaml', 'markdown', 'ts', 'html', 'htmlangular' } },
          formatting.clang_format.with { filetypes = { 'c', 'cpp', 'h', 'hpp' } },
          diagnostics.checkmake,
          require('none-ls.formatting.ruff').with { extra_args = { '--extend-select', 'I' } },
          require 'none-ls.formatting.ruff_format',
        },
      },
    }

    local profile = profiles[profile_name] or profiles.minimal

    require('mason-null-ls').setup {
      ensure_installed = profile.ensure_installed,
      automatic_installation = false,
    }

    local sources = profile.sources

    local augroup = vim.api.nvim_create_augroup('LspFormatting', {})
    null_ls.setup {
      -- debug = true, -- Enable debug mode. Inspect logs with :NullLsLog.
      sources = sources,
      -- you can reuse a shared lspconfig on_attach callback here
      on_attach = function(client, bufnr)
        if client.supports_method 'textDocument/formatting' then
          vim.api.nvim_clear_autocmds { group = augroup, buffer = bufnr }
          vim.api.nvim_create_autocmd('BufWritePre', {
            group = augroup,
            buffer = bufnr,
            callback = function()
              vim.lsp.buf.format { bufnr = bufnr, async = false }
              -- vim.lsp.buf.format { async = false }
            end,
          })
        end
      end,
    }
  end,
}
