# Model selection

Choose the least costly available model and reasoning effort adequate for the actual task before executing a new user task and each delegated task or phase. Respect an explicit user choice. Skill defaults are starting points, not proof of an optimal model or permission to delegate. Reassess when scope or difficulty changes.

## Task routes

| Route / CLI profile | Model | Effort | Use |
| --- | --- | --- | --- |
| easy | gpt-6-luna | low | Exact lookups, inventory, extraction, straightforward mechanical edits and test execution with clear checks |
| standard | gpt-6.1-sol | medium | Implementation, integration, research synthesis, design, planning and ordinary debugging |
| review | gpt-6.1-sol | high | Security interpretation, complex debugging, cross-file review and consequential tradeoffs |
| deep | gpt-6-astra | high | Hardest architecture, unresolved multi-system reasoning, or demonstrated inadequate reasoning from Sol |

These local defaults were checked against official guidance and the local model catalog on 2026-10-02. Luna's documented general starting point is high; low is our narrower choice for mechanical work. Increase its effort if checks show inadequate reasoning, or use Sol when the task needs broader judgment. Avoid max/ultra for routine work. Fix missing data, tool errors and network failures with better evidence or corrected operations before considering a larger model. Escalate after a substantive reasoning failure; return to a cheaper route for later routine steps.

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

Delegated children execute the parent's assigned task directly without recursive delegation unless explicitly designated as coordinators. The automatic trigger applies to the parent receiving a new user task.

For parent waiting, mailbox handling, user updates and stall investigation, follow the [global Subagents waiting rules](AGENTS.md#subagents).

Standing global authorization: before executing any new user task requiring file inspection, tools, edits or external research, the parent selects a route and delegates task execution. This applies across code, research, documentation, debugging, review, operations, data and design, including routine inventory and exact file lookups. A few-command task still delegates; batch related small steps into one cohesive child. Direct responses are limited to conversational, existing-context or status answers that need no new domain work. The parent may make brief scoping/routing checks, then coordinates, communicates, integrates and verifies; scoping must not become direct task completion. Parallelize independent work only with exclusive write ownership and isolation when needed. Run dependent stages and shared-repository writes sequentially. Keep action authorization, permissions and skills' explicit-only invocation metadata intact.

Choose the model and effort for the actual workload, using the tables as starting guidance. Apply supported explicit spawn arguments with fresh or limited history (`fork_turns = "none"` where supported); prose does not switch a model. Use a named role only when the runtime supports it and its configured model/effort match the chosen route. Explorer is suitable for easy read-only search; code-reviewer for review. Otherwise use a general agent with explicit model/effort and read-only research/review instructions or scoped mutation ownership. Pass compact context, paths, exact authorization, constraints and checks; verify returned results. Remember unsupported roles for the session instead of retrying them. If spawning or model overrides are unavailable, report once and continue authorized work without claiming a model switch. Never silently substitute an unavailable user-selected model.

`agents.default_subagent_model = "gpt-6.1-sol"` and `agents.default_subagent_reasoning_effort = "medium"` provide the standard fallback for unclassified spawns. Explicit workload overrides take precedence; neither default changes the parent's model. Duplicated context and orchestration have overhead, so delegation is not a cost-saving guarantee and conversational responses needing no new domain work need no child.

Requested Git workflows retain the persistent `git-workflow` route: Luna low for routine execution, with conflicts or failed checks returned to the parent for Sol medium/high assessment. Use the named role only when available with matching settings; otherwise use a general agent with explicit model/effort and the Git executor instructions. An explicit user model/effort overrides the fixed Luna role. This route also applies to small requested Git tasks. Keep dependent repository writes sequential, prevent recursive delegation, and execute only the authorized Git stages.

For new/unknown workloads, check scope, ambiguity, consequences of error, necessary context, modalities and tools, then choose a route; unknown tasks default to standard. Check current catalog/client support before adding model IDs or reasoning levels. Do not refresh documentation for every routine task; reuse validated settings until availability or behavior changes. Do not silently substitute unavailable models or use Claude model names as Codex IDs.

Sources: [models and effort guidance](https://learn.chatgpt.com/docs/models), [subagent model configuration](https://learn.chatgpt.com/docs/agent-configuration/subagents), and local `codex --help` / `~/.codex/models_cache.json`. Defaults are workload recommendations, not benchmarked cost or quality guarantees.
