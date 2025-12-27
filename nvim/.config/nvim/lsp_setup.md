# LSP Profile Setup Guide

This guide explains how to configure and use the profile-based LSP system for Neovim.

## Quick Start

Choose a profile and copy the example file to `~/.config/nvim/lsp-local.lua`:

```bash
# Full setup (all 14 LSP servers)
cp nvim/.config/nvim/lsp-local.lua.example.full ~/.config/nvim/lsp-local.lua

# Minimal setup (lua_ls, bashls only - recommended for light usage)
cp nvim/.config/nvim/lsp-local.lua.example.minimal ~/.config/nvim/lsp-local.lua
```

## Available Profiles

| Profile | LSP Servers | Use Case |
|---------|-------------|----------|
| `minimal` | lua_ls, bashls | Dotfiles, scripting, Neovim config (default) |
| `web` | ts_ls, html, cssls, tailwindcss, jsonls | Web development |
| `python` | ruff, pyright, pylsp | Python development |
| `angular` | ts_ls, angularls, html, cssls, tailwindcss, jsonls | Angular projects |
| `esp32` | clangd | ESP32/embedded C/C++ development |
| `full` | All 14 servers | Workstation with multiple language needs |

### Complete Server List

- **lua_ls** - Lua language server
- **bashls** - Bash/shell scripting
- **ts_ls** - TypeScript/JavaScript
- **angularls** - Angular framework
- **ruff** - Python linter (fast)
- **pyright** - Python type checker
- **pylsp** - Python language server
- **clangd** - C/C++ (also used for ESP-IDF)
- **html** - HTML
- **cssls** - CSS
- **tailwindcss** - Tailwind CSS framework
- **jsonls** - JSON
- **yamlls** - YAML
- **dockerls** - Dockerfile
- **sqlls** - SQL

## Lazy Loading

All LSP servers are lazy-loaded by filetype. They only start when you open relevant files:

```lua
lazy = { filetype = 'python' }  -- Only loads when opening .py files
```

This means:
- Fast Neovim startup
- Servers only activate when needed
- Reduced memory usage

## Configuration Options

### Option 1: Simple Profile Selection

Create `~/.config/nvim/lsp-local.lua` with just a profile name:

```lua
return 'web'
```

Or:

```lua
return 'python'
```

### Option 2: Profile + Custom Servers

Mix a base profile with additional custom servers:

```lua
return {
  profile = 'minimal',
  custom_servers = {
    pyright = {
      lazy = { filetype = 'python' },
      settings = {
        python = {
          analysis = {
            typeCheckingMode = 'strict',
          },
        },
      },
    },
  },
}
```

### Option 3: Custom Servers Only

Define servers completely from scratch:

```lua
return {
  custom_servers = {
    lua_ls = {
      lazy = { filetype = 'lua' },
      settings = {
        Lua = {
          completion = {
            callSnippet = 'Replace',
          },
          runtime = { version = 'LuaJIT' },
          workspace = {
            checkThirdParty = false,
            library = {
              '${3rd}/luv/library',
              unpack(vim.api.nvim_get_runtime_file('', true)),
            },
          },
          telemetry = { enable = false },
          diagnostics = {
            globals = { 'vim', 'client' },
            disable = { 'missing-fields' },
          },
          format = {
            enable = false,
          },
        },
      },
    },
    pyright = {
      lazy = { filetype = 'python' },
      settings = {
        python = {
          analysis = {
            typeCheckingMode = 'basic',
            autoSearchPaths = true,
            useLibraryCodeForTypes = true,
          },
        },
      },
    },
  },
}
```

## Common Use Cases

### Web Development Machine

```bash
echo "return 'web'" > ~/.config/nvim/lsp-local.lua
```

### Python + Data Science Machine

```bash
echo "return 'python'" > ~/.config/nvim/lsp-local.lua
```

### Angular Developer

```bash
echo "return 'angular'" > ~/.config/nvim/lsp-local.lua
```

### ESP32 / Embedded Developer

```bash
echo "return 'esp32'" > ~/.config/nvim/lsp-local.lua
```

### Main Workstation (All Languages)

```bash
echo "return 'full'" > ~/.config/nvim/lsp-local.lua
```

### Neovim Config Editing Only

```bash
echo "return 'minimal'" > ~/.config/nvim/lsp-local.lua
```

### Mixed: Minimal + Python

```lua
-- ~/.config/nvim/lsp-local.lua
return {
  profile = 'minimal',
  custom_servers = {
    pyright = {
      lazy = { filetype = 'python' },
    },
  },
}
```

## Troubleshooting

### Check LSP Configuration

In Neovim, run:

```vim
:checkhealth vim.lsp
```

This shows all configured and active LSP servers.

### Test Configuration

Test that your config loads without errors:

```bash
nvim --headless -c "lua print('LSP config loaded')" -c "qa"
```

### Manually Install LSP Servers

If servers aren't auto-installed via Mason:

```vim
:Mason
```

Then press `i` on the server you want to install.

### Change Profiles

Simply edit or replace `~/.config/nvim/lsp-local.lua` and restart Neovim:

```bash
# Change to web profile
echo "return 'web'" > ~/.config/nvim/lsp-local.lua

# Restart Neovim
nvim
```

### Reset to Default

Delete the local config file to fall back to `minimal` profile:

```bash
rm ~/.config/nvim/lsp-local.lua
```

## File Locations

- **Profile definitions**: `nvim/.config/nvim/lua/plugins/lsp-profiles.lua`
- **LSP config**: `nvim/.config/nvim/lua/plugins/lsp.lua`
- **Local config**: `~/.config/nvim/lsp-local.lua` (git-ignored, machine-specific)
- **Example files**:
  - `nvim/.config/nvim/lsp-local.lua.example` (detailed examples)
  - `nvim/.config/nvim/lsp-local.lua.example.full`
  - `nvim/.config/nvim/lsp-local.lua.example.minimal`

## Key Features

### 1. Machine-Specific Configuration

Each machine can have its own `lsp-local.lua` without committing to git.

### 2. Profile Hierarchy

- Profiles provide pre-configured server groups
- `lsp-local.lua` can extend any profile
- Custom servers override profile settings

### 3. Lazy Loading

- Servers only load when opening relevant files
- Faster startup time
- Lower memory usage

### 4. Fallback System

- If no `lsp-local.lua` exists, uses `minimal` profile
- Ensures Neovim always works with basic LSP support

## Technical Details

### Profile Structure

Each profile in `lsp-profiles.lua` contains:

```lua
{
  profile_name = {
    servers = {
      server_name = {
        lazy = { filetype = {...} },
        settings = { /* server settings */ },
        -- other server config options
      },
    },
    ensure_installed = { /* mason tools */ },
  },
}
```

### Server Configuration Options

- `lazy` - Lazy loading triggers
- `settings` - Server-specific settings
- `handlers` - Custom event handlers
- `on_attach` - Function called when server attaches
- `cmd` - Custom command to start server
- `root_dir` - Custom root directory detection
- `filetypes` - Override default filetypes

## Advanced Examples

### Custom Root Directory for ESP32

```lua
return {
  profile = 'minimal',
  custom_servers = {
    clangd = {
      lazy = { filetype = { 'c', 'cpp' } },
      cmd = {
        'clangd',
        '--compile-commands-dir=build',
        '--header-insertion=never',
        '--query-driver=/path/to/xtensa-esp32-elf-gcc',
      },
      root_dir = require('lspconfig.util').root_pattern('CMakeLists.txt', '.git'),
    },
  },
}
```

### Multiple Profiles per Machine

You can create scripts to quickly switch profiles:

```bash
# Switch to web profile
alias nvim-web='echo "return '\''web'\''" > ~/.config/nvim/lsp-local.lua && nvim'

# Switch to python profile
alias nvim-python='echo "return '\''python'\''" > ~/.config/nvim/lsp-local.lua && nvim'
```

## Getting Help

- Check Neovim docs: `:help lspconfig`
- View all server configs: `:help lspconfig-all`
- Report issues: Check `:checkhealth vim.lsp` output
