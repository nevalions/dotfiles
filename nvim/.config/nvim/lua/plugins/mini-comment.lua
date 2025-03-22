return {
  'echasnovski/mini.comment',
  version = false,
  event = 'VeryLazy',
  config = function()
    require('mini.comment').setup {
      mappings = {
        around = 'a',
        inside = 'i',
      },
    }
  end,
}
