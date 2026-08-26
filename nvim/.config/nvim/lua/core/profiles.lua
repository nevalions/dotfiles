-- What a profile turns on: language servers for vim.lsp.enable(), and
-- formatters for conform. Both lists feed one derived Mason install list, so a
-- tool can never be enabled without being installed.
--
-- Server *settings* are not here: each server's config is a single
-- `after/lsp/<name>.lua` that Neovim merges on top of the spec nvim-lspconfig
-- ships (:help lsp-config).
--
-- Pick a profile by writing e.g. `return 'full'` in `lsp-local.lua`.

-- lspconfig name -> Mason package that provides it. `false` means "comes from
-- the system". Names verified against the Mason registry (`neovim.lspconfig`).
local server_package = {
  angularls = false, -- system-wide `ngserver`; the project's own is preferred anyway
  bashls = 'bash-language-server',
  clangd = 'clangd',
  copilot = 'copilot-language-server',
  cssls = 'css-lsp',
  dockerls = 'dockerfile-language-server',
  html = 'html-lsp',
  jsonls = 'json-lsp',
  lua_ls = 'lua-language-server',
  pylsp = 'python-lsp-server',
  pyright = 'pyright',
  ruff = 'ruff',
  sqlls = 'sqlls',
  tailwindcss = 'tailwindcss-language-server',
  ts_ls = 'typescript-language-server',
  yamlls = 'yaml-language-server',
}

-- conform formatter -> Mason package. Several formatters share one package.
local formatter_package = {
  clang_format = 'clang-format',
  prettier = 'prettier',
  ruff_format = 'ruff',
  ruff_organize_imports = 'ruff',
  shfmt = 'shfmt',
  stylua = 'stylua',
}

-- Enabled in every profile: Copilot is not tied to a language, but it is an
-- LSP server like any other and rides the same vim.lsp.enable() machinery.
local always_servers = { 'copilot' }

-- Likewise: Lua and shell turn up in every project, config files included.
local always_formatters = {
  lua = { 'stylua' },
  sh = { 'shfmt' },
  bash = { 'shfmt' },
  zsh = { 'shfmt' },
}

-- prettier deliberately does not claim typescript: ts_ls formats it, and that
-- is what has actually been happening. (The old none-ls config listed `ts`,
-- which is not a filetype, so prettier never ran on TypeScript at all.)
local prettier_web = {
  json = { 'prettier' },
  yaml = { 'prettier' },
  markdown = { 'prettier' },
  html = { 'prettier' },
  htmlangular = { 'prettier' },
}

local python_formatters = {
  python = { 'ruff_organize_imports', 'ruff_format' },
}

local c_formatters = {
  c = { 'clang_format' },
  cpp = { 'clang_format' },
}

local profiles = {
  minimal = {
    servers = { 'lua_ls' },
    formatters = {},
  },

  web = {
    servers = { 'ts_ls', 'html', 'cssls', 'tailwindcss', 'jsonls' },
    formatters = prettier_web,
  },

  python = {
    servers = { 'ruff', 'pyright', 'pylsp' },
    formatters = python_formatters,
  },

  angular = {
    servers = { 'ts_ls', 'angularls', 'html', 'cssls', 'tailwindcss', 'jsonls' },
    formatters = prettier_web,
  },

  esp32 = {
    servers = { 'clangd' },
    formatters = c_formatters,
  },

  full = {
    servers = {
      'bashls',
      'ts_ls',
      'angularls',
      'ruff',
      'pyright',
      'pylsp',
      'cssls',
      'tailwindcss',
      'dockerls',
      'sqlls',
      'jsonls',
      'yamlls',
      'lua_ls',
      'clangd',
    },
    formatters = vim.tbl_extend('error', {}, prettier_web, python_formatters, c_formatters),
  },
}

local M = {}

for name, profile in pairs(profiles) do
  local servers = vim.list_extend(vim.deepcopy(profile.servers), always_servers)
  local formatters_by_ft = vim.tbl_extend('force', {}, always_formatters, profile.formatters)

  local seen, ensure_installed = {}, {}
  local function want(package)
    if package and not seen[package] then
      seen[package] = true
      table.insert(ensure_installed, package)
    end
  end

  for _, server in ipairs(servers) do
    local package = server_package[server]
    if package == nil then
      error(('profiles: no Mason package mapped for server %q'):format(server))
    end
    want(package)
  end

  for _, formatters in pairs(formatters_by_ft) do
    for _, formatter in ipairs(formatters) do
      local package = formatter_package[formatter]
      if package == nil then
        error(('profiles: no Mason package mapped for formatter %q'):format(formatter))
      end
      want(package)
    end
  end

  M[name] = {
    servers = servers,
    formatters_by_ft = formatters_by_ft,
    ensure_installed = ensure_installed,
  }
end

--- Resolve the profile named in `lsp-local.lua`, defaulting to `minimal`.
---@return table
function M.current()
  local name = 'minimal'
  local path = vim.fn.stdpath 'config' .. '/lsp-local.lua'

  if vim.fn.filereadable(path) == 1 then
    local ok, loaded = pcall(dofile, path)
    if ok and loaded then
      -- The file has historically held either a bare string or `{ profile = ... }`.
      name = type(loaded) == 'table' and loaded.profile or loaded
    end
  end

  return M[name] or M.minimal
end

return M
