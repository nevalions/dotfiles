# Agent dotfiles installer

Run from a reviewed checkout on **Linux, macOS, or WSL**, with Python 3.11+
(Codex uses `tomllib`), GNU Stow, and filesystem symlink support. Install the
agent CLIs separately. Native Windows is not guaranteed. No dependencies are
downloaded by the installer itself; plugin commands may access the network.

```sh
# Select tools explicitly; there is no implicit "install everything" mode.
python3 install-agents.py --tools claude codex hermes pi --check
python3 install-agents.py --tools claude codex hermes pi --skip-plugins

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

- **Pi:** links `~/.pi/agent/AGENTS.md`, the managed `extensions/provider-usage.ts` and `extensions/agy-worker.ts`, and the opt-in `pi-team` launcher, role files, and workflow docs without folding directories into symlinks. MCP config, OAuth and provider credentials, settings, skills, other extensions, and sessions remain local. Compare any existing real files with the package and move them to a backup before installing. Reload Pi afterward.

The Pi usage extension keeps the native session usage display for all providers. With `openai-codex` selected, it adds any available 5-hour and weekly quota windows from the authenticated **Codex CLI account**, which can differ from Pi’s login. It refreshes on startup, model selection, and after agent turns (at most once per minute), or on demand with `/usage-quota`. Other providers and unavailable windows are omitted. It does not read credential files or make model requests.

The installed AGY extension is auto-loaded by plain `pi`. Launch Pi from a disposable project or task worktree and explicitly ask it to use `agy_worker`. The default is AGY `gemini-4-hydrogen-high` at `high` effort. For a different plain-Pi worker, list IDs with `agy models` and launch, for example, `pi --agy-model gemini-4-neon-high --agy-effort high`.

Ask Pi: “Use `agy_worker` to create `hello.txt` with `hello` and a trailing newline. Tell AGY to use its file-write tool, not Bash, and to report back without running checks. Then verify the file yourself.” The worker model and effort are separate from Pi's own `--model` and `--thinking` options. Use a matching effort for model IDs that already include it.

The worker runs in Pi's current directory with AGY's `accept-edits` mode, a 10-minute deadline, and no permission bypass. AGY cannot prompt for shell permissions in print mode; if it denies a tool, inspect for partial edits and run the required checks separately in Pi. A worktree is not a permission sandbox. Use only projects you are authorized to share with AGY's model provider. `pi-team` pins its implementation worker to Hydrogen High regardless of plain-Pi flag settings and requires a linked Git worktree for delegation.

Run `pi-team --model jev/auto` for delegated coding with a session checklist and no routine plan-approval pauses. The wrapper alone loads the bundled subagent and todo extensions; scout, planner, and reviewer still run in Pi. Repository implementation requires `bd`, an existing issue, and the repo's documented sync procedure. Verify extension discovery with `/todos` in `pi-team` and tracker discovery with `bd where --json` from the task checkout. Tracker writes still require authorization. See the [Pi team runbook](pi/.pi/agent/team/README.md) and the [unattended factory plan](pi/.pi/agent/team/factory-plan.md). This installs an interactive team, not a dispatcher. It also links `~/.pi/agent/bin/pi-team-run` and the disabled-by-default watcher units. See the [pipeline runbook](pi/.pi/agent/team/pipeline.md) for restart recovery and opt-in scheduling.

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
