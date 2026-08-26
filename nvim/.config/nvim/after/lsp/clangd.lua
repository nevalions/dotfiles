-- Tuned for ESP-IDF: the xtensa cross-compiler has to be whitelisted as a
-- query driver, and the fallback flags stand in for a missing
-- build/compile_commands.json.
local esp_idf = os.getenv 'HOME' .. '/esp-idf/components'

return {
  cmd = {
    'clangd',
    '--compile-commands-dir=build',
    '--header-insertion=never',
    '--query-driver=' .. os.getenv 'HOME' .. '/.espressif/tools/xtensa-esp32-elf/**/xtensa-esp32-elf-*',
  },
  root_markers = { 'CMakeLists.txt', '.git' },
  settings = {
    clangd = {
      compileCommands = { 'build/compile_commands.json' },
      fallbackFlags = {
        '-I',
        esp_idf,
        '-I',
        esp_idf .. '/esp_wifi/include',
        '-I',
        esp_idf .. '/esp_common/include',
        '-target',
        'xtensa-esp32-elf',
        '-std=gnu99',
        '-DESP32',
      },
    },
  },
}
