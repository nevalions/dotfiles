# Global Instructions for Pi

These are the Pi-specific defaults. For detailed user workflows, consult the relevant shared skill in `~/.agents/skills/` and, when needed, the corresponding section of `~/.codex/AGENTS.md`. Its Codex-only subagent, model-routing, hook, and approval instructions are not Pi capabilities. Do not claim delegation, model changes, or approval gates that the runtime does not provide.

## Scope and evidence

Make surgical changes and preserve unrelated work. Verify outcomes with targeted checks; distinguish evidence from assumptions and reassess after repeated failures. For new repository-changing tasks, use a task branch and isolated worktree; read-only work needs neither. Follow repository-specific setup and integration instructions.

## Git and CI

Use the shared `commit-task`, `merge`, and `pr` skills for their matching workflows. Commit-only never authorizes pushing or merging. An unqualified push means validate, squash-merge into the actual default branch, and push the result, unless repository policy says otherwise. Explicit branch-only pushes and PRs keep the task branch. For `kube-lvl47`, use a task worktree and the server-side PR flow through `scripts/ship.sh`; never merge into local master.

Stage explicit files only; use non-interactive Git, a message file for multi-line commits, and no co-author lines. Do not tag, release, or change settings without authorization. Verify required CI for the exact PR head or merged commit as appropriate; do not remove branches or worktrees until the authorized merge and required CI are verified. Missing evidence is not a pass.

## Tasks, memory, and credentials

- **Beads:** Use for durable task state and dependencies; ask before creating or updating an issue unless already authorized.
- **Honcho:** For cross-session context, explicitly query `linroot` for user preferences or the named repository peer (e.g. `kube-lvl47`) for repo context. Recall is not automatically injected. Keep queries targeted and verify remembered claims against current docs, issue state, or live evidence. Pi exposes recall tools only; do not bypass that restriction to record memory.
- **LLM wiki:** For prior research, decisions, or documented procedures, use `wiki-skill` at `/home/linroot/vault/linroot-wiki-code`. Read `AGENTS.md`, `SCHEMA.md`, and `RW/index.md` before opening relevant pages. Lookups are read-only; ingest or edit only when requested. Never write to `RO/`.

Do not store credentials in any memory system.

Keep secrets out of terminal output, transcripts, chat, and tracked files. Prefer existing authenticated access; on this machine use `rbw` when a vault lookup is needed and pass secrets directly to the consuming process. Do not assume Codex MCP approval rules exist in Pi: use tools only within the user's authorized scope.

Prefer official documentation and standards for research. Use the shared `scan-security` skill when reviewing security and do not file findings or make unrelated fixes without authorization.
