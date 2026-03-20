---
description: "Triage Forgejo branches, pull requests, and issues for this repository"
agent: "plan"
---

Triage the current Forgejo repository using Forgejo MCP tools.

Tasks:
- Collect repository context with forgejo-read_get_repo.
- List feature branches with forgejo-read_list_branches:
  - Branch names
  - Linked Vikunja task (if any)
  - Last commit date and author
  - CI status (pass/fail/pending); if unavailable, mark as unknown
- List open pull requests with forgejo-read_list_pull_requests and note blockers.
- List open issues with forgejo-read_list_issues that appear actionable or blocked.
- Identify stale branches (>14 days old) and cleanup candidates.
- Identify blockers (failing CI, merge conflicts, unclear scope).
- Highlight anything security-related or time-sensitive.

Output a concise summary with recommended next actions.
Do NOT modify Forgejo state.
