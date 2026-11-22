# Pi Team Pipeline Runbook

`pi-team-run` provides manual, durable local pipeline bookkeeping in SQLite for multi-stage team runs.

## Rollout plan

1. **This release:** install the local ledger and opt-in watcher from dotfiles. Prove recovery across fresh CLI processes and a clean-home install with simulated CI. Use the same canonical repository key across its linked worktrees.
2. **Next:** have the interactive coordinator record checkpoints and reconcile read-only CI/rollout results. Pilot on one explicitly authorized task before considering automated external writes. Evaluate Jev in shadow mode only, on sanitized ambiguous cases; deterministic rules own routing and permissions.
3. **Later:** consider a dedicated isolated runner and explicit cross-host ownership handoff. Add authorized Honcho/wiki publishing with independently verified receipts, not as retries of delivery.

## Boundaries and Guarantees

- **Bookkeeping only**: the interactive `pi-team` launcher is unchanged. The coordinator still performs and verifies each authorized action. The ledger checks ordering and the CI revision you supply; it does not authenticate receipts, poll CI, auto-resume, or page anyone. Use only sanitized locators and reminders: never include tokens, raw logs, or private transcripts in command arguments, state, or journal notices.
- **Local private XDG state**: State is stored in `${XDG_STATE_HOME:-~/.local/state}/pi-team-run/state.db` (`0700` directory, `0600` database file), gated by `PRAGMA user_version = 1`. Unknown schema versions are rejected.
- **One active run per repository**: Enforced transactionally via SQLite (`BEGIN IMMEDIATE` + partial unique index on `repo_key` for `active`/`waiting` runs). Terminal runs (`completed`, `cancelled`) free the repository key.
- **No remote state sync or cross-host takeover**: State belongs strictly to the local host and XDG user state directory. There is no automatic authority transfer or distributed lock.
- **Journal-only best-effort notices**: `pi-team-run watch` deduplicates emitted notices once per `(run_id, wait_generation)` inside SQLite and prints one JSON object per line to stdout (captured by the systemd user journal when enabled). If stdout is dropped or not monitored, notices are not replayed.
- **Explicit authorization & no timeout success**:
  - `resume` is strictly read-only and never authorizes a `user` or `coordinator` wait.
  - `ci` waits remain silent in `watch` before `--deadline`, emit a `coordinator` notice once overdue, and **never** auto-succeed on timeout. Completing `ci` always requires an explicit `checkpoint RUN ci --rev <exact-full-sha> --evidence <locator>`.

## Stage Sequence

1. `admit` — Admission and claim
2. `implement` — Implementation
3. `check` — Local checks/tests
4. `review` — Review
5. `commit` — Commit
6. `publish` — Publish branch/PR
7. `ci` — CI gate (requires `wait RUN ci --target ci --rev <40|64-hex> --deadline <iso8601>` before checkpoint)
8. `integrate` — Integrate/merge
9. `verify` — Post-integration verification
10. `deploy` *(optional)* — Deploy + verification (enabled only via immutable `--with-deploy` at `start`, or explicitly skipped with `--skip` once reached)
11. `beads_close` — Close Beads issue
12. `honcho` *(optional)* — Honcho disposition (enabled via `--with-honcho` at `start`, or explicitly `--skip`)
13. `wiki` *(optional)* — Wiki disposition (enabled via `--with-wiki` at `start`, or explicitly `--skip`)

Optional stages (`deploy`, `honcho`, `wiki`) are omitted unless opted in at `start`. Required stages cannot be skipped mid-run. `start --commit-only` stops after the commit checkpoint; `start --no-ci` omits CI only for a repo with an explicit no-CI policy. Neither flag grants authority. Before `beads_close`, verify everything in scope; record a truthful not-applicable or pending disposition rather than claiming an external write you did not perform.

## Common Commands

```bash
# Start a run (add --with-deploy / --with-honcho / --with-wiki as needed)
pi-team-run start /path/to/repo

# Inspect status or read-only next step
pi-team-run status [RUN_ID]
pi-team-run resume RUN_ID

# Checkpoint current stage with an opaque nonsecret locator
pi-team-run checkpoint RUN_ID admit --evidence claim:issue-123

# Record an explicit user or coordinator wait
pi-team-run wait RUN_ID review --target user --reason "approve design change"
pi-team-run wait RUN_ID integrate --target coordinator --reason "ready to land"

# Record and complete the CI gate with exact full revision
pi-team-run wait RUN_ID ci --target ci --rev 0123456789abcdef0123456789abcdef01234567 --deadline 2026-11-22T18:00:00Z
pi-team-run checkpoint RUN_ID ci --rev 0123456789abcdef0123456789abcdef01234567 --evidence ci:run-987

# Explicitly skip an opted-in optional stage
pi-team-run checkpoint RUN_ID honcho --skip --evidence skip:no-memory-update

# Emit deduped JSON notices for pending user/coordinator or overdue CI waits
pi-team-run watch

# Cancel at the current stage (frees repo key)
pi-team-run cancel RUN_ID ci --reason "superseded by new task"
```

## Install and check

On a fresh PC or VPS, check out the same dotfiles revision and use Python 3.10+ and GNU Stow:

```bash
python3 install-agents.py --tools pi --check
python3 install-agents.py --tools pi
~/.pi/agent/bin/pi-team-run status
python3 -B tests/test_pi_team_run.py
```

The ledger works without a model or systemd. Outside systemd, run `~/.pi/agent/bin/pi-team-run watch` from your local scheduler. Ensure scheduled and interactive invocations use the same `XDG_STATE_HOME` if overriding the default. Never sync the live ledger through dotfiles.

## Opt-in Systemd Watch Timer

The `pi` stow package provides user units at `~/.config/systemd/user/pi-team-watch.{service,timer}` running `pi-team-run watch` every 5 minutes. They remain disabled until explicitly enabled:

```bash
systemctl --user daemon-reload
systemctl --user enable --now pi-team-watch.timer
journalctl --user -u pi-team-watch.service -f
```
