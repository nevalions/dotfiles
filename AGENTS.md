# AGENTS.md

## Repository Commands

### Configuration Management
- `stow <directory>` - Apply symlinks for specific configuration
- `stow -D <directory>` - Remove symlinks
- `stow */` - Apply all dotfiles to home directory
- `bat cache --build` - Rebuild bat syntax highlighting themes

### Neovim (Lua)
- `stylua --check .` - Lint Lua files
- `stylua .` - Format Lua files
- `nvim --headless -c "lua require('lazy').sync()" -c "qa"` - Update plugins

### Tmux
- `tmux source-file ~/.config/tmux/tmux.conf` - Reload configuration
- `~/.config/tmux/plugins/tpm/bin/install_plugins` - Install TPM plugins

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