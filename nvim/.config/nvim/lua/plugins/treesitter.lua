-- nvim-treesitter's `main` branch is a parser installer and nothing else: the
-- `configs` module, `ensure_installed`, `highlight`, `indent` and
-- `incremental_selection` all live in Neovim now. That is also what fixes
-- markdown, which had to be disabled here because the master-branch queries
-- clash with the ones 0.12 ships.
--
-- Highlighting  -> vim.treesitter.start()
-- Indent        -> 'indentexpr'
-- Incremental   -> built-in `an` / `in` in Visual mode, plus `]n` `[n` `]N` `[N`
return {
  'nvim-treesitter/nvim-treesitter',
  branch = 'main',
  build = ':TSUpdate',

  config = function()
    local parsers = {
      'angular',
      'scss',
      'lua',
      'python',
      'javascript',
      'typescript',
      'vimdoc',
      'vim',
      'regex',
      'sql',
      'dockerfile',
      'toml',
      'json',
      'java',
      'groovy',
      'go',
      'gitignore',
      'graphql',
      'yaml',
      'make',
      'cmake',
      'markdown',
      'markdown_inline',
      'bash',
      'tsx',
      'css',
      'html',
    }

    local ts = require 'nvim-treesitter'
    ts.setup {}

    -- Only fetch what is missing, so startup stays off the network once the
    -- parsers are in place. Unlike the master branch, which compiled
    -- src/parser.c with `cc`, this one shells out to the tree-sitter CLI --
    -- without it every parser fails one by one and floods the messages.
    local installed = ts.get_installed 'parsers'
    local missing = vim.tbl_filter(function(parser)
      return not vim.tbl_contains(installed, parser)
    end, parsers)

    if #missing > 0 then
      if vim.fn.executable 'tree-sitter' == 1 then
        ts.install(missing)
      else
        vim.notify(
          ('nvim-treesitter: %d parsers missing, and the tree-sitter CLI is not installed (pacman -S tree-sitter-cli)'):format(#missing),
          vim.log.levels.WARN
        )
      end
    end

    vim.api.nvim_create_autocmd('FileType', {
      group = vim.api.nvim_create_augroup('user-treesitter', { clear = true }),
      callback = function(event)
        -- Ruby's indent rules need vim's regex engine, as before.
        if vim.bo[event.buf].filetype == 'ruby' then
          return
        end

        if not pcall(vim.treesitter.start, event.buf) then
          return
        end

        vim.bo[event.buf].indentexpr = "v:lua.require'nvim-treesitter'.indentexpr()"
      end,
    })
  end,
}
