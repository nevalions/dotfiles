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

## Beads (bd)

Per-repo issue tracker (`bd`), replaces Vikunja. Data lives in `.beads/`. Run `bd prime` for full workflow. If a repo has no `.beads/`, `bd init` first.

Priority is INVERTED vs Vikunja: `-p 0..4`, **0 = highest**. 0=Urgent 1=High 2=Medium 3=Low 4=Trivial.

Descriptions/notes: plain text or markdown (no HTML). Use `bd remember` for persistent knowledge, not MEMORY.md.

Core commands: `bd ready` (available work), `bd show <id>`, `bd create "<title>" -p <0-4> -l <labels> -d <desc> --acceptance <ac>`, `bd update <id> --claim` (start), `bd update <id> --append-notes <text>` (progress), `bd close <id>` (done), `bd list --status open --json`.

## Safety

No fabricated citations/standards. No assumed security posture. No AGENTS.md/CLAUDE.md in READMEs.
