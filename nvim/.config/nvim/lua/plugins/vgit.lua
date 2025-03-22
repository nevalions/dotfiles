return {
  'tanvirtin/vgit.nvim',
  dependencies = { 'nvim-lua/plenary.nvim', 'nvim-tree/nvim-web-devicons' },
  -- Lazy loading on 'VimEnter' event is necessary.
  event = 'VimEnter',
  config = function()
    require('vgit').setup {
      keymaps = {
        ['n <leader>gk'] = function()
          require('vgit').hunk_up()
        end,
        {
          mode = 'n',
          key = '<leader>gj',
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
      settings = {
        live_blame = {
          enabled = false,
          format = function(blame, git_config)
            local config_author = git_config['user.name']
            local author = blame.author
            if config_author == author then
              author = 'You'
            end
            local time = os.difftime(os.time(), blame.author_time) / (60 * 60 * 24 * 30 * 12)
            local time_divisions = {
              { 1, 'years' },
              { 12, 'months' },
              { 30, 'days' },
              { 24, 'hours' },
              { 60, 'minutes' },
              { 60, 'seconds' },
            }
            local counter = 1
            local time_division = time_divisions[counter]
            local time_boundary = time_division[1]
            local time_postfix = time_division[2]
            while time < 1 and counter ~= #time_divisions do
              time_division = time_divisions[counter]
              time_boundary = time_division[1]
              time_postfix = time_division[2]
              time = time * time_boundary
              counter = counter + 1
            end
            local commit_message = blame.commit_message
            if not blame.committed then
              author = 'You'
              commit_message = 'Uncommitted changes'
              return string.format(' %s • %s', author, commit_message)
            end
            local max_commit_message_length = 255
            if #commit_message > max_commit_message_length then
              commit_message = commit_message:sub(1, max_commit_message_length) .. '...'
            end
            return string.format(
              ' %s, %s • %s',
              author,
              string.format('%s %s ago', time >= 0 and math.floor(time + 0.5) or math.ceil(time - 0.5), time_postfix),
              commit_message
            )
          end,
        },
      },
    }
  end,
}
