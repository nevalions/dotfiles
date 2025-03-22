return {
  'echasnovski/mini.surround',
  version = false,
  config = function()
    require('mini.surround').setup {
      -- Duration (in ms) of highlight when calling `MiniSurround.highlight()`
      highlight_duration = 500,

      -- Module mappings. Use `''` (empty string) to disable one.
      mappings = {
        add = '<leader>ra', -- Add surrounding in Normal and Visual modes
        delete = '<leader>rd', -- Delete surrounding
        find = '<leader>rf', -- Find surrounding (to the right)
        find_left = '<leader>rF', -- Find surrounding (to the left)
        highlight = '<leader>rh', -- Highlight surrounding
        replace = '<leader>rr', -- Replace surrounding
        update_n_lines = '', -- Update `n_lines`

        suffix_last = 'l', -- Suffix to search with "prev" method
        suffix_next = 'n', -- Suffix to search with "next" method
      },
    }
  end,
}
