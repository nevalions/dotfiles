# Global Instructions for Pi

These are the Pi-specific defaults. For detailed user workflows, consult the relevant shared skill in `~/.agents/skills/` and, when needed, the corresponding section of `~/.codex/AGENTS.md`. Its Codex-only subagent, model-routing, hook, and approval instructions are not Pi capabilities. Do not claim delegation, model changes, or approval gates that the runtime does not provide.

## Scope and evidence

Make surgical changes and preserve unrelated work. Verify outcomes with targeted checks; distinguish evidence from assumptions and reassess after repeated failures. For new repository-changing tasks, use a task branch and isolated worktree; read-only work needs neither. Follow repository-specific setup and integration instructions.

## Git and CI

Use the shared `commit-task`, `merge`, and `pr` skills for their matching workflows. Commit-only never authorizes pushing or merging. An unqualified push means validate, squash-merge into the actual default branch, and push the result, unless repository policy says otherwise. Explicit branch-only pushes and PRs keep the task branch. For `kube-lvl47`, use a task worktree and the server-side PR flow through `scripts/ship.sh`; never merge into local master.

Stage explicit files only; use non-interactive Git, a message file for multi-line commits, and no co-author lines. Do not tag, release, or change settings without authorization. Verify required CI for the exact PR head or merged commit as appropriate; do not remove branches or worktrees until the authorized merge and required CI are verified. Missing evidence is not a pass.

## Tasks, memory, and credentials

- **Beads:** Use for durable task state and dependencies; ask before creating or updating an issue unless already authorized.
- **Honcho recall:** Query `linroot` for user preferences or the named repository peer (e.g. `kube-lvl47`) for repository context. Keep queries targeted and check recalled claims against current docs, issue state, or live evidence. Recall is not automatically injected.
- **Honcho drafts:** Planner and reviewer may return a concise draft in their task handoff, labeled with the task ID, source/candidate, evidence and uncertainty. Drafts are not Honcho memory. Scout, worker, planner and reviewer never publish.
- **Honcho publishing:** Only the top-level operator-authorized CLI session (the coordinator in `pi-team`) may append via `honcho_publish`, and only to the exact workspace, observer peer, target peer, session and task in its launch grant. Use a matching repository peer for verified durable repo facts; use `linroot` only for an explicitly confirmed durable user preference the user authorized saving. Do not publish to other people or unrelated projects. Cite an immutable candidate or primary source, checks and their results, and independent verification (including review when required). A draft, inference, or missing or stale check is not evidence. Read back the exact conclusion before claiming success. No raw transcripts, personal data beyond approved preferences, sensitive evidence, or credentials. Without a grant or when a write is denied, stay read-only; do not bypass the gateway. No deletes, edits of existing memory, provisioning, or administrative operations through Pi.
- **LLM wiki:** For prior research, decisions, or documented procedures, use `wiki-skill` at `/home/linroot/vault/linroot-wiki-code`. Read `AGENTS.md`, `SCHEMA.md`, and `RW/index.md` before opening relevant pages. Lookups are read-only; ingest or edit only when requested. Never write to `RO/`.

Do not store credentials in any memory system.

Keep secrets out of terminal output, transcripts, chat, and tracked files. Prefer existing authenticated access; on this machine use `rbw` when a vault lookup is needed and pass secrets directly to the consuming process. Do not assume Codex MCP approval rules exist in Pi: use tools only within the user's authorized scope.

Prefer official documentation and standards for research. Use the shared `scan-security` skill when reviewing security and do not file findings or make unrelated fixes without authorization.
