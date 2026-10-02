# Model selection

Choose the least costly available model and reasoning effort adequate for the actual task before substantial work or an authorized delegation. Respect an explicit user choice. Skill defaults are starting points, not proof of an optimal model or permission to delegate. Reassess when scope or difficulty changes.

## Task routes

| Route / CLI profile | Model | Effort | Use |
| --- | --- | --- | --- |
| easy | gpt-6-luna | low | Exact lookups, extraction, status, summaries, mechanical edits with clear checks |
| standard | gpt-6.1-sol | medium | Implementation, integration, ordinary debugging, synthesis and planning |
| review | gpt-6.1-sol | high | Security interpretation, complex debugging, cross-file review and consequential tradeoffs |
| deep | gpt-6-astra | high | Hard architecture, unresolved multi-system reasoning, or inadequate results from Sol |

These local defaults were checked against official guidance and the local model catalog on 2026-10-02. Luna's documented general starting point is high; low is our narrower choice for mechanical work. Increase its effort if checks show inadequate reasoning, or use Sol when the task needs broader judgment. Avoid max/ultra for routine work. Missing context or a failed tool needs better evidence or a corrected command, not automatically a larger model. Escalate after a substantive reasoning failure; return to a cheaper route for later routine steps.

## Skill defaults and escalation

| Skill | Default | Escalate when |
| --- | --- | --- |
| check-agents | easy | Conflicting scopes need interpretation: standard |
| shell-history | easy | Reconstructing an incident or causality: standard/review |
| create | easy | Requirements, risk or acceptance criteria need design: standard |
| commit-task | easy | Diff correctness or failing checks need analysis: standard/review |
| docs-commit | easy | API semantics or substantial restructuring: standard |
| pr | easy | Conflict resolution or correctness assessment: standard/review |
| merge | easy | Conflicts or release consequences: standard/review |
| triage | easy | Root-cause or security judgment: standard/review |
| herdr | easy | Complex agent/workspace orchestration: standard |
| tools-audit | standard | Collecting/counting inventory only: easy; security judgment: review |
| search | standard | A factual lookup: easy; security or conflicting evidence: review |
| scan-security | review | Running scanner/counting findings only: easy; hardest threat analysis: deep |
| work | standard | Fully specified mechanical task: easy; complex bugs: review; architecture: deep |
| claude-to-codex | standard | Inventory/unchanged sync only: easy; permission/model semantic conflicts: review |
| frontend-design | standard | Mechanical styling: easy; novel architecture or complex interactions: review/deep |
| brainstorming, writing-plans | standard | Hard architectural tradeoffs: review/deep |
| systematic-debugging, receiving-code-review, requesting-code-review | review | Bounded evidence lookup: easy; unresolved multi-system cause: deep |
| test-driven-development, executing-plans, subagent-driven-development | standard | Mechanical specified step: easy; complex integration: review |
| dispatching-parallel-agents | standard | Choose each authorized child independently by its task |
| using-git-worktrees, finishing-a-development-branch, verification-before-completion | easy | Conflicts, failure interpretation or integration judgment: standard/review |
| using-superpowers | easy | Select the route for the actual next task |
| writing-skills, skill-creator, skill-installer | standard | Simple validation/install: easy; complex behavioral design: review |
| openai-docs | standard | Exact documentation lookup: easy; migration tradeoffs: review |
| imagegen | standard | Simple prompt/edit instructions: easy; complex art direction: review; image generator is separate |
| plugin-management | easy | Permission/dependency or ecosystem judgment: standard/review |
| create-pet, update-pet | standard | Simple metadata: easy; complex animation repair: review |
| pets | easy | Unexpected lifecycle behavior: standard |

## Apply the choice honestly

CLI: start with `codex -p easy`, `codex -p standard`, `codex -p review`, or `codex -p deep`. These are native `<name>.config.toml` profile files for the installed CLI. An existing session uses its model picker (`/model` in the CLI) or another supported runtime control. Skill Markdown and `agents/openai.yaml` do not automatically switch the parent model. If no switching control is exposed, report a useful mismatch once and continue authorized work; do not claim savings or stop repeatedly for a model change.

When delegation is already authorized, use the role's configured model/effort or explicit supported spawn overrides. Model overrides here require a fresh or limited-history child rather than a full-history fork. Pass only the context the child needs and verify results. Avoid starting a child for a trivial operation solely to change models: duplicated context and orchestration can cost more. Configure explorer as easy and code-reviewer as review; override for the actual workload when supported.

Requested Git workflows use the persistent `git-workflow` delegation route: Luna low for routine execution, with conflicts or failed checks returned to the parent for Sol medium/high assessment. This user-configured route also applies to small Git tasks; it is an exception to avoiding delegation solely for model cost. Keep dependent repository writes sequential, prevent recursive delegation, and preserve explicit user model choices and action scope.

For new/unknown workloads, check scope, ambiguity, consequences of error, necessary context, modalities and tools, then choose a route. Check current catalog/client support before adding model IDs or reasoning levels. Do not refresh documentation for every routine task; reuse validated settings until availability or behavior changes. Do not silently substitute unavailable models or use Claude model names as Codex IDs.

Sources: [models and effort guidance](https://learn.chatgpt.com/docs/models), [subagent model configuration](https://learn.chatgpt.com/docs/agent-configuration/subagents), and local `codex --help` / `~/.codex/models_cache.json`. Defaults are workload recommendations, not benchmarked cost or quality guarantees.
