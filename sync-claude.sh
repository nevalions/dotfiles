#!/bin/bash
# Sync Claude Code config from dotfiles to home.
#
# Everything is stowed, never copied: ~/.claude/<entry> symlinks back into this
# repo, so edits are live in both directions and `git status` always reflects
# what is actually in use. Stow folds into the existing ~/.claude/, linking only
# the packaged entries and leaving Claude Code's runtime data alone
# (projects/, history.jsonl, plugins/, daemon.lock, ...).
#
#   openclaude/     CLAUDE.md, AGENTS.md, settings.json, tui.json,
#                   commands/, templates/  ->  ~/.claude/
#   claude-skills/  agent skills           ->  ~/.claude/skills/
#
# Never stow ~/.claude wholesale: Claude Code writes into that directory
# continuously, so only per-entry folding is safe.

set -euo pipefail

DOTFILES_DIR="$(dirname "$(realpath "$0")")"
PACKAGES=(openclaude claude-skills)

if ! command -v stow >/dev/null 2>&1; then
    echo "stow not found; install with: sudo pacman -S stow" >&2
    exit 1
fi

echo "Stowing Claude Code config..."
for pkg in "${PACKAGES[@]}"; do
    echo "  $pkg"
    stow -d "$DOTFILES_DIR" -t "$HOME" -R "$pkg"
done

echo "Done! ~/.claude is linked to $DOTFILES_DIR"
