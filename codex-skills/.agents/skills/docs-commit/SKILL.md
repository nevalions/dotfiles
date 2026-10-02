---
name: docs-commit
description: Check docs for refactoring needs after changes, then commit
---


Update documentation that the current changes make stale, then commit.

- Find docs affected by `git diff HEAD`: README.md, docs/, inline documentation, examples, API references. Update them to match the code.
- Stage explicit files (`git add <file>`, not `-A`) and review with `git diff --cached`.
- Commit with a conventional prefix (feat, fix, refactor, docs, chore — as in the global AGENTS.md).

Use the user’s request and current diff as the change context.
