# Agent Instructions (Global)

These instructions apply to all projects unless overridden
by a project-specific CLAUDE.md.

---

## Semgrep usage

- Use the `semgrep` CLI (or the repo's own scan script / make target) for security scanning and code pattern detection
- Prefer Semgrep before manual security review
- Do not auto-fix findings unless explicitly instructed
- Create bd (beads) issues for medium/high severity findings

---

## Research

Prefer `/search [plan|ecosystem|security] <topic>` (Perplexity-backed, fixed output shape) over ad-hoc web questions.
