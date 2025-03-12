return {
  'tanvirtin/vgit.nvim',
  dependencies = { 'nvim-lua/plenary.nvim', 'nvim-tree/nvim-web-devicons' },
  -- Lazy loading on 'VimEnter' event is necessary.
  event = 'VimEnter',
  config = function()
    require('vgit').setup {
      keymaps = {
        ['n <leader>k'] = function()
          require('vgit').hunk_up()
        end,
        {
          mode = 'n',
          key = '<leader>j',
          handler = 'hunk_down',
          desc = 'Go down in the direction of the hunk',
        },
        ['n <leader>gs'] = function()
          require('vgit').buffer_hunk_stage()
        end,
        ['n <leader>gP'] = function()
          require('vgit').buffer_hunk_preview()
        end,
        ['n <leader>gf'] = function()
          require('vgit').buffer_diff_preview()
        end,
        ['n <leader>gh'] = function()
          require('vgit').buffer_history_preview()
        end,
        ['n <leader>gd'] = function()
          require('vgit').project_diff_preview()
        end,
        ['n <leader>gx'] = function()
          require('vgit').toggle_diff_preference()
        end,
      },
    }
  end,
}
