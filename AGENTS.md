# AGENTS.md

## Repository Commands

### Configuration Management
- `stow <directory>` - Apply symlinks for specific configuration
- `stow -D <directory>` - Remove symlinks
- `stow */` - Apply all dotfiles to home directory
- `./sync-claude.sh` - Stow the Claude Code packages (`openclaude`, `claude-skills`) into `~/.claude`
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