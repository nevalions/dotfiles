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

Reconciler adds prefix (e.g. "ANS-21:") to task titles and preserves all other fields. One-step `task_create` with description and priority works.

Quirks: `tasks_list` needs projectId. `tasks_list_all` unreliable. `task_complete`/`buckets_list` have type bugs — use `task_update(done=true)`. `tasks_bulk_update` may 401 — use individual updates.

## Safety

No fabricated citations/standards. No assumed security posture. No AGENTS.md/CLAUDE.md in READMEs.
