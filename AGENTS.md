# AGENTS.md

## Repository map

- Most top-level tool directories are GNU Stow packages for user configuration. See `README.md` for the package list and exceptions.
- `pi/`, `codex/`, and the other agent packages hold harness configuration; see `AGENT-INSTALL.md` for setup.
- `claude-mods/` contains Claude Code plugins, loaded in place rather than stowed.

## Repository Commands

### Local validation

- From the repository root, run `python3 validate.py` for all supported local checks, or pass one or more of `stow`, `lua`, `claude`, and `herdr` to run a subset.
- Requires Python 3 and, for the selected checks, GNU Stow, StyLua, Claude Code, or Herdr respectively. The Stow check uses a temporary target and does not detect conflicts in your home directory. See `README.md` under Local validation for coverage.

### Configuration Management
- `stow <directory>` - Apply symlinks for specific configuration
- `stow -D <directory>` - Remove symlinks
- `stow */` - Apply all dotfiles to home directory
- `stow -R openclaude claude-skills git` - link the Claude Code packages into `~/.claude` and the git ignore into `~/.config/git` (plain stow, no wrapper script)
- Claude mods in `claude-mods/` are not stowed: `~/.claude/settings.json` names them in `env.CLAUDE_CODE_PLUGIN_DIRS`. Check one with `claude plugin validate claude-mods/<mod>` and `claude plugin test claude-mods/<mod>`
- `python3 codex/install.py` - merge private Codex settings with tracked MCP defaults, then stow `codex` and `codex-skills` without folding runtime directories
- `stow codex-skills` - link a fresh Codex skills installation into `~/.agents/skills`; use the installer to migrate old file-level links
- `stow kimi` - link the Kimi Code package into `~/.kimi-code` (global AGENTS.md; `config.toml`, `mcp.json` and credentials stay local like Codex private config)
- `python3 hermes/install.py` - apply tracked Hermes settings with `hermes config set` (local values win), link `~/.hermes/SOUL.md` after backing up a real file, stow Hermes-only skills, and enable tracked local plugins; `--check` is a dry run
- `bat cache --build` - Rebuild bat syntax highlighting themes

Everything is stowed, never copied, so an edit under `~/.config` or `~/.claude`
changes the repo file and shows up in `git status`. Stow folds per entry, which
is what keeps tools' runtime state (herdr sockets and logs, `~/.claude/projects`)
out of the repo while the config beside it is tracked.

### Neovim (Lua)
- `stylua --check .` - Lint Lua files
- `stylua .` - Format Lua files
- `nvim --headless -c "lua require('lazy').sync()" -c "qa"` - Update plugins

### Tmux
- `tmux source-file ~/.config/tmux/tmux.conf` - Reload configuration
- `~/.config/tmux/plugins/tpm/bin/install_plugins` - Install TPM plugins

### Herdr
- `herdr config check` - Validate `config.toml`
- `herdr server reload-config` - Apply config changes without restarting the server
- `herdr --default-config` - Print the full option reference
- `herdr plugin list` - Installed plugins with their pinned commits (four: workspace-manager, reviewr, file-viewer, herdr-plus)
- `herdr plugin action list` - Action ids, needed to bind a key (`<plugin_id>.<action_id>`)
- `herdr plugin action invoke validate --plugin herdr-plugin-workspace-manager` - Validate project layouts
- `herdr plugin log list --plugin herdr-plugin-workspace-manager --limit 1` - Read plugin action output (actions are async)

Plugin configs are stowed from `herdr/.config/herdr/plugins/config/<plugin_id>/`.
workspace-manager owns worktree layout (it routes by branch name); herdr-plus
owns on-demand project start. Its `worktrees/` dir is deliberately empty — both
plugins answer `worktree.created`, and that absence is what keeps them apart.

## Code Style Guidelines

### Lua (Neovim)
- Use 2 spaces for indentation
- Prefer single quotes for strings
- Column width: 160 characters
- Modular structure: separate core functionality from plugins
- Use `require` for module imports
- Error handling with `pcall` or `vim.validate`

### Shell (Zsh)
- Use Oh My Zsh framework conventions
- Aliases should be short and descriptive
- Export environment variables in uppercase
- Use functions for complex operations

### Configuration Files
- Follow XDG Base Directory specification
- Use Catppuccin color scheme consistently
- TOML for Alacritty, YAML for K9s, JSONC for Waybar
- Keep configurations modular and tool-specific

### General
- No inline comments unless explicitly requested
- Use semantic versioning for any versioned configs
- Maintain backward compatibility when possible
- Test changes locally before committing

## Merging and cleanup

An unqualified `push` or `commit and push` includes local squash integration
into `main` and pushing that result. Explicit branch-only pushes and PR
requests retain their requested scope.

This repo has no CI, intentionally: that is its validation policy for the
merged-task cleanup rule. Validate locally (stow dry run, `claude plugin
validate`/`test` for a mod), squash-merge the task branch into `main` and push.
Once `origin/main` is fetched and holds the squash commit, delete the task
branch (exact-SHA guarded, remote with a lease) at once; do not wait for CI.
Branches that are not the task's merged branch stay.
