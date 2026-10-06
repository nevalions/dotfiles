# Codex skills

The 13 skills from `claude-skills` plus `claude-to-codex`, adapted for Codex and stowed to
`~/.agents/skills`. Install with `python3 codex/install.py` from the repo root,
or `stow codex-skills` for a fresh skills-only installation. Use the installer
to migrate an existing installation made with `--no-folding`; Codex 0.160.0
requires regular skill files under the linked skills root for discovery.

Use `$work`, `$create`, `$commit-task`, `$pr`, `$merge`, `$docs-commit`, `$search`,
`$triage`, `$scan-security`, `$check-agents`, `$shell-history`, `$tools-audit`,
and `$herdr`, or describe the matching task in plain language. The 14 local
skills also include `$claude-to-codex`. Supply the task
id or topic in the prompt. The ten local workflow skills allow automatic
selection in `agents/openai.yaml` with scoped descriptions. Claude-only Fork/Plan/model frontmatter is
removed; each skill now carries a model/effort recommendation and escalation
criteria. Shared task and plugin routes live at `~/.codex/model-policy.md`.
Native profiles and custom agents apply model choices; skill prose does not
switch the parent model. `$claude-to-codex` preserves model intent in future migrations.

Tasks needing file inspection, tools, edits or external research automatically
delegate by workload across code, research, documentation, debugging, review,
operations, data and design. Short
conversational and status responses may stay direct when they need no new
domain work. Routine inventory and file lookups also delegate; related small
steps use one worker. Workers execute directly; the parent coordinates,
integrates and verifies. Luna low handles routine
mechanical work, Sol medium implementation and synthesis, Sol high complex
review/debugging, and Astra high the hardest reasoning. Unknown tasks
default to Sol medium; explicit user model choices take precedence.
General agents with explicit model/effort settings provide the fallback when
named roles are unavailable or their settings do not match the task.

Commit, branch push/preparation and merge requests retain the Luna-low Git
executor, including plain-language requests without `$`. Conflicts or failed
checks return to the parent; dependent Git stages stay sequential and only
requested actions run. Automatic skill selection and delegation preserve
action authorization and permissions. Install the full Codex package for persistent
routing and agent defaults; skill-only installation supplies recommendations
without configuring those defaults. Context overhead means routing does not
guarantee cost savings.

These are reviewed variants, not automatic mirrors. Update both versions when
changing shared workflow behavior. The Codex Herdr skill allows selection from
task context inside Herdr (`HERDR_ENV=1`); controlling existing panes or agents
owned by the user or other sessions still requires explicit instructions. Its
upstream pin is in `claude-skills/README.md`.
The Codex tools-audit scanner reads Codex JSONL sessions and prints inventory
and tool counts without conversation content or credentials.
