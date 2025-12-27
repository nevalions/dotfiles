return {
  'neovim/nvim-lspconfig',
  dependencies = {
    { 'williamboman/mason.nvim', config = true },
    'williamboman/mason-lspconfig.nvim',
    'WhoIsSethDaniel/mason-tool-installer.nvim',
    { 'j-hui/fidget.nvim', opts = {} },
    { 'Aietes/esp32.nvim' },
    'hrsh7th/cmp-nvim-lsp',
  },

  config = function()
    local profiles = require 'plugins.lsp-profiles'

    local function get_probe_dir(root_dir)
      local project_root = vim.fs.dirname(vim.fs.find('node_modules', { path = root_dir, upward = true })[1])
      return project_root and (project_root .. '/node_modules') or ''
    end

    local function get_angular_core_version(root_dir)
      local project_root = vim.fs.dirname(vim.fs.find('node_modules', { path = root_dir, upward = true })[1])

      if not project_root then
        return ''
      end

      local package_json = project_root .. '/package.json'
      if not vim.loop.fs_stat(package_json) then
        return ''
      end

      local contents = io.open(package_json):read '*a'
      local json = vim.json.decode(contents)
      if not json.dependencies then
        return ''
      end

      local angular_core_version = json.dependencies['@angular/core']
      angular_core_version = angular_core_version and angular_core_version:match '%d+%.%d+%.%d+'

      return angular_core_version
    end

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

    local profile = profiles[profile_name] or profiles.minimal
    local servers = vim.deepcopy(profile.servers)

    if local_config and type(local_config) == 'table' and local_config.custom_servers then
      for server_name, server_config in pairs(local_config.custom_servers) do
        servers[server_name] = server_config
      end
    end

    require('esp32').setup {
      target = 'esp32',
      idf_path = os.getenv 'HOME' .. '/esp-idf',
      toolchain_path = os.getenv 'HOME' .. '/.espressif/tools/xtensa-esp-elf',
      suppress_clangd_warnings = true,
      clangd_args = {
        '--query-driver=/home/linroot/.espressif/tools/xtensa-esp-elf/esp-14.2.0_20241119/bin/xtensa-esp-elf-gcc',
        '--extra-arg=-Wno-unused-command-line-argument',
        '--extra-arg=-Wno-unknown-warning-option',
        '--extra-arg=-Wno-error=unknown-warning-option',
        '--extra-arg=-Wno-error=unused-command-line-argument',
      },
      build_dir = 'build',
    }

    vim.api.nvim_create_autocmd('LspAttach', {
      group = vim.api.nvim_create_augroup('kickstart-lsp-attach', { clear = true }),
      callback = function(event)
        local map = function(keys, func, desc, mode)
          mode = mode or 'n'
          vim.keymap.set(mode, keys, func, { buffer = event.buf, desc = 'LSP: ' .. desc })
        end

        map('gd', require('telescope.builtin').lsp_definitions, '[G]oto [D]efinition')

        vim.keymap.set('n', 'g|', function()
          vim.cmd 'vsplit'
          vim.lsp.buf.definition()
        end, { desc = 'LSP: [G]oto [D]efinition in vertical split' })

        vim.keymap.set('n', 'g-', function()
          vim.cmd 'split'
          vim.lsp.buf.definition()
        end, { desc = 'LSP: [G]oto [D]efinition in horizontal split' })

        map('gr', require('telescope.builtin').lsp_references, '[G]oto [R]eferences')
        map('gI', require('telescope.builtin').lsp_implementations, '[G]oto [I]mplementation')
        map('<leader>D', require('telescope.builtin').lsp_type_definitions, 'Type [D]efinition')
        map('<leader>ds', require('telescope.builtin').lsp_document_symbols, '[D]ocument [S]ymbols')
        map('<leader>ws', require('telescope.builtin').lsp_dynamic_workspace_symbols, '[W]orkspace [S]ymbols')
        map('<leader>rn', vim.lsp.buf.rename, '[R]e[n]ame')
        map('<leader>ca', vim.lsp.buf.code_action, '[C]ode [A]ction', { 'n', 'x' })
        map('gD', vim.lsp.buf.declaration, '[G]oto [D]eclaration')

        local client = vim.lsp.get_client_by_id(event.data.client_id)
        if client and client.supports_method(vim.lsp.protocol.Methods.textDocument_inlayHint) then
          map('<leader>th', function()
            vim.lsp.inlay_hint.enable(not vim.lsp.inlay_hint.is_enabled { bufnr = event.buf })
          end, '[T]oggle Inlay [H]ints')
        end
      end,
    })

    local capabilities = vim.lsp.protocol.make_client_capabilities()
    capabilities = vim.tbl_deep_extend('force', capabilities, require('cmp_nvim_lsp').default_capabilities())

    if profile_name == 'angular' or profile_name == 'full' then
      local default_probe_dir = get_probe_dir(vim.fn.getcwd())
      local default_angular_core_version = get_angular_core_version(vim.fn.getcwd())

      if servers.angularls then
        servers.angularls.cmd = {
          'ngserver',
          '--stdio',
          '--tsProbeLocations',
          default_probe_dir,
          '--ngProbeLocations',
          default_probe_dir,
          '--angularCoreVersion',
          default_angular_core_version,
        }
      end
    end

    for server_name, server_config in pairs(servers) do
      local lazy_config = server_config.lazy or {}
      server_config.lazy = nil

      local config = {
        capabilities = vim.tbl_deep_extend('force', {}, capabilities, server_config.capabilities or {}),
      }

      if server_config.settings then
        config.settings = server_config.settings
        server_config.settings = nil
      end

      if server_config.handlers then
        config.handlers = server_config.handlers
        server_config.handlers = nil
      end

      if server_config.on_attach then
        config.on_attach = server_config.on_attach
        server_config.on_attach = nil
      end

      if server_config.cmd then
        config.cmd = server_config.cmd
        server_config.cmd = nil
      end

      if server_config.root_dir then
        config.root_dir = server_config.root_dir
        server_config.root_dir = nil
      end

      if server_config.filetypes then
        config.filetypes = server_config.filetypes
        server_config.filetypes = nil
      end

      for key, value in pairs(server_config) do
        config[key] = value
      end

      if next(lazy_config) ~= nil then
        config.lazy = lazy_config
      end

      vim.lsp.config(server_name, config)
      vim.lsp.enable(server_name)
    end

    require('mason').setup()

    local ensure_installed = vim.list_extend({}, profile.ensure_installed or {})
    if local_config and type(local_config) == 'table' and local_config.custom_servers then
      for server_name, _ in pairs(local_config.custom_servers) do
        if not vim.tbl_contains(ensure_installed, server_name) then
          table.insert(ensure_installed, server_name)
        end
      end
    end

    require('mason-tool-installer').setup { ensure_installed = ensure_installed }
  end,
}
