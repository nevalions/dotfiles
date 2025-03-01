return {
  "alexghergh/nvim-tmux-navigation",
  cmd = {
    "TmuxNavigateLeft",
    "TmuxNavigateDown",
    "TmuxNavigateUp",
    "TmuxNavigateRight",
    "TmuxNavigatePrevious",
    "TmuxNavigatorProcessList",
  },
  keys = {
    { "<C-h>", "<cmd>TmuxNavigateLeft<CR>", desc = "Navigate left" },
    { "<C-j>", "<cmd>TmuxNavigateDown<CR>", desc = "Navigate down" },
    { "<C-k>", "<cmd>TmuxNavigateUp<CR>", desc = "Navigate up" },
    { "<C-l>", "<cmd>TmuxNavigateRight<CR>", desc = "Navigate right" },
  },
  config = function()
    require("nvim-tmux-navigation").setup({
      keybindings = {
        left = "<C-h>",
        down = "<C-j>",
        up = "<C-k>",
        right = "<C-l>",
      },
    })
  end,
}
