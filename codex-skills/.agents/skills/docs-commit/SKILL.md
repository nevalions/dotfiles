---
name: docs-commit
description: Use when the user requests updating documentation affected by current changes and committing it.
---

## Authorization

Automatic selection loads this workflow; it does not authorize mutations. Execute only the Git stages, remote writes, release actions, or issue filing covered by the user’s request and applicable repository instructions. Complete authorized read-only preparation before seeking any missing authorization.

## Model selection

Default: `gpt-6-luna / low` (easy). API semantics or substantial restructuring: standard. Apply the task routes and runtime limits in `~/.codex/model-policy.md` when available; skill text does not switch the session model.



Update documentation that the current changes make stale, then commit.

- Find docs affected by `git diff HEAD`: README.md, docs/, inline documentation, examples, API references. Update them to match the code.
- Stage explicit files (`git add <file>`, not `-A`) and review with `git diff --cached`.
- Commit with a conventional prefix (feat, fix, refactor, docs, chore — as in the global AGENTS.md).

Use the user’s request and current diff as the change context.
