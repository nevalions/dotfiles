-- Adds git related signs to the gutter, as well as utilities for managing changes
return {
  'lewis6991/gitsigns.nvim',
  opts = {
    signs = {
      add = { text = '+' },
      change = { text = '~' },
      delete = { text = '_' },
      topdelete = { text = '‾' },
      changedelete = { text = '~' },
    },
    signs_staged = {
      add = { text = '+' },
      change = { text = '~' },
      delete = { text = '_' },
      topdelete = { text = '‾' },
      changedelete = { text = '~' },
    },
    signs_staged_enable = true,
    signcolumn = true, -- Toggle with `:Gitsigns toggle_signs`
    numhl = true, -- Toggle with `:Gitsigns toggle_numhl`
    linehl = false, -- Toggle with `:Gitsigns toggle_linehl`
    word_diff = true, -- Toggle with `:Gitsigns toggle_word_diff`
    watch_gitdir = {
      follow_files = true,
    },
    auto_attach = true,
    attach_to_untracked = false,
    current_line_blame = false, -- Toggle with `:Gitsigns toggle_current_line_blame`
    current_line_blame_opts = {
      virt_text = true,
      virt_text_pos = 'eol', -- 'eol' | 'overlay' | 'right_align'
      delay = 1000,
      ignore_whitespace = false,
      virt_text_priority = 100,
      use_focus = true,
    },
    current_line_blame_formatter = '<author>, <author_time:%R> - <summary>',
    sign_priority = 6,
    update_debounce = 100,
    status_formatter = nil, -- Use default
    max_file_length = 40000, -- Disable if file is longer than this (in lines)
    preview_config = {
      -- Options passed to nvim_open_win
      border = 'single',
      style = 'minimal',
      relative = 'cursor',
      row = 0,
      col = 1,
    },
  },
  keys = {
    { '<leader>gg', ':Gitsigns preview_hunk<CR>', desc = 'Preview Hunk' },
    { '<leader>ghl', ':Gitsigns preview_hunk<CR>', desc = 'Preview Hunk Inline' },
    { '<leader>gn', ':Gitsigns next_hunk<CR>', desc = 'Next Hunk' },
    { '<leader>gp', ':Gitsigns prev_hunk<CR>', desc = 'Previous Hunk' },
    { '<leader>gs', ':Gitsigns stage_hunk<CR>', desc = 'Stage Hunk' },
    { '<leader>gS', ':Gitsigns stage_buffer<CR>', desc = 'Stage Buffer' },
    { '<leader>gd', ':Gitsigns diffthis<CR>', desc = 'Diffthis' },
    { '<leader>gD', ':Gitsigns diffthis ~<CR>', desc = 'Diffthis all' },
    { '<leader>gb', ':Gitsigns blame_line ~<CR>', desc = 'Blame line' },
  },
}
