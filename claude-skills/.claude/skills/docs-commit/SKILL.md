---
name: docs-commit
description: "Check docs for refactoring needs after changes, then commit"
disable-model-invocation: true
---

Update documentation that the current changes make stale, then commit.

- Find docs affected by `git diff HEAD`: README.md, docs/, inline documentation, examples, API references. Update them to match the code.
- Stage explicit files (`git add <file>`, not `-A`) and review with `git diff --cached`.
- Commit with a conventional prefix (feat, fix, refactor, docs, chore — as in the global CLAUDE.md).

Changes context:
$ARGUMENTS
