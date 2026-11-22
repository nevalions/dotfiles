# Unattended Pi factory implementation plan

**Status: unattended execution is proposed.** The installed `pi-team` is interactive and prompt-driven. The separate [local pipeline ledger](pipeline.md) is the first shipped slice; it records checkpoints and notices but does not dispatch work. This plan grants no standing authorization and does not change plain Pi or PurpleFlow.

## 1. Define admission and repository policy

- Beads is mandatory. Admit only an existing, ready issue in a designated repo, with current dependencies, explicit scope, exclusions, base revision, acceptance criteria, required checks, risk class and data exposure limits.
- Version an allowlist of repositories, low-risk task classes, permitted operations, required checks and the repository's Beads sync procedure. Specify which claim, note, closure and sync actions are preauthorized and by whom. Default to denying integration, deployment and unrelated issue creation until separately authorized.
- Park issues with ambiguous requirements, conflicting ownership, unmet dependencies, or work outside the configured authority. Report parked issues in an exception digest without blocking other eligible work. Provide a kill switch that stops dispatch and revokes active execution before resumption.

## 2. Implement dispatch, recovery, and isolation

- Use a deterministic dispatcher and a shared transactional execution ledger separate from Beads. Key issue ownership by repository plus issue ID and start with one active run per repo. Persist run IDs, stage and attempt records, leases, heartbeats, budgets, artifact references and pending external writes.
- Atomically reserve execution, recheck issue eligibility and claim using a unique Beads actor before running a stage. Record intent before external writes; reconcile against Beads on restart. Never treat sync as the lock. Use lease generations to reject stale workers; terminate or quarantine the old environment before handing off write access. Make transitions and publication retries idempotent.
- Run Pi roles as bounded stage executors, not as the authority that advances the run. Use disposable containers or VMs with only candidate inputs mounted, no host credentials or deployment access, and deny-by-default egress. Give the worker one writable task workspace; review the frozen candidate in a separate read-only environment. Expose provider access via a scoped mechanism without handing host credentials to the stage. Pin tested Pi and extension versions and fail closed on incompatible capabilities.
- Enforce per-stage timeouts, whole-run time and spend limits, and a total attempt cap in the dispatcher. Retain the same-finding two-repair limit as an additional bound. If a prerequisite fails repeatedly or the budget runs out, stop and record a blocked, failed, or quarantined result.

## 3. Enforce validation and authorize delivery separately

- Require structured handoffs scoped to issue ID, run ID, attempt, candidate SHA, artifact references and result. Collect test exit codes and artifacts independently of model summaries. Require independent review for all unattended candidates during the pilot. Scout and planner may be omitted for narrowly scoped tasks when policy permits.
- Freeze each candidate commit before review and deterministic checks. Reject mismatched or stale evidence; rerun affected checks and re-review after changes. A model verdict cannot waive a required check or expand permissions.
- Give only a restricted integration identity access to the authorized delivery path. Apply the repository's branch, PR, CI and integration rules; verify the exact result as required. If delivery is part of the issue's definition of done, don't close on implementation evidence alone.
- Update/close the authorized Beads issue only after the definition of done is verified. Publish via the repo's existing sync procedure, tracking local completion and pending remote publication separately. Verify publication without duplicating writes on retry. `/todos` is ephemeral execution UI; any future Kanban is a view, not another task database.

## 4. Test failures and run one low-risk pilot

- Test denial of unauthorized repositories, paths, network access, credentials, Git operations, and tracker writes. Verify admission fails when the policy or required capabilities are missing.
- Simulate concurrent dispatchers, lease expiry with a stale worker, restarts after claim and after each stage/artifact write, duplicate callbacks, and partial or failed sync. Assert at most one active writer and no duplicate closure or publication.
- Inject unavailable models, hung or failed tests, stale review SHA, missing artifacts, repeated findings and budget exhaustion. Exercise the kill switch. Verify all failures prevent delivery, park or quarantine appropriately, and leave an evidence trail.
- On the pinned pilot configuration, take one existing, explicitly authorized low-risk Beads issue from claim through isolated implementation, independent review, and verified completion and sync. Demonstrate recovery and duplicate-dispatch prevention before enabling further unattended tasks. Measure first-pass acceptance, escaped defects, cost per accepted issue, recovery success and blocked age.

## Deferred

- Honcho stays recall-only. Pass only relevant, provenance-labeled context; live issue and repository evidence take precedence.
- Wiki is a separate authorized flow: verified outcome, sanitized draft, source validation, then permitted wiki update. No raw transcript ingestion.
- Evaluate Jev shadow-mode routing after the pilot. It may recommend more scrutiny, never waive review, authorize a transition, or bypass deterministic checks.
