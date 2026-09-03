# Agent Instructions (Global)

These instructions apply to all projects unless overridden
by a project-specific CLAUDE.md.

---

## vibe_check

Call vibe_check before actions that are hard to reverse or that change the plan the user approved, passing the full user request and the current plan. Record resolved issues with vibe_learn when they would help a later session.

---

## Semgrep usage

- Use Semgrep MCP for security scanning and code pattern detection
- Prefer Semgrep before manual security review
- Do not auto-fix findings unless explicitly instructed
- Create bd (beads) issues for medium/high severity findings

---

## Research commands

Prefer these commands over ad-hoc questions:

- **/search-plan** — Research topic, extract rules, propose safe plan
- **/search-ecosystem** — Current state of a tool/framework (releases, breaking changes)
- **/search-security** — Latest security guidance (standards, deprecations)
- **/search** — General web-backed research
