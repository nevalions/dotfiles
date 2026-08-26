return {
  settings = {
    Lua = {
      completion = {
        callSnippet = 'Replace',
      },
      runtime = { version = 'LuaJIT' },
      workspace = {
        checkThirdParty = false,
        library = {
          '${3rd}/luv/library',
          unpack(vim.api.nvim_get_runtime_file('', true)),
        },
      },
      telemetry = { enable = false },
      diagnostics = {
        globals = { 'vim', 'client' },
        disable = { 'missing-fields' },
      },
      -- stylua formats Lua, via none-ls.
      format = {
        enable = false,
      },
    },
  },
}
