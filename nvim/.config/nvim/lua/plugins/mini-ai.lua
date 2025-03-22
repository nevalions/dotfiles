return {
  'echasnovski/mini.ai',
  version = false,
  event = 'VeryLazy',
  config = function()
    require('mini.ai').setup {
      mappings = {
        around = 'a',
        inside = 'i',
      },
    }
  end,
}
