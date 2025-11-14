# Dotfiles

A comprehensive collection of configuration files for a modern development environment using Arch Linux, Wayland, and a Catppuccin color scheme.

## Overview

This repository contains my personal dotfiles, organized and managed using GNU Stow for easy symlinking to the appropriate locations in the home directory. The configuration emphasizes a cohesive development workflow with consistent theming and efficient tooling.

## Quick Start

### Initial Setup
```bash
# Clone the repository
git clone <repository-url> ~/dotfiles
cd ~/dotfiles

# Apply all configurations
stow */

# Install required dependencies
sudo pacman -S zsh git neovim tmux kitty bat fzf

# Install Oh My Zsh
sh -c "$(curl -fsSL https://raw.github.com/ohmyzsh/ohmyzsh/master/tools/install.sh)"

# Install TPM (Tmux Plugin Manager)
git clone https://github.com/tmux-plugins/tpm ~/.tmux/plugins/tpm
```

### Post-Installation Steps
```bash
# Rebuild bat cache for theme support
bat cache --build

# Install tmuxinator for project management
gem install tmuxinator

# Install Powerlevel10k Zsh theme
git clone --depth=1 https://github.com/romkatv/powerlevel10k.git ${ZSH_CUSTOM:-$HOME/.oh-my-zsh/custom}/themes/powerlevel10k
```

## Configuration Structure

### Core Components

#### Shell Environment (Zsh + Oh My Zsh)
- **Framework**: Oh My Zsh with Powerlevel10k prompt
- **Features**: Extensive aliases, git workflow shortcuts, Kubernetes tools
- **Key Files**: `zshrc/.zshrc`, `p10k/.p10k.zsh`

#### Text Editor (Neovim)
- **Configuration**: Lua-based modular setup with Lazy.nvim plugin manager
- **Features**: LSP, completion, git integration, custom keybindings
- **Location**: `nvim/`

#### Terminal Multiplexer (Tmux)
- **Manager**: TPM (Tmux Plugin Manager)
- **Features**: Session persistence, vim navigation, Catppuccin theme
- **Location**: `tmux/`

#### Window Manager (Hyprland)
- **System**: Wayland compositor with optimized settings
- **Theme**: Catppuccin color scheme throughout
- **Location**: `hyprland/`

### Tool Configurations

| Tool | Description | Location |
|------|-------------|----------|
| **Kitty** | Terminal emulator with GPU acceleration | `kitty/` |
| **Bat** | Cat clone with syntax highlighting | `bat/` |
| **K9s** | Kubernetes cluster management UI | `k9s/` |
| **Atuin** | Shell history management | `atuin/` |
| **Tmuxinator** | Project templating system | `tmuxinator/` |

## Key Features

### Development Workflow
- **Git Integration**: Comprehensive aliases and shortcuts
- **FZF Integration**: Fuzzy finding for files and commands
- **Project Management**: Tmuxinator templates for quick project setup
- **Shell History**: Atuin for searchable command history

### Theming
- **Color Scheme**: Catppuccin Mocha across all applications
- **Consistency**: Unified visual experience
- **Customization**: Optimized color palettes for different tools

### Performance Optimizations
- **Lazy Loading**: Neovim plugins loaded on demand
- **Efficient Keybindings**: Vim-inspired navigation everywhere
- **Resource Management**: Optimized startup times

## Directory Structure

```
dotfiles/
├── README.md          # This file
├── CLAUDE.md          # AI assistant guidance
├── .git/              # Git configuration
├── zshrc/             # Zsh shell configuration
├── nvim/              # Neovim configuration
├── tmux/              # Tmux configuration
├── hyprland/          # Window manager settings
├── kitty/             # Terminal emulator config
├── p10k/              # Powerlevel10k prompt config
├── tmuxinator/        # Project templates
├── k9s/               # Kubernetes tool config
├── atuin/             # Shell history tool
├── bat/               # Bat configuration
└── [other tools]/     # Additional application configs
```

## Usage

### Managing Configurations
```bash
# Apply specific configuration
stow <directory>

# Remove configuration symlinks
stow -D <directory>

# List all stowed packages
stow -t ~ -v
```

### Common Workflows

#### Development Session
```bash
# Start new project with tmuxinator
tmuxinator new project-name

# Navigate with fuzzy finding
fcd  # Change directory
fv   # Edit file
f    # Find file
```

#### Git Workflow
```bash
# Enhanced git aliases (defined in .zshrc)
gaa   # Add all files
gc    # Commit with message
gp    # Push to remote
gco   # Checkout branch
```

## Requirements

### System Dependencies
- **OS**: Arch Linux (or compatible)
- **Shell**: Zsh with Oh My Zsh
- **Display Server**: Wayland
- **Window Manager**: Hyprland

### Package Dependencies
```bash
# Core utilities
pacman -S zsh git neovim tmux kitty fzf bat

# Development tools
pacman -S nodejs npm go python

# Window management
pacman -S hyprland waybar wofi

# Additional tools
pacman -S k9s atuin
```

## Customization

### Adding New Configurations
1. Create directory structure following XDG Base Directory specification
2. Add configuration files to appropriate subdirectory
3. Use `stow <directory>` to create symlinks
4. Test configuration changes

### Theme Customization
- All configurations use Catppuccin color scheme
- Color definitions can be modified in theme files
- Most tools support theme switching

## Troubleshooting

### Common Issues
- **Stow conflicts**: Use `stow -D <directory>` to remove existing symlinks
- **Permission issues**: Ensure proper ownership of configuration files
- **Theme not applying**: Rebuild caches with `bat cache --build`

### Getting Help
- Check individual tool documentation for specific issues
- Verify all dependencies are installed
- Ensure proper stow target directory (~)

## Contributing

This is a personal configuration repository. Feel free to:
- Fork and adapt configurations to your needs
- Submit issues for bug reports or questions
- Suggest improvements through pull requests

## License

Personal use. Adapt as needed for your own workflow.
