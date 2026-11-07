# Agent dotfiles installer

Run from a reviewed checkout on **Linux, macOS, or WSL**, with Python 3.11+
(Codex uses `tomllib`), GNU Stow, and filesystem symlink support. Install the
agent CLIs separately. Native Windows is not guaranteed. No dependencies are
downloaded by the installer itself; plugin commands may access the network.

```sh
# Select tools explicitly; there is no implicit "install everything" mode.
python3 install-agents.py --tools claude codex hermes --check
python3 install-agents.py --tools claude codex hermes --skip-plugins

# Named Hermes packages instead of the default Hermes package:
python3 install-agents.py --tools hermes --profiles dotfiles-sync --check
python3 install-agents.py --tools hermes --profiles dotfiles-sync

# A different home, not a Hermes profile directory:
python3 install-agents.py --tools hermes --profiles dotfiles-sync --target /path/to/home
```

`--target` defaults to Python's `Path.home()`. The shared installer deliberately
ignores the invoking agent's `HERMES_HOME` and `CODEX_HOME`: the selected home is
authoritative. Named profile settings commands set `HERMES_HOME` to exactly
`TARGET/.hermes/profiles/NAME`. This differs from the standalone
`hermes/install.py`, whose default remains `$HERMES_HOME` or `~/.hermes`.

## Default tools

- **Claude:** plain GNU Stow of `openclaude` and `claude-skills`. Git settings
  and `claude-mods` are not implicitly installed.
- **Codex:** delegates to `codex/install.py`, retaining its private-settings
  merge, generated config, backups, folded agents and skill directories,
  migration checks, and plugin handling. It is not replaced with a generic
  symlink strategy. A generated config belongs to one target: use a separate
  checkout for another target. Recovery options remain on the standalone
  installer, not on this conservative wrapper.
- **Hermes without `--profiles`:** delegates to `hermes/install.py`, retaining
  local-setting precedence, real SOUL backup behavior, Stow and plugins.
  It now rejects unsupported home layouts before settings/SOUL writes and
  preflights Stow conflicts before applying settings. Named packages are
  excluded from the default Stow package.

`--skip-plugins` forwards to Codex and default Hermes. It suppresses plugin
activation, not linking of tracked plugin files. Named profiles do not deploy
plugins at all.

## Named Hermes packages

A reviewed package has this layout:

```text
hermes/profiles/NAME/
  SOUL.md
  config.base.yaml          # optional dotted.key: value defaults
  skills/
    SKILL-NAME/
      SKILL.md
      ...                   # reviewed support files
```

Names must match `[A-Za-z0-9][A-Za-z0-9_-]{0,63}`; `default` is reserved.
`--profiles` requires selecting Hermes. When supplied, it selects only those
named Hermes packages, not the default profile. Other explicitly selected
tools still deploy normally.

The installer links SOUL and each skill directory individually. It never links
the profile root or the shared skills root, and never copies credentials,
sessions, databases, memories, logs, caches, or runtime configuration from
another profile. Existing unrelated profile contents remain untouched.

Optional `config.base.yaml` uses the same restricted dotted-key/scalar input
format as `hermes/config.base.yaml`, not a general nested YAML document.
Settings are applied through native `hermes config set` only after all planned
link and settings-path conflicts have passed preflight. Existing local values
win; there is no named-profile force flag. `config.yaml` stays a local real
file, never a symlink to the reviewed input. The inherited author's
`HERMES_HOME` is not used for these commands.

A SOUL identifies a new named profile, but this deployer is not a substitute
for the supported Hermes profile lifecycle/setup CLI. Prefer creating a new
profile through Hermes first, then deploying the reviewed package. If that
creates a default SOUL, inspect and back it up outside the managed link before
removing it explicitly. This installer will **not** silently replace it.
Existing real files/directories (even an identical real SOUL), foreign links,
and redirected profile/skills parents are rejected. Correct existing managed
links are idempotent. No automatic conflict removal or backup flag is provided
for named profiles.

The `dotfiles-sync` package selects **Kimi Code** (`kimi-coding`,
`kimi-for-coding`). Authenticate that profile independently using supported
Hermes setup; credentials are not installed by dotfiles. A previous runtime
smoke test with Astra does not validate Kimi: Kimi runtime verification remains
pending authentication, as reported by the parent setup session.

## Dry run, preflight, and limits

`--check` performs validation and planning only: no target links, configuration,
credentials, backups, generated Codex files, or plugin changes. Hermes config
commands are not executed in check mode, including seemingly read-only
`config get` commands that could initialize runtime files. For a nonexistent
default-tool target, GNU Stow needs an existing directory, so the wrapper uses
and removes an empty temporary planning directory under `$TMPDIR`; it does not
create the requested target. Named-profile-only checks need no temporary tree.

All named links/settings inputs and all selected default-tool checks run before
application. Existing downstream installer checks can be conservative (notably
Codex's regular config/Stow conflicts); resolve those using the documented
standalone installer rather than bypassing the checks.

**Application is not a cross-tool transaction.** A later CLI/plugin failure,
permissions error, concurrent filesystem edit, or disk exhaustion can leave
earlier changes applied. Settings and links are also not one atomic unit.
Stop agents that could mutate these paths while installing, inspect failures,
and rerun after correcting them. The wrapper does not roll back runtime state.
It does not authenticate providers or prove a model is usable.

## Tests

```sh
# TMPDIR must point to an existing scratch directory outside the checkout.
python3 -m unittest discover -s tests -p 'test_install_agents.py' -v
```

Tests create isolated fixture repositories/homes under `$TMPDIR`, execute real
GNU Stow for default packages, and use mocked CLI subprocess calls for named
settings. They do not install into the live home or call model providers.
