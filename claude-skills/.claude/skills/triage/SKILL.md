---
name: triage
description: "Triage Forgejo branches, pull requests, and issues for this repository"
disable-model-invocation: true
context: fork
agent: Plan
---

Triage the current Forgejo repository with the read-only Forgejo MCP tools (repository, branches, pull requests, issues).

Report:
- Feature branches: name, linked bd (beads) issue if any, last commit date and author, CI status (pass/fail/pending; unknown if unavailable).
- Open pull requests and their blockers.
- Open issues that look actionable or blocked.
- Stale branches (older than 14 days) and cleanup candidates.
- Blockers: failing CI, merge conflicts, unclear scope.
- Anything security-related or time-sensitive.

End with a concise summary and recommended next actions. Read-only: do not change Forgejo state — the user acts on the recommendations.
