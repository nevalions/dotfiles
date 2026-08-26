-- In an Angular workspace angularls owns the templates; starting html-lsp
-- there would double-report on the same buffers. Not calling `on_dir` leaves
-- the server unstarted for that buffer.
return {
  root_dir = function(bufnr, on_dir)
    local fname = vim.api.nvim_buf_get_name(bufnr)
    if fname == '' then
      return
    end

    local root = vim.fs.root(fname, { 'package.json', '.git' })
    if not root or vim.uv.fs_stat(root .. '/angular.json') then
      return
    end

    on_dir(root)
  end,
}
