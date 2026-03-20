---
description: "Check docs for refactoring needs after changes, then commit"
---

Check documentation and commit changes:

1) Analyze code changes:
   - Review git diff to understand what was modified

2) Check documentation for refactoring needs:
   - Identify any README.md, docs/, or inline documentation affected
   - Determine if documentation needs updates or refactoring to match changes
   - If docs need refactoring:
     - Refactor/update documentation to match the code changes
     - Ensure examples, API docs, and guides remain accurate

3) Prepare commit:
   - git add
   - Review staged changes with git diff --cached

4) Create commit:
   - Draft a concise commit message following conventional commits:
     - feat: new feature
     - fix: bug fix
     - refactor: code cleanup
     - docs: documentation changes
   - git commit -m "<commit message>"

Changes context:
$ARGUMENTS
