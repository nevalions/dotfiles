return {
  minimal = {
    servers = {
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
      bashls = {
        lazy = { filetype = { 'sh', 'zsh', 'zshrc' } },
      },
    },
    ensure_installed = { 'stylua', 'lua-language-server', 'bash-language-server' },
  },

  web = {
    servers = {
      ts_ls = {
        lazy = { filetype = { 'typescript', 'typescriptreact', 'typescript.tsx' } },
      },
      html = {
        lazy = { filetype = { 'html', 'twig', 'hbs' } },
      },
      cssls = {
        lazy = { filetype = 'css' },
      },
      tailwindcss = {
        lazy = { filetype = { 'css', 'html' } },
      },
      jsonls = {
        lazy = { filetype = 'json' },
      },
    },
    ensure_installed = {},
  },

  python = {
    servers = {
      ruff = {
        lazy = { filetype = 'python' },
        settings = {
          fixAll = true,
          codeAction = {
            disableRules = {
              enablement = true,
            },
          },
        },
      },
      pyright = {
        lazy = { filetype = 'python' },
        handlers = {
          ['textDocument/publishDiagnostics'] = function() end,
        },
        on_attach = function(client, _)
          client.server_capabilities.codeActionProvider = false
        end,
        settings = {
          pyright = {
            disableOrganizeImports = true,
          },
          python = {
            analysis = {
              autoSearchPaths = true,
              typeCheckingMode = 'basic',
              useLibraryCodeForTypes = true,
            },
          },
        },
      },
      pylsp = {
        lazy = { filetype = 'python' },
        settings = {
          pylsp = {
            plugins = {
              pyflakes = { enabled = false },
              pycodestyle = { enabled = false },
              autopep8 = { enabled = false },
              yapf = { enabled = false },
              mccabe = { enabled = false },
              pylsp_mypy = { enabled = false },
              pylsp_black = { enabled = false },
              pylsp_isort = { enabled = false },
            },
          },
        },
      },
    },
    ensure_installed = {},
  },

  angular = {
    servers = {
      ts_ls = {
        lazy = { filetype = { 'typescript', 'typescriptreact', 'typescript.tsx' } },
      },
      angularls = {
        filetypes = { 'typescript', 'html', 'typescriptreact', 'typescript.tsx', 'htmlangular' },
      },
      html = {
        lazy = { filetype = { 'html', 'twig', 'hbs' } },
      },
      cssls = {
        lazy = { filetype = 'css' },
      },
      tailwindcss = {
        lazy = { filetype = { 'css', 'html' } },
      },
      jsonls = {
        lazy = { filetype = 'json' },
      },
    },
    ensure_installed = {},
  },

  esp32 = {
    servers = {
      clangd = {
        lazy = { filetype = { 'c', 'cpp' } },
        cmd = {
          'clangd',
          '--compile-commands-dir=build',
          '--header-insertion=never',
          '--query-driver=/home/linroot/.espressif/tools/xtensa-esp32-elf/**/xtensa-esp32-elf-*',
        },
        root_dir = require('lspconfig.util').root_pattern('CMakeLists.txt', '.git'),
        settings = {
          clangd = {
            compileCommands = { 'build/compile_commands.json' },
            fallbackFlags = {
              '-I',
              os.getenv 'HOME' .. '/esp-idf/components',
              '-I',
              os.getenv 'HOME' .. '/esp-idf/components/esp_wifi/include',
              '-I',
              os.getenv 'HOME' .. '/esp-idf/components/esp_common/include',
              '-target',
              'xtensa-esp32-elf',
              '-std=gnu99',
              '-DESP32',
            },
          },
        },
      },
    },
    ensure_installed = { 'clangd' },
  },

  full = {
    servers = {
      bashls = {
        lazy = { filetype = { 'sh', 'zsh', 'zshrc' } },
      },
      ts_ls = {
        lazy = { filetype = { 'typescript', 'typescriptreact', 'typescript.tsx' } },
      },
      angularls = {
        filetypes = { 'typescript', 'html', 'typescriptreact', 'typescript.tsx', 'htmlangular' },
      },
      ruff = {
        lazy = { filetype = 'python' },
        settings = {
          fixAll = true,
          codeAction = {
            disableRules = {
              enablement = true,
            },
          },
        },
      },
      pyright = {
        lazy = { filetype = 'python' },
        handlers = {
          ['textDocument/publishDiagnostics'] = function() end,
        },
        on_attach = function(client, _)
          client.server_capabilities.codeActionProvider = false
        end,
        settings = {
          pyright = {
            disableOrganizeImports = true,
          },
          python = {
            analysis = {
              autoSearchPaths = true,
              typeCheckingMode = 'basic',
              useLibraryCodeForTypes = true,
            },
          },
        },
      },
      pylsp = {
        lazy = { filetype = 'python' },
        settings = {
          pylsp = {
            plugins = {
              pyflakes = { enabled = false },
              pycodestyle = { enabled = false },
              autopep8 = { enabled = false },
              yapf = { enabled = false },
              mccabe = { enabled = false },
              pylsp_mypy = { enabled = false },
              pylsp_black = { enabled = false },
              pylsp_isort = { enabled = false },
            },
          },
        },
      },
      cssls = {
        lazy = { filetype = 'css' },
      },
      tailwindcss = {
        lazy = { filetype = { 'css', 'html' } },
      },
      dockerls = {
        lazy = { filetype = 'dockerfile' },
      },
      sqlls = {
        lazy = { filetype = 'sql' },
      },
      jsonls = {
        lazy = { filetype = 'json' },
      },
      yamlls = {
        lazy = { filetype = 'yaml' },
        settings = {
          yaml = {
            schemas = {
              kubernetes = 'k8s-*.yaml',
              ['http://json.schemastore.org/github-workflow'] = '.github/workflows/*',
              ['http://json.schemastore.org/github-action'] = '.github/action.{yml,yaml}',
              ['http://json.schemastore.org/ansible-stable-2.9'] = 'roles/tasks/*.{yml,yaml}',
              ['http://json.schemastore.org/prettierrc'] = '.prettierrc.{yml,yaml}',
              ['http://json.schemastore.org/kustomization'] = 'kustomization.{yml,yaml}',
              ['http://json.schemastore.org/ansible-playbook'] = '*play*.{yml,yaml}',
              ['http://json.schemastore.org/chart'] = 'Chart.{yml,yaml}',
              ['https://json.schemastore.org/dependabot-v2'] = '.github/dependabot.{yml,yaml}',
              ['https://json.schemastore.org/gitlab-ci'] = '*gitlab-ci*.{yml,yaml}',
              ['https://raw.githubusercontent.com/OAI/OpenAPI-Specification/main/schemas/v3.1/schema.json'] = '*api*.{yml,yaml}',
              ['https://raw.githubusercontent.com/compose-spec/compose-spec/master/schema/compose-spec.json'] = '*docker-compose*.{yml,yaml}',
              ['https://raw.githubusercontent.com/argoproj/argo-workflows/master/api/jsonschema/schema.json'] = '*flow*.{yml,yaml}',
            },
          },
        },
      },
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
      clangd = {
        lazy = { filetype = { 'c', 'cpp' } },
        cmd = {
          'clangd',
          '--compile-commands-dir=build',
          '--header-insertion=never',
          '--query-driver=/home/linroot/.espressif/tools/xtensa-esp32-elf/**/xtensa-esp32-elf-*',
        },
        root_dir = require('lspconfig.util').root_pattern('CMakeLists.txt', '.git'),
        settings = {
          clangd = {
            compileCommands = { 'build/compile_commands.json' },
            fallbackFlags = {
              '-I',
              os.getenv 'HOME' .. '/esp-idf/components',
              '-I',
              os.getenv 'HOME' .. '/esp-idf/components/esp_wifi/include',
              '-I',
              os.getenv 'HOME' .. '/esp-idf/components/esp_common/include',
              '-target',
              'xtensa-esp32-elf',
              '-std=gnu99',
              '-DESP32',
            },
          },
        },
      },
    },
    ensure_installed = { 'stylua', 'clangd' },
  },
}
