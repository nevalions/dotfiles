return {
  'echasnovski/mini.operators',
  version = false,
  config = function()
    require('mini.operators').setup {
      -- Evaluate text and replace with output
      evaluate = {
        prefix = 'g=',

        -- Function which does the evaluation
        func = nil,
      },

      -- Exchange text regions. Not `gx`: that is Neovim's built-in
      -- "open URL / follow documentLink under cursor".
      exchange = {
        prefix = 'cx',

        -- Whether to reindent new text to match previous indent
        reindent_linewise = true,
      },

      -- Multiply (duplicate) text
      multiply = {
        prefix = 'gm',

        -- Function which can modify text before multiplying
        func = nil,
      },

      -- Replace text with register. Not `gr`: since Neovim 0.11 that prefix
      -- belongs to the built-in LSP maps (`grr`, `gra`, `grn`, `gri`, `grt`).
      replace = {
        prefix = 'cr',

        -- Whether to reindent new text to match previous indent
        reindent_linewise = true,
      },

      -- Sort text
      sort = {
        prefix = 'gs',

        -- Function which does the sort
        func = nil,
      },
    }
  end,
}
