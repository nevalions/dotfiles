return {
  "JoosepAlviste/nvim-ts-context-commentstring",
  config = function()
    require("nvim-ts-context-commentstring").setup({
      enable_autocmd = false,
    })
  end,
  {
    "numToStr/Comment.nvim",
    dependencies = { "JoosepAlviste/nvim-ts-context-commentstring" },
    opts = {
      padding = true,
      sticky = true,
      ignore = nil,
      toggler = {
        line = "gcc",
        block = "gbc",
      },
      opleader = {
        line = "gc",
        block = "gb",
      },
      extre = {
        eol = "gcA",
      },
    },
    keys = {
      { "<leader>gc", false },
    },
  },
}
