---
name: pipeline-contract
description: Pragmatic, low-overhead Kanban pipeline for Hermes agents. Focus on working code, real tests, and fast completion.
version: 2.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [kanban, orchestration, evidence, validation]
    related_skills: [hermes-agent, test-driven-development]
---

# Pragmatic Kanban Pipeline (v2)

Use for task admission, implementation, review, and delivery. Keep overhead low and focus on delivering verified outcomes quickly.

## Core Principles (Zero Bureaucracy)

1. **Outcome First — No JSON Receipt Ceremony**
   - Do **not** create `-evidence/` directories full of JSON receipt files (`intake.json`, `admission-intent.json`, `actual-admission.json`, `owner-candidate-binding.json`, `guard-input.json`, `preparation-results.json`, etc.).
   - Do **not** run offline bureaucratic validators (`review_loop_guard.py`, `validate_gate.py`, `fast_track_packet.py`) or compute SHA-256 history chains before admitting or reviewing work.
   - Track task state, test results, and handoffs directly in the Kanban card comments and native lifecycle metadata.

2. **Fast Path for Easy & Bounded Tasks**
   - Do **not** ask the user for authorization on easy, bounded, or non-breaking tasks and improvements.
   - If a task is small and self-contained (e.g., config tweak, docs fix, small script fix, dependency bump preparation), handle it with the minimum path:
     - **Direct or 1-Card Path:** `main-implementer` (implement + run targeted tests) -> `reviewer` (same-card review via `kanban_request_review`).
     - Do **not** spawn extra cards for `planner`, `researcher`, `repo-scout`, `tester`, or `repo-docs` unless the task genuinely requires them.

3. **Constructive Review — Never Block on Nits or Hypotheticals**
   - `reviewer` verifies the **actual code/deliverable and real test execution**.
   - **Never reject or block a card over:**
     - How an evidence packet or comment is formatted,
     - Hypothetical future commands not being executed in the current stage,
     - Style preferences or minor wording nits.
   - If the code is sound and the relevant tests pass, **approve and complete the card** (`kanban_complete(summary=..., metadata={'review_outcome': 'approved'})`), noting any minor caveats as non-blocking notes in the summary.
   - If there is a real bug or failing test in the deliverable, use `kanban_request_changes` with a clear, actionable fix description. Do **not** permanently park a task in `blocked` or `triage` after 2 review rounds if the issue is a straightforward, fixable defect—allow normal iterative correction. Reserve `kanban_block` for genuine external blockers or human policy decisions.

4. **Pragmatic Guard & Error Handling**
   - If a command or payload hits a false-positive string match in a local hook (for example, `rbw-guard.py` triggering because a prose comment mentioned `rbw-env`), simply remove the offending string from the prose or use native file tools (`read_file`, `write_file`, `edit_file`) and continue. Only treat a guard refusal as a hard stop when you were actually attempting a forbidden credential or production mutation.
   - Ordinary technical hiccups (wrong working directory, missing flag, typo in a test command) should be fixed immediately in-place without escalating to the user or creating new cards.

5. **Real Safety & Delivery Boundaries**
   - **Git Worktrees:** Edit code in the assigned task worktree (`--workspace dir:/absolute/path` or task worktree), preserving unrelated work in the main checkout. Run `git-freshness` once before starting new repository work; never `git pull`, `stash`, or `reset` over active uncommitted edits.
   - **External Actions Gate:** Local implementation, local testing, and local commits on a task branch are standing authorized work. Pushing to remote, opening/merging PRs, publishing images, or mutating production clusters (`commiter`, `cluster-operator`) follow the repository's delivery rules (e.g., `scripts/ship.sh` and independent CI verification) and require explicit user request or standing repo authorization.
   - **Cluster Observation:** Always use `cluster-operator` (via the `observer` peer when configured) for live cluster checks, never `ansible-operator`.

## Standard Workflow Stages

1. **Intake & Triage (`orchestrator`)**
   - If the request is a quick question or tiny local fix, handle it directly or with a single specialist.
   - For a coding task: ensure a clean task worktree exists, create/update one Kanban card assigned to `main-implementer` with a concise, clear specification (goal, worktree path, files of interest, and test command to run).
2. **Implementation (`main-implementer`)**
   - Implement the change in the assigned worktree.
   - Run the relevant unit/lint/integration tests and `git diff --check`.
   - Call `kanban_request_review(summary="...", reviewer="reviewer")` on the same card with the diff summary and test output, then stop.
3. **Independent Review (`reviewer`)**
   - Call `kanban_show`, inspect the actual git diff in the worktree, and run the relevant test suite.
   - If tests pass and acceptance criteria are met: call `kanban_complete(summary="...", metadata={"review_outcome": "approved"})`.
   - If a real code defect exists: call `kanban_comment` + `kanban_request_changes(reason="...")`.
   - Only call `kanban_block` if a genuine external dependency or human decision is required.
4. **Delivery (`orchestrator` -> `commiter` / `ci-watcher`)**
   - Once the card is `done` (approved), if the user requested commit/push/PR/deploy, dispatch `commiter` (and `ci-watcher` when required by repo rules). Otherwise, report the verified local completion concisely to the user.
