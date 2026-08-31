---
name: shell-history
description: "Search what was actually executed on this machine and across the fleet, from the atuin shell-history database via the atuin MCP server. Use before re-running anything with blast radius (has this been run, with what flags, did it exit 0), for post-mortems of a failed command or playbook, to answer 'did we already try this', to separate what a human ran from what an agent ran, and to reconstruct executed commands after a compaction. Do NOT use to read file contents, find code, or inspect commit history — that is Read, Grep and git log."
---

# Shell history (atuin)

Atuin records every command run in an instrumented shell: the command line, the
working directory, the exit code, the duration, the host, and — for agent-run
commands — the agent's name and its stated intent. Where a sync server is
configured, that record spans every host that syncs, not just this one.

## Why this matters

Three stores hold different things, and only one of them cannot be wrong about
what happened:

| Store | Holds | Can be wrong? |
|---|---|---|
| beads (`bd`) | intent, task state, decisions | it records what someone *meant* |
| claude-mem | observations, narrative | it is a summary |
| **atuin** | **commands executed, and their exit codes** | **no — it is a log** |

A transcript's account of a command is the agent's claim. Atuin is the receipt.
After a compaction, it is also the only surviving record of what was run.

## Tools

`atuin_history` — fuzzy search. Key parameters:

- `filter_modes` (required, first entry used): `global` (every synced host),
  `host` (this machine), `workspace` (current git repo), `directory`, `session`.
- `authors`: `$all-user` (human), `$all-agent` (any agent), or a literal name
  such as `claude-code`. Omit for everything.
- `only_failed`: non-zero exits only. Commands still running are excluded.
- `query`, `limit`.

`atuin_output` — see the hard limitation below before calling it.

## Query shapes worth knowing

| Question | Call |
|---|---|
| Has this playbook been run, and how? | `query: "ansible-playbook <name>"`, `filter_modes: ["workspace"]` |
| What is failing on this branch? | `only_failed: true`, `filter_modes: ["workspace"]` |
| What did the agent do here, and why? | `authors: ["claude-code"]`, `filter_modes: ["workspace"]` |
| What did the human run, as opposed to an agent? | `authors: ["$all-user"]` |
| What ran on another host before it broke? | `filter_modes: ["global"]` |
| What did I just run? | `query: ""`, `filter_modes: ["session"]` |

**Use exact-match syntax for a distinctive string**: prefix the term with `'`,
as in `'deploy-prod`. The query is fuzzy by default, and a fuzzy query for a
long or hyphenated string matches most of the database and buries the answer.
Other fzf-style operators work too: `^prefix`, `suffix$`, `!negate`, `r/regex/`.

## Four things that will otherwise waste your time

**`atuin_output` returns nothing for agent-run commands, and cannot.** Output
capture happens only in atuin's PTY proxy, which parses OSC 133 boundaries in an
interactive terminal. Agent commands run through a non-interactive shell with no
PTY, and `atuin history end` has no output field, so there is no path by which a
hook could store it. Do not call `atuin_output` on a command an agent ran, and
do not conclude from an empty result that something went wrong. You can see
**that** a command ran and how it exited — never what it printed.

**Absence is not proof.** `global` covers only hosts that actually sync. A host
that was never enrolled is invisible, so "no results" means "not found in the
synced set", not "never happened". Check coverage before reasoning from a
negative.

**A command run as `<shell> -c '…'` records nothing.** No interactive shell
means no `preexec` hook. To create an entry deliberately:

```sh
id=$(atuin history start -- "the command"); atuin history end --exit 0 "$id"
```

**Your own tool descriptions become the audit trail.** The one-line description
attached to each command you run is stored as the intent alongside it, and is
what a future session — or the user — reads back months later:

```
claude-code: Commit the squash merge        exit 0, 2.030s, ~/repo
```

Write it as the reason, not a restatement of the command. "Check whether the
migration already ran" is worth storing; "run psql" is not.

## The habit worth forming

Before re-running anything with real blast radius, ask the history whether it
has been run before, with which flags, and whether it exited 0. A destructive
playbook run in this fleet once destroyed data on two hosts; the absence of any
prior `--check` invocation was sitting in history, unread, the whole time.
