# Global Instructions

## Git

Author: linroot <nevalions@gmail.com>. No co-authored-by lines.
Prefixes: feat, fix, refactor, docs, chore. Non-interactive only. `git add <file>` not `-A`.
Branches: feature/ bugfix/ hotfix/ refactor/ docs/ → atomic commits → squash merge to master → tag → cleanup.

## Forgejo

Solo owner. Write actions only when requested. No settings/secrets changes unless stated. Plan before PRs/merges.

## MCP sources

1. Context7 — docs, APIs, patterns (primary)
2. Perplexity (`perplexity_search`) — security, ecosystem, comparisons (fallback)

Priority: official standards > official docs > community > blogs.

## Vikunja

Descriptions: HTML. Comments: plain text. Priority: 0=None 1=Low 2=Medium 3=High 4+=Urgent.

Webhook on `task_create` adds prefix (e.g. "ANS-21:") and **wipes description+priority**. Two-step pattern:
1. `task_create` (title, projectId only)
2. After all creates settle: `task_update` (description, priority)

Quirks: `tasks_list` needs projectId. `tasks_list_all` unreliable. `task_complete`/`buckets_list` have type bugs — use `task_update(done=true)`. `tasks_bulk_update` may 401 — use individual updates.

## Safety

No fabricated citations/standards. No assumed security posture. No AGENTS.md/CLAUDE.md in READMEs.
