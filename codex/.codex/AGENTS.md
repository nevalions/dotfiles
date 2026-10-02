# Global Instructions

## Git

Author: linroot <nevalions@gmail.com>. No co-authored-by lines.
Prefixes: feat, fix, refactor, docs, chore. Non-interactive only. `git add <file>` not `-A`.
Multi-line messages go in a file and commit with `-F`, never inline `-m`: the shell
command-substitutes backticks and silently truncates the message. Read it back with
`git log -1 --format=%B` afterwards.
Branches: feature/ bugfix/ hotfix/ refactor/ docs/ → atomic commits → squash merge to master → tag → cleanup.
kube-lvl47: the squash happens server-side through a PR (`scripts/ship.sh`); never merge
into master locally, never work in the main clone — worktree per task.

## Worktrees

Default to a feature branch in the current checkout. Use an isolated Git worktree when other agents or sessions may write to the repo, or unrelated dirty work would interfere. Read-only agents need no worktree. Follow project setup instructions; ignored environment files and installed dependencies are absent in fresh checkouts. Never copy secrets into tracked files. `bd` discovers the shared tracker.

## Forgejo

Solo owner. Write actions only when requested. No settings/secrets changes unless stated. Plan before PRs/merges.

## Scope of changes

If, while working or testing, you find a pre-existing bug, a performance concern, or behavior the task doesn't mention, don't fix, optimize or extend it in this change unless the requested behavior cannot work without it; report it as a follow-up in your summary. Commit tests only where the task asks for them or the repo already keeps tests for this kind of change, sized like the neighboring test files; scratch checks need not be kept.

When it will not affect the end result, surgically edit a file rather than rewrite the entire thing.

## Subagents

Delegate when the user or applicable project/skill instructions request it. Use the read-only `explorer` for searches and `code-reviewer` for reviews. Inherit the current model unless a suitable Codex model has been explicitly configured. Keep task prompts narrow, carry findings rather than transcripts, and run targeted checks before broader project checks.

## MCP sources

1. Context7 — docs, APIs, patterns (primary)
2. Perplexity (`perplexity_search`) — security, ecosystem, comparisons (fallback)

Priority: official standards > official docs > community > blogs.

## Beads (bd)

Per-repo issue tracker (`bd`). Data lives in `.beads/`. Run `bd prime` for full workflow. If a repo has no `.beads/`, `bd init` first.

Priority: `-p 0..4`, **0 = highest**. 0=Urgent 1=High 2=Medium 3=Low 4=Trivial.

Descriptions/notes: plain text or markdown (no HTML). Use `bd remember` for persistent knowledge, rather than a separate memory file.

Core commands: `bd ready` (available work), `bd show <id>`, `bd create "<title>" -p <0-4> -l <labels> -d <desc> --acceptance <ac>`, `bd update <id> --claim` (start), `bd update <id> --append-notes <text>` (progress), `bd close <id>` (done), `bd list --status open --json`.

## Secrets and logins (Vaultwarden via rbw)

Passwords, tokens and keys live in the human vault (`vault.butakov.su`). When a
command needs a credential, or a login is required, **first check
`command -v rbw`**. If it exists, fetch the value from the vault and hand it to
the consumer without ever printing it:

- `rbw list | grep -i <name>` to find the item (names only, safe to print).
- `rbw get '<item>' | <cmd> --password-stdin` for stdin-reading tools.
- `rbw-env VAR='<item>' -- <cmd>` (`~/.local/bin/rbw-env`) when the tool wants
  an env var; `VAR='<item>'/<username>` when names repeat,
  `VAR='<item>':<field>` for a custom field or `notes`.
- `rbw get '<item>' --field password` on a Secure note is empty: the value must
  be a Login, or the note needs a hidden custom field named `password`.

Never run a bare `rbw get` whose output lands in the terminal or the
transcript, never `echo`/`cat` a fetched secret, never paste one into chat. If
rbw is locked, the first call prompts the user through pinentry; if it is not
installed, say so and ask the user to run the login themselves (their own terminal).

**Windows:** rbw does not run there; the vault is reached with `bw` (Bitwarden
CLI, winget-pinned to 2026.6.x to match Vaultwarden — newer releases 404 during
login and leave a vault that will not unlock). Same rules: names only, never
print a value.

- `bw status` reports `unlocked` only when `BW_SESSION` is set in this process.
  Unlocking needs the master password, so if it is locked, ask the user to run
  the command in their own terminal, and never paste `BW_SESSION`
  into chat.
- `bw list items --search <name> | jq -r '.[].name'` to find the item.
- `bw get password '<item>' | <cmd> --password-stdin` for stdin-reading tools.
- MCP keys (`FORGEJO_URL`, `FORGEJO_TOKEN`, `PERPLEXITY_API_KEY`) are user env
  vars that `~/.claude.json` references as `${VAR}`, filled by
  `C:\code\set-claude-secrets.ps1`. After re-running it, restart the terminal
  app, not just Claude Code: new tabs inherit the terminal's stale environment.

## Safety

No fabricated citations/standards. No assumed security posture. No AGENTS.md/CLAUDE.md in READMEs.

## Semgrep and research

Use the Semgrep CLI or project scan entry point before manual security review. Do not auto-fix findings without a request. File medium/high findings to bd when authorized. Prefer `$search` for Perplexity-backed research, with official sources first.
