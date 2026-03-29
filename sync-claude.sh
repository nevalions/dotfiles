#!/bin/bash
# Sync Claude Code config files from dotfiles to home

CONFIG_DIR="$HOME/.claude"
SOURCE_DIR="$(dirname "$(realpath "$0")")/openclaude/.claude"

echo "Syncing Claude Code config..."

# Copy config files (not runtime data)
cp -v "$SOURCE_DIR"/CLAUDE.md "$CONFIG_DIR/"
cp -v "$SOURCE_DIR"/AGENTS.md "$CONFIG_DIR/"
cp -v "$SOURCE_DIR"/settings.json "$CONFIG_DIR/"
cp -v "$SOURCE_DIR"/tui.json "$CONFIG_DIR/"
cp -rv "$SOURCE_DIR"/templates/ "$CONFIG_DIR/"
cp -rv "$SOURCE_DIR"/commands/ "$CONFIG_DIR/"

echo "Done! Config files synced to ~/.claude/"
