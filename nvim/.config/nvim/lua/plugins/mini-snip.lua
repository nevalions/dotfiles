return {
  'echasnovski/mini.snippets',
  version = false,
  config = function()
    require('mini.snippets').setup {
      -- Module mappings. Use `''` (empty string) to disable one.
      mappings = {
        -- Expand snippet at cursor position. Created globally in Insert mode.
        expand = '<C-j>',

        -- Interact with default `expand.insert` session.
        -- Created for the duration of active session(s)
        jump_next = '<C-l>',
        jump_prev = '<C-h>',
        stop = '<C-c>',
      },
    }
  end,
}
