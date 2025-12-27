return {
  'neovim/nvim-lspconfig',
  dependencies = {
    { 'williamboman/mason.nvim', config = true },
    'williamboman/mason-lspconfig.nvim',
    'WhoIsSethDaniel/mason-tool-installer.nvim',
    { 'j-hui/fidget.nvim', opts = {} },
    'hrsh7th/cmp-nvim-lsp',
  },

  config = function()
    ---------------------------------------------------------------------------
    -- 🔇 Hide ONLY the lspconfig deprecation warning + traceback
    ---------------------------------------------------------------------------
    local orig_notify = vim.notify
    vim.notify = function(msg, level, opts)
      if type(msg) == 'string' then
        if
          msg:find "The `require%('lspconfig'%)`"
          or msg:find 'lspconfig%-nvim%-0%.11'
          or msg:find 'nvim%-lspconfig v3%.0%.0'
          or msg:find 'lspconfig.lua:81'
        then
          return
        end
      end
      orig_notify(msg, level, opts)
    end

    ---------------------------------------------------------------------------
    -- Setup
    ---------------------------------------------------------------------------
    local lspconfig = require 'lspconfig'
    local util = require 'lspconfig.util'

    local function mason_bin(exe)
      local p = vim.fn.stdpath 'data' .. '/mason/bin/' .. exe
      if vim.loop.fs_stat(p) then
        return p
      end
      return exe
    end

    local function find_node_modules(root_dir)
      local found = vim.fs.find('node_modules', { path = root_dir, upward = true })
      return found and found[1] or (root_dir .. '/node_modules')
    end

    local function angular_cmd(root_dir)
      local nm = find_node_modules(root_dir)
      return {
        mason_bin 'ngserver',
        '--stdio',
        '--tsProbeLocations',
        nm,
        '--ngProbeLocations',
        nm,
      }
    end

    ---------------------------------------------------------------------------
    -- Capabilities (nvim-cmp)
    ---------------------------------------------------------------------------
    local capabilities = vim.lsp.protocol.make_client_capabilities()
    capabilities = require('cmp_nvim_lsp').default_capabilities(capabilities)

    ---------------------------------------------------------------------------
    -- LSP keymaps
    ---------------------------------------------------------------------------
    vim.api.nvim_create_autocmd('LspAttach', {
      group = vim.api.nvim_create_augroup('user-lsp-attach', { clear = true }),
      callback = function(event)
        local map = function(lhs, rhs, desc)
          vim.keymap.set('n', lhs, rhs, { buffer = event.buf, desc = desc })
        end

        map('gd', vim.lsp.buf.definition, 'Go to definition')
        map('gr', vim.lsp.buf.references, 'References')
        map('K', vim.lsp.buf.hover, 'Hover')
        map('<leader>rn', vim.lsp.buf.rename, 'Rename')
        map('<leader>ca', vim.lsp.buf.code_action, 'Code action')
      end,
    })

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
        'pyright',
      },
    }

    ---------------------------------------------------------------------------
    -- Angular Language Server
    ---------------------------------------------------------------------------
    lspconfig.angularls.setup {
      capabilities = capabilities,
      filetypes = { 'typescript', 'typescriptreact', 'html', 'htmlangular' },
      root_dir = util.root_pattern('angular.json', 'nx.json', 'project.json', 'package.json', '.git'),
      cmd = angular_cmd(vim.loop.cwd()),
      on_new_config = function(cfg, root)
        cfg.cmd = angular_cmd(root)
      end,
    }

    ---------------------------------------------------------------------------
    -- TypeScript
    ---------------------------------------------------------------------------
    lspconfig.ts_ls.setup {
      capabilities = capabilities,
      root_dir = util.root_pattern('package.json', 'tsconfig.json', '.git'),
    }

    ---------------------------------------------------------------------------
    -- Python (Pyright) ✅
    ---------------------------------------------------------------------------
    lspconfig.pyright.setup {
      capabilities = capabilities,
      root_dir = util.root_pattern('pyproject.toml', 'setup.py', 'setup.cfg', 'requirements.txt', 'Pipfile', '.git'),
      settings = {
        python = {
          venvPath = '.',
          venv = '.venv',
          analysis = {
            diagnosticMode = 'openFilesOnly',
            typeCheckingMode = 'basic',
          },
        },
      },
    }

    ---------------------------------------------------------------------------
    -- Tailwind
    ---------------------------------------------------------------------------
    lspconfig.tailwindcss.setup {
      capabilities = capabilities,
      filetypes = {
        'html',
        'htmlangular',
        'typescript',
        'typescriptreact',
        'css',
        'scss',
        'less',
      },
    }

    ---------------------------------------------------------------------------
    -- HTML LSP (disabled inside Angular projects)
    ---------------------------------------------------------------------------
    lspconfig.html.setup {
      capabilities = capabilities,
      root_dir = function(fname)
        local root = util.root_pattern('package.json', '.git')(fname)
        if root and vim.fn.filereadable(root .. '/angular.json') == 1 then
          return nil
        end
        return root
      end,
    }

    ---------------------------------------------------------------------------
    -- CSS
    ---------------------------------------------------------------------------
    lspconfig.cssls.setup {
      capabilities = capabilities,
    }

    ---------------------------------------------------------------------------
    -- Lua
    ---------------------------------------------------------------------------
    lspconfig.lua_ls.setup {
      capabilities = capabilities,
      settings = {
        Lua = {
          diagnostics = { globals = { 'vim' } },
          workspace = { checkThirdParty = false },
          telemetry = { enable = false },
        },
      },
    }

    ---------------------------------------------------------------------------
    -- Ensure AngularLS starts for HTML templates
    ---------------------------------------------------------------------------
    vim.api.nvim_create_autocmd('FileType', {
      pattern = { 'html', 'htmlangular' },
      callback = function(args)
        local fname = vim.api.nvim_buf_get_name(args.buf)
        if fname == '' then
          return
        end

        local root = util.root_pattern('angular.json', 'nx.json', 'project.json')(fname)

        if root and vim.fn.exists ':LspStart' == 2 then
          pcall(vim.cmd, 'LspStart angularls')
        end
      end,
    })
  end,
}
