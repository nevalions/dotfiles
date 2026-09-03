# Global Instructions

## Git

Author: linroot <nevalions@gmail.com>. No co-authored-by lines.
Prefixes: feat, fix, refactor, docs, chore. Non-interactive only. `git add <file>` not `-A`.
Branches: feature/ bugfix/ hotfix/ refactor/ docs/ → atomic commits → squash merge to master → tag → cleanup.

## Forgejo

Solo owner. Write actions only when requested. No settings/secrets changes unless stated. Plan before PRs/merges.

## Scope of changes

If, while working or testing, you find a pre-existing bug, a performance concern, or behavior the task doesn't mention, don't fix, optimize or extend it in this change unless the requested behavior cannot work without it; report it as a follow-up in your summary. Commit tests only where the task asks for them or the repo already keeps tests for this kind of change, sized like the neighboring test files; scratch checks need not be kept.

When it will not affect the end result, surgically edit a file rather than rewrite the entire thing.

## Subagents — token economy

- Pick the cheapest model that can do the job: **haiku** for search/scan/triage
  and mechanical lookups; **sonnet** for well-specified implementation (clear
  spec, few files, TDD steps spelled out); default (big) model only for design,
  architecture, cross-cutting debugging, and reviews.
- Dispatch a **fresh** agent per task. Resume a long-lived agent only when its
  accumulated context covers the exact files of the new task — an inherited
  transcript outside that is dead-weight context re-read on every tool call.
- Batch small shell commands into one call (one `python3`/`git` invocation with
  several steps beats five one-liners). Per-file `git add` still applies.
- Same rules for Workflow `agent()` calls: set `model`/`effort` down for
  mechanical stages, keep the big model for verify/judge stages.

## MCP sources

1. Context7 — docs, APIs, patterns (primary)
2. Perplexity (`perplexity_search`) — security, ecosystem, comparisons (fallback)

Priority: official standards > official docs > community > blogs.

## Beads (bd)

Per-repo issue tracker (`bd`). Data lives in `.beads/`. Run `bd prime` for full workflow. If a repo has no `.beads/`, `bd init` first.

Priority: `-p 0..4`, **0 = highest**. 0=Urgent 1=High 2=Medium 3=Low 4=Trivial.

Descriptions/notes: plain text or markdown (no HTML). Use `bd remember` for persistent knowledge, not MEMORY.md.

Core commands: `bd ready` (available work), `bd show <id>`, `bd create "<title>" -p <0-4> -l <labels> -d <desc> --acceptance <ac>`, `bd update <id> --claim` (start), `bd update <id> --append-notes <text>` (progress), `bd close <id>` (done), `bd list --status open --json`.

## Safety

No fabricated citations/standards. No assumed security posture. No AGENTS.md/CLAUDE.md in READMEs.
