-- ruff owns diagnostics and code actions for Python; pyright is kept for
-- types, hover and go-to-definition only.
return {
  root_markers = { 'pyproject.toml', 'setup.py', 'setup.cfg', 'requirements.txt', 'Pipfile', '.git' },

  handlers = {
    ['textDocument/publishDiagnostics'] = function() end,
  },

  on_attach = function(client, _)
    client.server_capabilities.codeActionProvider = false
  end,

  settings = {
    pyright = {
      disableOrganizeImports = true,
    },
    python = {
      venvPath = '.',
      venv = '.venv',
      analysis = {
        autoSearchPaths = true,
        diagnosticMode = 'openFilesOnly',
        typeCheckingMode = 'basic',
        useLibraryCodeForTypes = true,
      },
    },
  },
}
