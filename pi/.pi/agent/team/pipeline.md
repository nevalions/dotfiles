# Pi Team Pipeline Runbook

`pi-team-run` provides durable local pipeline bookkeeping in SQLite and polls exact-revision Forgejo CI for interactive delivery.

## Rollout plan

1. **This release:** the interactive coordinator drives pre-plan knowledge lookup, local ledger tracking, exact-revision Forgejo polling after publishing, and shared closeout (`honcho`/`wiki` disposition) after verified delivery—this is interactive coordinator policy, not a daemon or `pi-team-run` CLI default. A scoped interactive Honcho publisher (`honcho_publish`) is already available for some mapped repositories with an operator grant; automated wiki publishing remains disabled. Use the same canonical repository key across linked worktrees. The optional journal watcher is separate from polling.
2. **Next:** pilot read-only rollout receipts, additional CI providers, and coordinator restart recovery on explicitly authorized tasks. Evaluate Jev in shadow mode only, on sanitized ambiguous cases; deterministic rules own routing and permissions.
3. **Later:** consider a dedicated isolated runner and explicit cross-host ownership handoff, plus any gated wiki automation only where an explicit allowlist and standing ingest authorization exist, with independently verified receipts rather than retries of delivery.

## Boundaries and Guarantees

- **Interactive continuation**: the coordinator starts `monitor` immediately after publishing and continues authorized work on success. `monitor` queries Forgejo and records a successful PR CI checkpoint when attached to a run. Add `--queue` to the same command to register a durable PR wait on git.butakov.su and return immediately. The enabled systemd user watcher polls that wait independently of Pi and records success against its exact generation and SHA. Neither command merges, deploys, starts or resumes a coordinator, or performs Honcho/wiki publication. Post-merge monitoring remains interactive. Use only sanitized locators and reminders: never include tokens, raw logs, or private transcripts in command arguments, state, or journal notices.
- **Local private XDG state**: State is stored in `${XDG_STATE_HOME:-~/.local/state}/pi-team-run/state.db` (`0700` directory, `0600` database file), with SQLite schema v2. A v1 ledger is readable without migration and upgrades atomically on the next successful write. Existing runs keep their original scope and history. Unknown versions are rejected; use matching ledger, dispatcher and watcher versions.
- **Parallel issue runs**: `start LINKED_WORKTREE --issue FULL_ID` reserves that issue and Git worktree for one active or waiting interactive run. Both must differ for a second run in the same repository. The CLI checks the Git identity, not Beads ownership; verify the claim separately. Starts without `--issue`, pre-upgrade runs, and dispatcher reservations remain repository-exclusive. Do not relabel or cancel them to make room.
- **No remote state sync or cross-host takeover**: State belongs strictly to the local host and XDG user state directory. There is no automatic authority transfer or distributed lock.
- **Journal-only best-effort notices**: `pi-team-run watch` deduplicates emitted notices once per `(run_id, wait_generation)` inside SQLite and prints one JSON object per line to stdout (captured by the systemd user journal when enabled). If stdout is dropped or not monitored, notices are not replayed.
- **Explicit authorization & no timeout success**:
  - `resume` is strictly read-only and never authorizes a `user` or `coordinator` wait.
  - `ci` waits remain silent in `watch` before `--deadline`, emit a `coordinator` notice once overdue, and **never** auto-succeed on timeout. Forgejo `monitor --run-id` creates the CI wait and checkpoints success automatically. Other providers retain the explicit `checkpoint RUN ci --rev <exact-full-sha> --evidence <locator>` path.

## Coordinating shared writes

A ledger reservation is local, advisory, and owned by the run. It grants no permission to act. Task-branch edits, local checks, review and PR CI need no shared reservation. For an issue-scoped run:

1. Before a repository-wide operation, run `pi-team-run reserve RUN_ID CURRENT_STAGE`. A busy result names the holder: do not perform the operation; retry when it is free. There is no background queue or automatic takeover. Reserve even at an earlier stage if the repository calls for shared tracker sync there. Do not sync unrelated pending tracker changes.
2. Reserve before integrating, and before publishing if `--no-ci` (a direct-to-main flow may land at publish). **After acquiring**, fetch and compare the actual destination tip and candidate with the reviewed and tested revisions. If the base moved, reconcile against it and rerun affected checks and review; if the head changes, old CI evidence does not apply. Obtain fresh exact-head evidence before landing. Never force a stale push. A reservation cannot lock external Git clients or other hosts.
3. A successful checkpoint releases the reservation, except that landing retains it through verification and any in-scope deploy. Reserve again before Beads closure/sync or an actual Honcho/wiki publication; an optional skip needs no reservation. This guards operations for this repository only, not a shared destination used from another repo.
4. Explicit waits and coordinator exits do not free an acquired reservation. On restart inspect `status RUN_ID`, recheck ownership, approvals and external results, then continue without replaying writes. Repeating `reserve` at the same stage is safe. Cancel only with authority and after confirming no writer or delivery operation remains in flight.

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

Optional stages (`deploy`, `honcho`, `wiki`) are omitted by the CLI unless opted in at `start`; the interactive coordinator automatically selects `--with-honcho`/`--with-wiki` when applicable by policy (honoring opt-outs) to bookkeep closeout disposition. Required stages cannot be skipped mid-run. `start --commit-only` stops delivery after the `commit` checkpoint, rejects `--no-ci` and `--with-deploy`, and may combine with `--with-honcho` and/or `--with-wiki` to append those closeout stages after `commit`. `start --no-ci` omits CI only for a repo with an explicit no-CI policy. None of these flags grant authority. Before `beads_close`, verify everything in scope; incomplete delivery is never marked done to reach closeout. At `honcho` and `wiki`, record verified authorized receipts or `--skip` with a nonsecret typed reason (`skip:not-applicable:...`, `skip:draft:...`/`skip:denied:...`, or `skip:deferred:...`; these prefixes are a coordinator convention and not CLI-enforced).

## Delivery profile pilot: frontend-angular-signals

```bash
pi-team-run delivery-profile nevalions/frontend-angular-signals --json

# Pass the ready PR's exact head and existing ledger run.
pi-team-run monitor nevalions/frontend-angular-signals --profile --pr "$PR" \
  --run-id "$RUN_ID" --rev "$PR_HEAD" --queue

# Check the exact merged tip and the publish-image gate after integration.
pi-team-run monitor nevalions/frontend-angular-signals --profile --rev "$MERGE_SHA"
```

`--profile` replaces hand-entered `--require` contexts. The pilot is keyed by Forgejo host and repository, verifies that the PR targets `master` in that repository, and requires the current `master` tip for post-merge monitoring. If the tip advances, this path stops rather than silently switching revisions. The queued watcher retains the checked context set and target branch; a changed profile requires a new wait. For other repositories, use the existing explicit `--require` flow. If repo policy or server branch protection differs from this profile, reconcile it before using the profile as a gate.

The profile is guidance, not authorization or an executor. With publish and merge authorized, use the application's `scripts/ship.sh` server-side flow and record the actual tested PR head and resulting merge SHA. The script can refresh the candidate; a changed head invalidates earlier CI evidence. Treat default-branch image publication as separate from deployment. A default-branch publish can trigger the existing `stats-dev` GitOps automation, so disclose that side effect before an otherwise ambiguous delivery. Production promotion requires separate authorization and the `kube-lvl47` pin PR flow; do not use direct cluster writes.

For a deployment in scope, use the application's `docs/release-checklist.md`: tie the published digest to the merge SHA, confirm Flux applied the intended GitOps revision, match the serving pods' image IDs in the target environment to that digest, and check the affected public routes. Record these independently before checkpointing deployment. The watcher never merges, changes GitOps, or verifies a rollout by itself.

## Common Commands

```bash
# Start a run (add --with-deploy / --with-honcho / --with-wiki as needed;
# --commit-only may combine with --with-honcho and/or --with-wiki)
pi-team-run start /path/to/linked-task-worktree --issue repo-123
# Without --issue, start retains the exclusive repo-wide behavior.

# Inspect status or read-only next step
pi-team-run status [RUN_ID]
pi-team-run resume RUN_ID

# Checkpoint current stage with an opaque nonsecret locator
pi-team-run checkpoint RUN_ID admit --evidence claim:issue-123

# Record an explicit user or coordinator wait
pi-team-run wait RUN_ID review --target user --reason "approve design change"
pi-team-run wait RUN_ID integrate --target coordinator --reason "ready to land"

# Start Forgejo monitoring immediately after publishing a ready PR.
# Repeat --require for every context required by repository policy.
pi-team-run monitor owner/repo --pr 47 --run-id RUN_ID \
  --rev 0123456789abcdef0123456789abcdef01234567 \
  --require 'CI / test (pull_request)'

# For merged-head monitoring, omit --pr and --run-id and supply push contexts.
# Forgejo authentication uses PI_TEAM_FORGEJO_TOKEN or, on git.butakov.su only,
# ~/.config/forgejo/token. --host selects another HTTPS Forgejo host.

# For other providers, record and complete the CI gate with exact full revision
pi-team-run wait RUN_ID ci --target ci --rev 0123456789abcdef0123456789abcdef01234567 --deadline 2026-11-22T18:00:00Z
pi-team-run checkpoint RUN_ID ci --rev 0123456789abcdef0123456789abcdef01234567 --evidence ci:run-987

# Explicitly skip an opted-in optional stage with a nonsecret typed reason
pi-team-run checkpoint RUN_ID honcho --skip --evidence skip:not-applicable:no-eligible-fact

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

## Opt-in Forgejo delivery pilot

The PR watcher remains read-only against Forgejo. An explicitly started, separate `pi-team-delivery@ID.service` can continue one authorized squash merge and verify post-merge checks without the Pi session. It never edits Beads, deletes a branch, or deploys directly. Only use it for pilot repositories whose merge side effects were individually authorized; do not allowlist production deployment repositories for the pilot.

Configure private (0600) files under `~/.config/pi-team/` (or the service's `XDG_CONFIG_HOME` equivalent): `delivery-pilot-repos` lists approved pilot repositories, one `owner/name` per line; `delivery-token` holds a dedicated, non-admin Forgejo credential restricted to the pilot repository and subject to its branch protection. The normal watcher token is not used. The protected branch must independently enforce required checks at merge time. The runner pins and rechecks the base tip before POST and verifies the actual squash parent afterwards; Forgejo's merge API guards the head, not the base atomically.

Once a specific merge is authorized, create `delivery/ID.json` (0600) in that directory with this schema, filling values from the approved PR and repo policy:

```json
{
  "host": "git.butakov.su",
  "repo": "owner/pilot-repo",
  "pr": 12,
  "head_sha": "<exact ready PR head>",
  "base_sha": "<exact protected base tip>",
  "base_ref": "main",
  "pr_checks": ["<exact required PR context>"],
  "post_merge_checks": ["<exact required push context>"],
  "expires_at": "<UTC timestamp no more than 24h away>"
}
```

```bash
systemctl --user daemon-reload
systemctl --user start --no-block pi-team-delivery@ID.service
journalctl --user -u pi-team-delivery@ID.service
```

The service uses model-free polling and reconciles an already-merged PR instead of merging twice. Restart it with the same unexpired grant to resume after interruption. Do not change an active grant: stop the service and issue a new grant if the PR or base changes. Stop the service or remove the grant to revoke it before the merge request is sent. If evidence drifts, a check fails, or a prior merge response is ambiguous, consult the journal and Forgejo instead of attempting a different candidate under the same grant. This pilot does not automate rollout verification or grant issuance.

## Opt-in Systemd Watch Timer

The `pi` stow package provides user units at `~/.config/systemd/user/pi-team-watch.{service,timer}` running `pi-team-run watch` every 30 seconds. They remain disabled until explicitly enabled:

```bash
systemctl --user daemon-reload
systemctl --user enable --now pi-team-watch.timer
systemctl --user restart pi-team-watch.timer
journalctl --user -u pi-team-watch.service -f
```
