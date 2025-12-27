local local_config_path = vim.fn.stdpath 'config' .. '/lsp-local.lua'
local profile_name = 'minimal'
local config = nil

if vim.fn.filereadable(local_config_path) == 1 then
  local ok, loaded_config = pcall(dofile, local_config_path)
  if ok then
    config = loaded_config
    if type(config) == 'string' then
      profile_name = config
    elseif type(config) == 'table' then
      profile_name = config.profile or 'minimal'
    end
  end
end

local has_esp32 = profile_name == 'esp32' or profile_name == 'full'

if not has_esp32 and config and type(config) == 'table' and config.custom_servers then
  for server_name, _ in pairs(config.custom_servers) do
    if server_name == 'clangd' then
      has_esp32 = true
      break
    end
  end
end

if has_esp32 then
  return {
    'Aietes/esp32.nvim',
    lazy = true,
    ft = { 'c', 'cpp' },
    keys = '<leader>e',
    config = function()
      require('esp32').setup {
        target = 'esp32',
        idf_path = os.getenv 'HOME' .. '/esp-idf',
        toolchain_path = os.getenv 'HOME' .. '/.espressif/tools/xtensa-esp-elf',
        suppress_clangd_warnings = true,
        clangd_args = {
          '--query-driver=/home/linroot/.espressif/tools/xtensa-esp-elf/esp-14.2.0_20241119/bin/xtensa-esp-elf-gcc',
          '--extra-arg=-Wno-unused-command-line-argument',
          '--extra-arg=-Wno-unknown-warning-option',
          '--extra-arg=-Wno-error=unknown-warning-option',
          '--extra-arg=-Wno-error=unused-command-line-argument',
        },
        build_dir = 'build',
      }
    end,
  }
else
  return {}
end
