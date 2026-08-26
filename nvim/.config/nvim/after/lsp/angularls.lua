-- The probe locations must point at the project's own node_modules, so the
-- command can only be built once the root is known. Neovim 0.12 passes the
-- resolved config to a `cmd` function, which replaces the old `on_new_config`.
local function ngserver()
  local mason = vim.fn.stdpath 'data' .. '/mason/bin/ngserver'
  return vim.uv.fs_stat(mason) and mason or 'ngserver'
end

return {
  filetypes = { 'typescript', 'html', 'typescriptreact', 'htmlangular' },
  root_markers = { 'angular.json', 'nx.json', 'project.json' },
  -- Don't start outside an Angular workspace. Replaces the FileType autocmd
  -- that used to call `:LspStart angularls` by hand.
  workspace_required = true,

  cmd = function(dispatchers, config)
    local root = config.root_dir or vim.fn.getcwd()
    local node_modules = vim.fs.find('node_modules', { path = root, upward = true })[1] or (root .. '/node_modules')

    return vim.lsp.rpc.start({
      ngserver(),
      '--stdio',
      '--tsProbeLocations',
      node_modules,
      '--ngProbeLocations',
      node_modules,
    }, dispatchers)
  end,
}
