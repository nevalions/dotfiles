# Codex skills

The 13 skills from `claude-skills` plus `claude-to-codex`, adapted for Codex and stowed to
`~/.agents/skills`. Install with `python3 codex/install.py` from the repo root,
or `stow codex-skills` for a fresh skills-only installation. Use the installer
to migrate an existing installation made with `--no-folding`; Codex 0.160.0
requires regular skill files under the linked skills root for discovery.

Use `$work`, `$create`, `$commit-task`, `$pr`, `$merge`, `$docs-commit`, `$search`,
`$triage`, `$scan-security`, `$check-agents`, `$shell-history`, `$tools-audit`,
and `$herdr`. Supply the task id or topic in the prompt. Claude's explicit-only
skills keep that policy in `agents/openai.yaml`. Claude-only Fork/Plan/model frontmatter is
removed; each skill now carries a model/effort recommendation and escalation
criteria. Shared task and plugin routes live at `~/.codex/model-policy.md`.
Native profiles and custom agents apply model choices; skill prose does not
switch the parent model. `$claude-to-codex` preserves model intent in future migrations.

Commit, branch push/preparation and merge requests use the configured Luna-low
Git executor, including plain-language requests without `$`. The executor
runs each requested stage directly, with no recursive delegation. Conflicts
or failed checks return to the parent. Install the full Codex package for
this routing; skill-only installation does not configure the executor.

These are reviewed variants, not automatic mirrors. Update both versions when
changing shared workflow behavior. Herdr's instruction body is preserved from
the vendored Claude skill; its upstream pin is in `claude-skills/README.md`.
The Codex tools-audit scanner reads Codex JSONL sessions and prints inventory
and tool counts without conversation content or credentials.
