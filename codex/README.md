# Codex synchronization

This package keeps portable Codex preferences and global instructions in dotfiles.
The skills manifest links selected existing repository skills into the user's
`.agents/skills` directory. It does not duplicate the Claude skills package.

On Windows, install Python 3.11 or newer and enable Windows Developer Mode for
symbolic links. Run from any directory:

```powershell
& C:\code\dotfiles\scripts\sync-windows.ps1
& C:\code\dotfiles\scripts\sync-windows.ps1 -Apply
```

The first command previews changes. The second applies and verifies them.
`-TargetHome`, `-CodexHome`, `-RepoRoot`, and `-Python` override the defaults.
`CODEX_HOME` is honored when it is set. Restart Codex after deployment.

`settings.json` contains only selected top-level portable settings. Edit this
file in the repository and rerun the script to update them. The script parses
the local config, merges those selected values, and validates that all other
values remain unchanged. It preserves local MCP configuration, plugin entries,
project trust and Windows paths. Unlike instructions and skills, the config file
stays a local file because Codex also writes machine-specific state to it.

Global instructions and each selected skill directory are symbolic links.
Editing those files through the user directory updates the repository directly.
Existing `.agents/skills/synced` and bundled skills remain intact.

Replaced entries are moved into `$CODEX_HOME/dotfiles-backups/<timestamp>/`.
If deployment fails, the script restores replaced entries. To restore manually,
close Codex, remove the newly created link at the corresponding destination,
and move its saved entry back from the backup directory. For a changed config,
restore the saved `config.toml`. Newly installed skills with no prior entry can
be removed by deleting their links without deleting the repository sources.

The package does not export authentication, secret environment values, session
history, databases, caches or installed plugin contents. Plugin installation
and service login are managed by Codex; this script preserves their local
configuration. Review changes before committing or pulling on another machine.

On Linux, run `python3 scripts/sync-codex.py --apply` from the checkout to merge
settings and link instructions and selected skills. `--repo` and `--home` can
override the defaults. Do not stow this package or the entire `.codex` directory.
