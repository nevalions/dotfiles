return {
  'neovim/nvim-lspconfig',
  dependencies = {
    { 'williamboman/mason.nvim', config = true },
    'williamboman/mason-lspconfig.nvim',
    'WhoIsSethDaniel/mason-tool-installer.nvim',
    'hrsh7th/cmp-nvim-lsp',
    { 'j-hui/fidget.nvim', opts = {} },
  },

  config = function()
    local lspconfig = require 'lspconfig'
    local util = require 'lspconfig.util'

    ---------------------------------------------------------------------------
    -- Capabilities (cmp)
    ---------------------------------------------------------------------------
    local capabilities = vim.lsp.protocol.make_client_capabilities()
    capabilities = require('cmp_nvim_lsp').default_capabilities(capabilities)

    ---------------------------------------------------------------------------
    -- on_attach
    ---------------------------------------------------------------------------
    local on_attach = function(_, bufnr)
      local map = function(lhs, rhs, desc)
        vim.keymap.set('n', lhs, rhs, { buffer = bufnr, desc = desc })
      end

      map('gd', vim.lsp.buf.definition, 'Go to definition')
      map('gr', vim.lsp.buf.references, 'References')
      map('K', vim.lsp.buf.hover, 'Hover')
      map('<leader>rn', vim.lsp.buf.rename, 'Rename')
      map('<leader>ca', vim.lsp.buf.code_action, 'Code action')
    end

    ---------------------------------------------------------------------------
    -- Mason
    ---------------------------------------------------------------------------
    require('mason').setup()

    require('mason-tool-installer').setup {
      ensure_installed = {
        'angular-language-server',
        'typescript-language-server',
        'tailwindcss-language-server',
        'html-lsp',
        'css-lsp',
        'lua-language-server',
      },
    }

    ---------------------------------------------------------------------------
    -- Angular Language Server (IMPORTANT PART)
    ---------------------------------------------------------------------------
    local function angular_cmd(root_dir)
      local node_modules = root_dir .. '/node_modules'
      return {
        vim.fn.stdpath 'data' .. '/mason/bin/ngserver',
        '--stdio',
        '--tsProbeLocations',
        node_modules,
        '--ngProbeLocations',
        node_modules,
      }
    end

    lspconfig.angularls.setup {
      capabilities = capabilities,
      on_attach = on_attach,
      filetypes = { 'typescript', 'typescriptreact', 'html', 'htmlangular' },
      root_dir = util.root_pattern('angular.json', 'nx.json', 'project.json', 'package.json', '.git'),
      cmd = angular_cmd(vim.loop.cwd()),
      on_new_config = function(new_config, new_root_dir)
        new_config.cmd = angular_cmd(new_root_dir)
      end,
    }

    ---------------------------------------------------------------------------
    -- TypeScript
    ---------------------------------------------------------------------------
    lspconfig.ts_ls.setup {
      capabilities = capabilities,
      on_attach = on_attach,
      root_dir = util.root_pattern('package.json', 'tsconfig.json', '.git'),
    }

    ---------------------------------------------------------------------------
    -- HTML (disabled inside Angular projects)
    ---------------------------------------------------------------------------
    lspconfig.html.setup {
      capabilities = capabilities,
      on_attach = on_attach,
      root_dir = function(fname)
        local root = util.root_pattern('package.json', '.git')(fname)
        if root and vim.fn.filereadable(root .. '/angular.json') == 1 then
          return nil
        end
        return root
      end,
    }

    ---------------------------------------------------------------------------
    -- Tailwind
    ---------------------------------------------------------------------------
    lspconfig.tailwindcss.setup {
      capabilities = capabilities,
      on_attach = on_attach,
      filetypes = {
        'html',
        'htmlangular',
        'typescript',
        'typescriptreact',
        'css',
        'scss',
      },
    }

    ---------------------------------------------------------------------------
    -- CSS
    ---------------------------------------------------------------------------
    lspconfig.cssls.setup {
      capabilities = capabilities,
      on_attach = on_attach,
    }

    ---------------------------------------------------------------------------
    -- Lua
    ---------------------------------------------------------------------------
    lspconfig.lua_ls.setup {
      capabilities = capabilities,
      on_attach = on_attach,
      settings = {
        Lua = {
          diagnostics = { globals = { 'vim' } },
          workspace = { checkThirdParty = false },
        },
      },
    }

    ---------------------------------------------------------------------------
    -- Force AngularLS attach for HTML templates
    -- (THIS fixes your exact issue)
    ---------------------------------------------------------------------------
    vim.api.nvim_create_autocmd('FileType', {
      pattern = { 'html', 'htmlangular' },
      callback = function(args)
        local fname = vim.api.nvim_buf_get_name(args.buf)
        if fname == '' then
          return
        end

        local root = util.root_pattern('angular.json', 'nx.json', 'project.json')(fname)

        if root then
          vim.cmd 'LspStart angularls'
        end
      end,
    })
  end,
}
