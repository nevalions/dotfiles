# Global Instructions

## Git

- All commits must be by linroot with email nevalions@gmail.com
- Do not add co-authored-by lines to commits
- Use conventional commit prefixes: feat, fix, refactor, docs, chore
- Use non-interactive git commands only (no -i, no -v, no interactive rebase)
- Prefer `git add <file>` over `git add -A`

## Git workflow (solo owner)

Branch prefixes: feature/, bugfix/, hotfix/, refactor/, docs/

Workflow: feature branch → frequent atomic commits → squash merge to master → tag → cleanup

## Forgejo (solo owner)

- Assume user is the repository owner
- Write actions allowed when explicitly requested
- Do not modify repository settings or secrets unless explicitly stated
- Prefer planning before execution for PRs and merges

## MCP source prioritization

1. **Context7** — primary source for official framework/library docs, APIs, idiomatic patterns
2. **Perplexity** — web-backed research: security standards, ecosystem updates, comparisons. Use `perplexity_search` (not research)
3. If Context7 is insufficient, explicitly fall back to Perplexity

Source priority: official standards > official docs > community guidance > blogs

## Vikunja

- Descriptions use **HTML** (`<h2>`, `<ul>`, `<pre>`, `<code>`), not markdown
- Comments use **plain text**
- A webhook fires on `task_create` that adds identifier prefix (e.g. "ANS-21:") and **wipes description and priority**
- Always use a two-step pattern with delay:
  1. `task_create` (title, projectId, priority only — description will be wiped by webhook)
  2. Wait for webhook to settle (create all tasks first, then update)
  3. `task_update` (set description and priority — updates after webhook persist)
- `task_update` supports partial updates — only include fields you want to change

## Safety

- Never fabricate citations, standards, or release notes
- Never assume security posture without verification
- When unsure, say so and propose a validation step
- Do not add AGENTS.md or CLAUDE.md to README.md
