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
    -- Load profile configuration
    ---------------------------------------------------------------------------
    local profile = 'minimal'
    local profile_path = vim.fn.stdpath 'config' .. '/lsp-local.lua'
    if vim.fn.filereadable(profile_path) == 1 then
      local ok, loaded_profile = pcall(dofile, profile_path)
      if ok and loaded_profile then
        profile = loaded_profile
      end
    end

    local lsp_profiles = require 'plugins.lsp-profiles'
    local profile_config = lsp_profiles[profile] or lsp_profiles.minimal

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
      ensure_installed = profile_config.ensure_installed or {},
    }

    ---------------------------------------------------------------------------
    -- Angular Language Server
    ---------------------------------------------------------------------------
    if profile_config.servers.angularls then
      local config = profile_config.servers.angularls
      lspconfig.angularls.setup(vim.tbl_deep_extend('force', {
        capabilities = capabilities,
        cmd = angular_cmd(vim.loop.cwd()),
        on_new_config = function(cfg, root)
          cfg.cmd = angular_cmd(root)
        end,
      }, config))
    end

    ---------------------------------------------------------------------------
    -- TypeScript
    ---------------------------------------------------------------------------
    if profile_config.servers.ts_ls then
      local config = profile_config.servers.ts_ls
      lspconfig.ts_ls.setup(vim.tbl_deep_extend('force', {
        capabilities = capabilities,
      }, config))
    end

    ---------------------------------------------------------------------------
    -- Python (Pyright) ✅
    ---------------------------------------------------------------------------
    if profile_config.servers.pyright then
      local config = profile_config.servers.pyright
      lspconfig.pyright.setup(vim.tbl_deep_extend('force', {
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
      }, config or {}))
    end

    ---------------------------------------------------------------------------
    -- Tailwind
    ---------------------------------------------------------------------------
    if profile_config.servers.tailwindcss then
      local config = profile_config.servers.tailwindcss
      lspconfig.tailwindcss.setup(vim.tbl_deep_extend('force', {
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
      }, config))
    end

    ---------------------------------------------------------------------------
    -- HTML LSP (disabled inside Angular projects)
    ---------------------------------------------------------------------------
    if profile_config.servers.html then
      local config = profile_config.servers.html
      lspconfig.html.setup(vim.tbl_deep_extend('force', {
        capabilities = capabilities,
        root_dir = function(fname)
          local root = util.root_pattern('package.json', '.git')(fname)
          if root and vim.fn.filereadable(root .. '/angular.json') == 1 then
            return nil
          end
          return root
        end,
      }, config))
    end

    ---------------------------------------------------------------------------
    -- CSS
    ---------------------------------------------------------------------------
    if profile_config.servers.cssls then
      local config = profile_config.servers.cssls
      lspconfig.cssls.setup(vim.tbl_deep_extend('force', {
        capabilities = capabilities,
      }, config))
    end

    ---------------------------------------------------------------------------
    -- Lua
    ---------------------------------------------------------------------------
    if profile_config.servers.lua_ls then
      local config = profile_config.servers.lua_ls
      lspconfig.lua_ls.setup(vim.tbl_deep_extend('force', {
        capabilities = capabilities,
      }, config or {}))
    end

    ---------------------------------------------------------------------------
    -- Bash
    ---------------------------------------------------------------------------
    if profile_config.servers.bashls then
      local config = profile_config.servers.bashls
      lspconfig.bashls.setup(vim.tbl_deep_extend('force', {
        capabilities = capabilities,
      }, config or {}))
    end

    ---------------------------------------------------------------------------
    -- Python LSP
    ---------------------------------------------------------------------------
    if profile_config.servers.ruff then
      local config = profile_config.servers.ruff
      lspconfig.ruff.setup(vim.tbl_deep_extend('force', {
        capabilities = capabilities,
      }, config or {}))
    end

    if profile_config.servers.pylsp then
      local config = profile_config.servers.pylsp
      lspconfig.pylsp.setup(vim.tbl_deep_extend('force', {
        capabilities = capabilities,
      }, config or {}))
    end

    ---------------------------------------------------------------------------
    -- JSON
    ---------------------------------------------------------------------------
    if profile_config.servers.jsonls then
      local config = profile_config.servers.jsonls
      lspconfig.jsonls.setup(vim.tbl_deep_extend('force', {
        capabilities = capabilities,
      }, config or {}))
    end

    ---------------------------------------------------------------------------
    -- YAML
    ---------------------------------------------------------------------------
    if profile_config.servers.yamlls then
      local config = profile_config.servers.yamlls
      lspconfig.yamlls.setup(vim.tbl_deep_extend('force', {
        capabilities = capabilities,
      }, config or {}))
    end

    ---------------------------------------------------------------------------
    -- Docker
    ---------------------------------------------------------------------------
    if profile_config.servers.dockerls then
      local config = profile_config.servers.dockerls
      lspconfig.dockerls.setup(vim.tbl_deep_extend('force', {
        capabilities = capabilities,
      }, config or {}))
    end

    ---------------------------------------------------------------------------
    -- SQL
    ---------------------------------------------------------------------------
    if profile_config.servers.sqlls then
      local config = profile_config.servers.sqlls
      lspconfig.sqlls.setup(vim.tbl_deep_extend('force', {
        capabilities = capabilities,
      }, config or {}))
    end

    ---------------------------------------------------------------------------
    -- C/C++
    ---------------------------------------------------------------------------
    if profile_config.servers.clangd then
      local config = profile_config.servers.clangd
      lspconfig.clangd.setup(vim.tbl_deep_extend('force', {
        capabilities = capabilities,
      }, config or {}))
    end

    ---------------------------------------------------------------------------
    -- Ensure AngularLS starts for HTML templates (only in angular profile)
    ---------------------------------------------------------------------------
    if profile_config.servers.angularls then
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
    end
  end,
}
