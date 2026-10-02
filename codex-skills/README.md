# Codex skills

The 13 skills from `claude-skills`, adapted for Codex and stowed to
`~/.agents/skills`. Install with `python3 codex/install.py` from the repo root,
or `stow --no-folding codex-skills` for skills alone.

Use `$work`, `$create`, `$commit-task`, `$pr`, `$merge`, `$docs-commit`, `$search`,
`$triage`, `$scan-security`, `$check-agents`, `$shell-history`, `$tools-audit`,
and `$herdr`. Supply the task id or topic in the prompt. Claude's explicit-only
skills keep that policy in `agents/openai.yaml`. Fork/Plan/model frontmatter is
removed; Codex's session controls and native agents govern execution.

These are reviewed variants, not automatic mirrors. Update both versions when
changing shared workflow behavior. Herdr's instruction body is preserved from
the vendored Claude skill; its upstream pin is in `claude-skills/README.md`.
The Codex tools-audit scanner reads Codex JSONL sessions and prints inventory
and tool counts without conversation content or credentials.
