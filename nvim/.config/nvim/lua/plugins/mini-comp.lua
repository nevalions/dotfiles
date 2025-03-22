return {
  'echasnovski/mini.completion',
  version = false,
  config = function()
    require('mini.completion').setup {
      -- Fallback action as function/string. Executed in Insert mode.
      -- To use built-in completion (`:h ins-completion`), set its mapping as
      -- string. Example: set '<C-x><C-l>' for 'whole lines' completion.
      delay = { completion = 100, info = 100, signature = 50 },

      -- Configuration for action windows:
      -- - `height` and `width` are maximum dimensions.
      -- - `border` defines border (as in `nvim_open_win()`; default "single").
      window = {
        info = { height = 25, width = 80, border = nil },
        signature = { height = 25, width = 80, border = nil },
      },

      fallback_action = '<C-n>',

      -- Module mappings. Use `''` (empty string) to disable one. Some of them
      -- might conflict with system mappings.
      mappings = {
        -- Force two-step/fallback completions
        force_twostep = '<C-Space>',
        force_fallback = '<A-Space>',
        -- Scroll info/signature window down/up. When overriding, check for
        -- conflicts with built-in keys for popup menu (like `<C-u>`/`<C-o>`
        -- for 'completefunc'/'omnifunc' source function; or `<C-n>`/`<C-p>`).
        scroll_down = '<C-f>',
        scroll_up = '<C-b>',
      },
    }
  end,
}
