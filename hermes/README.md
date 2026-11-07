# Hermes Agent

Hermes counterpart to `openclaude/`, `codex/` and `kimi/`. What is tracked here
is the portable part of `~/.hermes`: the agent identity, the settings that are
deliberate choices rather than machine defaults, the env template, any
Hermes-only skills, local plugins, named bot profiles, and the agent-hooks
guard scripts.

Everything Hermes writes while running stays local: `config.yaml`, `.env`,
`auth.json`, `state.db`, `sessions/`, `logs/`, `memories/`, `cache/`, `tools/`,
`updates/`, bundled skills, desktop plugins, pets.

## Install

Requires Hermes, GNU Stow and Python 3.9+.

```sh
python3 hermes/install.py --check    # what would change, writes nothing
python3 hermes/install.py
```

The installer does two things:

1. **Settings.** Applies `config.base.yaml` with `hermes config set`. A key that
   is already present in the live `config.yaml` is kept as-is, so local choices
   win; pass `--force` to replace them. `config.yaml` is never edited directly
   or symlinked.
2. **Files.** Backs up a real `~/.hermes/SOUL.md` to `~/.hermes/backups/` and
   replaces it with a link to `hermes/.hermes/SOUL.md`, stows the package so
   custom skills and plugins link into the repo, then enables each tracked
   plugin (Hermes plugins are opt-in).

Useful flags: `--skip-settings`, `--skip-stow`, `--skip-plugins`, `--home <path>`
(a `HERMES_HOME` override; the directory must be named `.hermes`, matching the
package layout).

## Settings

`config.base.yaml` is one `dotted.key: value` per line. Add a setting there,
then re-run the installer; it applies only keys the live config does not have
yet. To change a key that is already set, either pass `--force` or use
`hermes config set <key> <value>` and update the tracked line to match.

Current tracked choices:

| Key | Value | Why |
|-----|-------|-----|
| `model.default` | `deepseek-flash` | provider default on this machine |
| `model.provider` | `deepseek` | |
| `model.base_url` | `https://api.deepseek.com` | |
| `agent.max_turns` | `150` | longer tool loops than the stock 500 are not wanted |
| `agent.reasoning_effort` | `high` | |
| `skills.external_dirs` | `["~/.agents/skills"]` | shares skills with Codex and Kimi Code |

API keys are **not** here. They belong in `~/.hermes/.env`; `.env.example`
lists the documented variables and is the only env file in the repo.

## Skills

Two sources, both intentional:

- `~/.agents/skills` — stowed from `codex-skills/`, shared with Codex and Kimi
  Code, and now read by Hermes through `skills.external_dirs`. External dirs are
  read-only and local skills win name collisions. Keep `beads` only in this
  shared tree; a Hermes-local copy would shadow its ownership safeguards.
  Claude links the same canonical skill, and Codex selects it through
  `skills.config`. Use a unique session actor and atomic issue claims as
  documented there.
- `~/.hermes/skills` — Hermes' own tree. Bundled skills are managed by
  `hermes update` and are not tracked. Hermes-only skills go in this repo at
  `hermes/.hermes/skills/<category>/<name>/SKILL.md`, then `stow hermes`.

Stow folds the deepest missing directory into a single link — normally the
skill directory, or its category directory when the category is new — so files a
skill adds later (`references/`, scripts) also land in the repo. Keep
`~/.hermes/skills/` existing before stowing; the installer creates it.

## Plugins

Local plugins live in `hermes/.hermes/plugins/<name>/` (`plugin.yaml` + code),
are stowed into `~/.hermes/plugins/`, and are enabled by the installer, because
Hermes plugins are opt-in through `plugins.enabled`.

- **`q-quit`** — `/q` exits the CLI, same as `/quit`, instead of queueing a
  prompt. Aliases resolve from the built-in registry before plugin commands,
  skills or `quick_commands`, so the plugin moves the alias at load time rather
  than registering a command; see `hermes/.hermes/plugins/q-quit/README.md`.
  `/queue` keeps its other spellings.

## Profiles

Named bots live in `profiles/<name>/` with the same shape as the package
root: `SOUL.md`, `config.base.yaml`, and optionally `skills/<skill>/`. Each
file is symlinked from `~/.hermes/profiles/<name>/` (same convention as the
package-root `SOUL.md`: the repo owns content, the profile home holds links;
`config.yaml` stays a real, runtime-managed file and the tracked base is
applied with `hermes config set` the same way as the root base). The
installer does not touch profiles yet — linking is deliberate per profile.

| Profile | Model | Skill |
|---------|-------|-------|
| `dotfiles-sync` | kimi-for-coding | dotfiles-sync |
| `beads-coordinator` | gpt-6-luna (openai-codex) | beads-coordination |
| `bot-creator` | gpt-6-astra (openai-codex) | create-hermes-bot |
| `commiter` | deepseek-flash (deepseek) | — |
| `feature-wiki` | gpt-6.1-sol (openai-codex) | feature-wiki |
| `orchestrator` | gpt-6-astra (openai-codex) | orchestration |
| `repo-scout` | kimi-for-coding (kimi-coding) | — |
| `skill-creator` | gpt-6.1-sol (openai-codex) | — |
| `wiki-skill` | gpt-6.1-sol (openai-codex) | — |

`profile.yaml` (roster description, avatar metadata) is runtime-managed by
the desktop app and is not tracked.

## Agent hooks

`agent-hooks/` holds the `pre_tool_call` guard scripts wired in live
`config.yaml` (`hooks.pre_tool_call`, e.g. the Obsidian vault RO/ guard).
They are stowed into `~/.hermes/agent-hooks/` like plugins. The hook list
itself is not in `config.base.yaml`: the installer format only carries flat
scalar keys, so hooks stay a live-config choice.

## Why config.yaml is not stowed

`~/.hermes/config.yaml` is rewritten at runtime: `hermes config set`, startup
migrations, and `hermes update` all change its shape, and it is the file the
gateway reads live. Linking it into a public repo would either publish machine
state or let a runtime write corrupt the tracked copy. The tracked file is an
input (`config.base.yaml`) that the installer applies through the supported
command, same idea as `codex/config.base.toml`.

`SOUL.md` is different: Hermes only reads it, so it is linked. The installer
owns the replace step because it must back up a real file first, which is why
`.stow-local-ignore` excludes it from plain `stow hermes`.

## On another machine

```sh
git clone <repo> ~/dotfiles
cd ~/dotfiles
python3 hermes/install.py --check
python3 hermes/install.py
cp hermes/.env.example ~/.hermes/.env   # then fill in keys
hermes doctor
```

## Uninstall

```sh
stow -D -t ~ hermes          # removes skill links
rm ~/.hermes/SOUL.md          # restore the newest backup from ~/.hermes/backups if needed
```

Settings set by the installer stay in `config.yaml`; remove them with
`hermes config unset <key>`.
