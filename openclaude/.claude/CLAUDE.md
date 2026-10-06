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

## Merged task cleanup

A merge request includes standing authorization to clean its merged task branch locally and remotely and remove its task worktrees after required CI passes on the exact merged default-branch commit. A commit or branch-push request alone does not authorize cleanup. Apply this separately in each repository (including separate frontend and backend repos); never infer one repo's merge or CI result from another.

Record the task branch/source SHA, merge result SHA and CI run results. Fetch the default branch and verify the merge result is present there. For squash merges, use confirmed merged PR source/target SHAs or recorded local squash-and-push evidence; ancestry or `git branch --merged` alone is insufficient. Pending, failed, cancelled, skipped or unknown required checks block cleanup. If CI is intentionally absent, follow the repository's explicit validation policy; otherwise retain the task artifacts and report missing evidence.

Clean only the confirmed merged task refs and worktrees, with no new commits since the recorded source SHA. Preserve default/protected branches, the main checkout, dirty/untracked work, valuable ignored files (including environment files), active/locked worktrees and unrelated or unmerged tasks. Release finished task sessions/processes and move cleanup execution to a retained checkout before removal; never remove the worktree still hosting an active agent. Use non-force worktree removal, exact-SHA guarded branch deletion and a remote deletion lease; tolerate already deleted refs. Do not bulk-delete by age or branch-name pattern, force-remove worktrees, reset or discard work. Verify the final local/remote refs and worktree list, and report anything retained with the reason.

## Worktrees

Default: work in place on a feature branch. Use the native `EnterWorktree` tool (never raw `git worktree add`) only when another session or agent may write to the same repo (Herdr panes, claw, parallel write-capable subagents via `isolation: worktree`), or when the tree holds unrelated dirty work. Read-only agents (review, search, triage) never need one.

A worktree is a fresh checkout: `.env` and installed deps are absent. Add a `.worktreeinclude` (gitignore syntax) for gitignored files to copy, run the repo's setup there, and keep `.claude/worktrees/` gitignored. `bd` finds the shared tracker on its own.

## Forgejo

Solo owner. Write actions only when requested. No settings/secrets changes unless stated. Plan before PRs/merges.

## Scope of changes

If, while working or testing, you find a pre-existing bug, a performance concern, or behavior the task doesn't mention, don't fix, optimize or extend it in this change unless the requested behavior cannot work without it; report it as a follow-up in your summary. Commit tests only where the task asks for them or the repo already keeps tests for this kind of change, sized like the neighboring test files; scratch checks need not be kept.

When it will not affect the end result, surgically edit a file rather than rewrite the entire thing.

## Subagents — token economy

- Pick the cheapest model that can do the job: **haiku** for search/scan/triage
  and mechanical lookups; **sonnet** for well-specified implementation (clear
  spec, few files, TDD steps spelled out); default (big) model only for design,
  architecture and cross-cutting debugging. Diff review goes to the
  `code-reviewer` agent, which is pinned to sonnet.
- Dispatch a **fresh** agent per task. Resume a long-lived agent only when its
  accumulated context covers the exact files of the new task — an inherited
  transcript outside that is dead-weight context re-read on every tool call.
- **Carry findings, not transcripts.** Resuming compounds: the agent re-reads a
  transcript that grew in the previous round, so a multi-round review costs far
  more than the rounds suggest. Past the second resume, what matters is the list
  of findings, not how they were reached — put that in a fresh agent's prompt and
  let the old one go. Narrow final checks ("verify these two edits") go to a cheap
  fresh agent regardless of who found the issue.
- Batch only *small mechanical* tasks into one dispatch (a helper plus a schema,
  a doc plus a status flip). Anything with its own tests across several files
  gets its own agent: a long agent re-reads its whole transcript on every tool
  call, so two short agents cost less than one long one.
- Implementers run the *targeted* tests for what they touched, never the full
  suite: it is minutes of output in their context, and pre-push runs it anyway.
  The orchestrator runs the full suite once, on the merged result.
- Batch small shell commands into one call (one `python3`/`git` invocation with
  several steps beats five one-liners). Per-file `git add` still applies.
- Same rules for Workflow `agent()` calls: set `model`/`effort` down for
  mechanical stages, keep the big model for verify/judge stages.

## MCP sources

1. Context7 — docs, APIs, patterns (primary)
2. Perplexity (`perplexity_search`) — security, ecosystem, comparisons (fallback)

Priority: official standards > official docs > community > blogs.

## Beads (bd)

Per-repo issue tracker (`bd`). Data lives in `.beads/`. Run `bd prime` for full workflow. If a repo has no `.beads/`, `bd init` first.

Priority: `-p 0..4`, **0 = highest**. 0=Urgent 1=High 2=Medium 3=Low 4=Trivial.

Descriptions/notes: plain text or markdown (no HTML). Use `bd remember` for persistent knowledge, not MEMORY.md.

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
installed, say so and ask the user to run the login themselves (`! <cmd>`).

**Windows:** rbw does not run there; the vault is reached with `bw` (Bitwarden
CLI, winget-pinned to 2026.6.x to match Vaultwarden — newer releases 404 during
login and leave a vault that will not unlock). Same rules: names only, never
print a value.

- `bw status` reports `unlocked` only when `BW_SESSION` is set in this process.
  Unlocking needs the master password, so if it is locked, ask the user to run
  the command in their own terminal — not via `!`, and never paste `BW_SESSION`
  into chat.
- `bw list items --search <name> | jq -r '.[].name'` to find the item.
- `bw get password '<item>' | <cmd> --password-stdin` for stdin-reading tools.
- MCP keys (`FORGEJO_URL`, `FORGEJO_TOKEN`, `PERPLEXITY_API_KEY`) are user env
  vars that `~/.claude.json` references as `${VAR}`, filled by
  `C:\code\set-claude-secrets.ps1`. After re-running it, restart the terminal
  app, not just Claude Code: new tabs inherit the terminal's stale environment.

## Safety

No fabricated citations/standards. No assumed security posture. No AGENTS.md/CLAUDE.md in READMEs.
