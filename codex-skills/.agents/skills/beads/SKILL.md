---
name: beads
description: >
  Dolt-powered issue tracker for multi-session work with dependencies and persistent
  memory across conversation compaction. Use when work spans sessions, has blockers,
  or needs context recovery after compaction. Trigger with "create task", "what's
  ready", "track this work", "resume after compaction". Make sure to use this skill
  whenever managing multi-session work, tracking dependencies, or recovering context.
allowed-tools: "Read,Bash(bd:*)"
version: "0.60.0"
author: "Steve Yegge <steve.yegge@gmail.com>"
license: "MIT"
compatible-with: [claude-code, codex, hermes]
tags: [issue-tracking, task-management, multi-session, dependencies]
---

# Beads - Persistent Task Memory for AI Agents

Graph-based issue tracker that survives conversation compaction. Provides persistent memory for multi-session work with complex dependencies.

## bd vs TodoWrite

**Decision test**: "Will I need this context in 2 weeks?" YES = bd, NO = TodoWrite.

| bd (persistent) | TodoWrite (ephemeral) |
|-----------------|----------------------|
| Multi-session, dependencies, compaction survival | Single-session linear tasks |
| Dolt-backed team sync | Conversation-scoped |

See [BOUNDARIES.md](resources/BOUNDARIES.md) for detailed comparison.

## Prerequisites

```bash
bd --version  # Requires v0.60.0+
```

- **bd CLI** installed and in PATH
- **Git repository** (optional — use `BEADS_DIR` + `--stealth` for git-free operation)
- **Initialization**: `bd init` run once (humans do this, not agents)

## CLI Reference

**Run `bd prime`** for AI-optimized workflow context (auto-loaded by hooks).
**Run `bd <command> --help`** for specific command usage.

Essential commands: `bd ready`, `bd create`, `bd show`, `bd update`, `bd close`, `bd dolt push`

## Shared Claude, Codex and Hermes workspace

All three tools use this canonical skill and the same repository tracker. Before
tracking work, ask whether to create a new issue or update an existing one unless
the user already chose; a request to skip tracking means no issue writes.

Before any tracker write, choose a unique actor for this agent session, such as
`codex:<session-id>`, `claude:<session-id>` or `hermes:<profile>:<session-id>`.
Generate a UUID once if no session ID exists. Reuse the exact actor throughout
that session, including after compaction. Pass `--actor '<actor>'` on every bd
invocation, or set `BEADS_ACTOR` on every invocation if terminal environments do
not persist. Each concurrent worker needs its own actor; never inherit another
worker's actor. The default Git username is shared across tools and is unsafe
for ownership: a claim by the same actor is idempotent.

Run `bd where --json` from the task checkout before writing. Linked Git
worktrees normally discover the main repository's shared `.beads/` workspace.
Do not initialize a second tracker, set a different `BEADS_DIR`, or copy/import
issue data to make a worktree work. Diagnose discovery first; initialize only
when the user authorized a new tracker and none exists.

Read the explicit issue ID, then use `bd update <id> --claim` with your actor.
Proceed only after a successful claim. If another actor owns it, stop work on
that issue and coordinate with the user/owner. Do not use `--force`, overwrite
its assignee/status, or release another actor's claim. Use `--append-notes` for
progress rather than replacing notes. Mutate/close only your assigned issue,
with explicit IDs; apply the user's requested Git/CI completion gates before
closing. Issue-data pushes require the same user authorization as other writes
to remotes; the session protocol below does not grant that authorization.

## Session Protocol

1. `bd ready` — Find unblocked work
2. `bd show <id>` — Get full context
3. `bd update <id> --claim` — Claim and start work atomically
4. Add notes as you work (critical for compaction survival)
5. `bd close <id> --reason "..."` — Complete task
6. `bd dolt push` — Push to Dolt remote (if configured)

## Output

Append `--json` to any command for structured output. Use `bd show <id> --long` for extended metadata. Status icons: `○` open `◐` in_progress `●` blocked `✓` closed `❄` deferred.

## Error Handling

| Error | Fix |
|-------|-----|
| `database not found` | `bd init <prefix>` in project root |
| `not in a git repository` | `git init` first |
| `disk I/O error (522)` | Move `.beads/` off cloud-synced filesystem |
| Status updates lag | Use server mode: `bd dolt start` |

See [TROUBLESHOOTING.md](resources/TROUBLESHOOTING.md) for full details.

## Examples

**Track a multi-session feature:**
```bash
bd create "OAuth integration" -t epic -p 1 --json
bd create "Token storage" -t task --deps blocks:oauth-id --json
bd ready --json                    # Shows unblocked work
bd update <id> --claim --json      # Claim and start
bd close <id> --reason "Implemented with refresh tokens" --json
```

**Recover after compaction:** `bd list --status in_progress --json` then `bd show <id> --long`

**Discover work mid-task:** `bd create "Found bug" -t bug -p 1 --deps discovered-from:<current-id> --json`

## Advanced Features

| Feature | CLI | Resource |
|---------|-----|----------|
| Molecules (templates) | `bd mol --help` | [MOLECULES.md](resources/MOLECULES.md) |
| Chemistry (pour/wisp) | `bd pour`, `bd wisp` | [CHEMISTRY_PATTERNS.md](resources/CHEMISTRY_PATTERNS.md) |
| Agent beads | `bd agent --help` | [AGENTS.md](resources/AGENTS.md) |
| Async gates | `bd gate --help` | [ASYNC_GATES.md](resources/ASYNC_GATES.md) |
| Worktrees | `bd worktree --help` | [WORKTREES.md](resources/WORKTREES.md) |

## Resources

| Category | Files |
|----------|-------|
| **Getting Started** | [BOUNDARIES.md](resources/BOUNDARIES.md), [CLI_REFERENCE.md](resources/CLI_REFERENCE.md) (live reference pointers), [WORKFLOWS.md](resources/WORKFLOWS.md) |
| **Core Concepts** | [DEPENDENCIES.md](resources/DEPENDENCIES.md), [ISSUE_CREATION.md](resources/ISSUE_CREATION.md), [PATTERNS.md](resources/PATTERNS.md) |
| **Resilience** | [RESUMABILITY.md](resources/RESUMABILITY.md), [TROUBLESHOOTING.md](resources/TROUBLESHOOTING.md) |
| **Advanced** | [MOLECULES.md](resources/MOLECULES.md), [CHEMISTRY_PATTERNS.md](resources/CHEMISTRY_PATTERNS.md), [AGENTS.md](resources/AGENTS.md), [ASYNC_GATES.md](resources/ASYNC_GATES.md), [WORKTREES.md](resources/WORKTREES.md) |
| **Reference** | [STATIC_DATA.md](resources/STATIC_DATA.md), [INTEGRATION_PATTERNS.md](resources/INTEGRATION_PATTERNS.md) |

## Validation

If `bd --version` reports newer than `0.60.0`, this skill may be stale. Run `bd prime` for current CLI guidance — it auto-updates with each bd release and is the canonical source of truth ([ADR-0001](adr/0001-bd-prime-as-source-of-truth.md)).
