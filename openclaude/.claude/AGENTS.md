# Agent Instructions (Global)

These instructions apply to all projects unless overridden
by a project-specific CLAUDE.md.

---

## Mandatory

As an autonomous agent you will:

1. Call vibe_check after planning and before major actions.
2. Provide the full user request and your current plan.
3. Optionally, record resolved issues with vibe_learn.

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

---

## Output expectations

- Provide a short summary first
- Include actionable recommendations
- Clearly separate facts from opinions
- Avoid inventing APIs, versions, or guarantees
