# Pi Team Pipeline Runbook

`pi-team-run` provides durable local pipeline bookkeeping in SQLite and polls exact-revision Forgejo CI for interactive delivery.

## Rollout plan

1. **This release:** the interactive coordinator drives pre-plan knowledge lookup, local ledger tracking, exact-revision Forgejo polling after publishing, and shared closeout (`honcho`/`wiki` disposition) after verified delivery—this is interactive coordinator policy, not a daemon or `pi-team-run` CLI default. A scoped interactive Honcho publisher (`honcho_publish`) is already available for some mapped repositories with an operator grant; automated wiki publishing remains disabled. Use the same canonical repository key across linked worktrees. The optional journal watcher is separate from polling.
2. **Next:** pilot read-only rollout receipts, additional CI providers, and coordinator restart recovery on explicitly authorized tasks. Evaluate Jev in shadow mode only, on sanitized ambiguous cases; deterministic rules own routing and permissions.
3. **Later:** consider a dedicated isolated runner and explicit cross-host ownership handoff, plus any gated wiki automation only where an explicit allowlist and standing ingest authorization exist, with independently verified receipts rather than retries of delivery.

## Boundaries and Guarantees

- **Interactive continuation**: the coordinator starts `monitor` immediately after publishing and continues authorized work on success. `monitor` queries Forgejo and records a successful PR CI checkpoint when attached to a run. Add `--queue` to the same command to register a durable PR wait on git.butakov.su and return immediately. The enabled systemd user watcher polls that wait independently of Pi and records success against its exact generation and SHA. Neither command merges, deploys, starts or resumes a coordinator, or performs Honcho/wiki publication. Post-merge monitoring remains interactive. Use only sanitized locators and reminders: never include tokens, raw logs, or private transcripts in command arguments, state, or journal notices.
- **Local private XDG state**: State is stored in `${XDG_STATE_HOME:-~/.local/state}/pi-team-run/state.db` (`0700` directory, `0600` database file), with SQLite schema v3. Both v1 and v2 ledgers remain readable without migration (`status`, `discover`, `resume`, `preflight`, and read-only `monitor`) and upgrade atomically on the next successful write. Existing runs keep their original scope and history. Unknown versions are rejected; use matching ledger, dispatcher and watcher versions.
- **Parallel issue runs**: `start LINKED_WORKTREE --issue FULL_ID` reserves that issue and Git worktree for one active or waiting interactive run. Both must differ for a second run in the same repository. The CLI checks the Git identity, not Beads ownership; verify the claim separately. Starts without `--issue`, pre-upgrade runs, and dispatcher reservations remain repository-exclusive. Do not relabel or cancel them to make room.
- **Durable writer fence (v3)**: Team writer launches (`agy_worker` under `--agy-team`, via `pi-team-run writer-exec`) register an `open` row in `writer_attempts` and enforce mutual exclusion with `runs` (including persisted `BEFORE INSERT` triggers). Scoped writers require an exact `active` matching run for `(issue, worktree)`—a `waiting` row is rejected.
  - **Sandbox & host requirements**: Requires Linux `os.pidfd_open` (host pidfd) and trusted system host paths (`/usr/bin/python3 -I -S` for team writer supervision and isolated bootstrap; `/usr/bin/bd` for team claim heartbeats before launch and during delegation; `/usr/bin/flock` for team lock checks and per-worktree locking; `/usr/bin/git` with cleaned Git identity environment for `start`, `writer-exec`, and `preflight` host identity resolution; and `/usr/bin/bwrap` with `--unshare-pid`, `--die-with-parent`, `--ro-bind / /`, `--bind <cwd> <cwd>`, `--dev /dev`, `--proc /proc`, plus paired `--overlay-src`/`--tmp-overlay` for restricted Pi writers). The ledger pathname (`XDG_STATE_HOME`, the `pi-team-run` state directory, and `state.db`) must be a direct, symlink-free lexical path that never traverses symlinks or the writable worktree bind, and an existing `state.db` must be a single-link regular file (`st_nlink == 1`, rejecting hardlink aliases, symlinks, and non-regular files). `writer-exec` rechecks the actual `state.db` inode after registration commit before spawning `bwrap` (leaving the open attempt row intact if late validation fails), verifies the nested namespace init via `--info-fd` and host pidfd before releasing execution, and bypasses closing only on a negative `Popen.wait()` return (actual signal-killed outer launcher); any nonnegative launcher exit (including high exit codes such as `200`) still requires pinned namespace-init pidfd exit verification and closes only the matching `open` attempt row.
  - **Fence boundary**: Only ledger callers (`pi-team-run` / SQLite triggers) and new Team writer launchers sharing the same `XDG_STATE_HOME` state database are fenced. Plain Pi (`--agy-team` disabled), manual edits/CLI runs outside Team, and callers using a different `XDG_STATE_HOME` are excluded.
  - **Cutover & mixed-version policy**: Mixed-version operation is unsupported. Before enabling or upgrading to v3, drain or restart all older writer-capable sessions and positively verify that their in-flight `agy`, `pi.managed`, `bwrap`, and `flock` writer processes are gone.
  - **Uncertain attempts persist**: If a supervisor is interrupted/killed, stopped at a work deadline without a verified exit receipt, fails pidfd exit verification, or encounters a close mismatch, the `writer_attempts` row stays `open` (unjournaled as closed). `agy_worker` never offers `resumeAfterTimeout` on such an interrupted deadline and rejects explicit `resumeAfterTimeout` requests before launch. There is no automatic recovery, takeover, cancellation, or reset/clear command for open writer attempts; only the explicit post-reboot `writer-recovery arm`/`retire` procedure below can close one, and it records the attempt as interrupted rather than successful.
- **No remote state sync or cross-host takeover**: State belongs strictly to the local host and XDG user state directory. There is no automatic authority transfer or distributed lock.
- **External patch handoff** (issue-scoped implement/check/review): once an exhausted repair is independently blocked and no writer fence is open, persist `wait RUN STAGE --target coordinator --rejected-patch DIFF_SHA256 --reason FINDINGS`. A blocked legacy coordinator wait may be explicitly converted with `--replace` after checking the same owner and evidence. No automatic migration guesses from prose. The startup picker and `resume` now distinguish “await external patch” from “verify supplied patch.” The cooperative owner verifies the worktree/base, snapshots all changes including untracked files and records `supply-patch RUN --generation G --candidate NEW_SHA256 --snapshot PRIVATE_FILE --evidence SOURCE`. The CLI hashes that file, not the live checkout. A changed hash queues verification; it is not evidence of a behavioral fix. Each phase has a single durable watcher notice and repeated submissions cannot launch work. No more writers are admitted to this run, even after the handoff. Checks and review must cite the supplied digest; `checkpoint` on the patch wait additionally requires the new generation. If the prior check is for an older digest, review requires a separate fresh checks locator via `--checks-evidence`. No command launches a coordinator, proves independent review, changes an old delivery profile, or deploys.
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

Shared-delivery reservations (`reserve` / `runs.reserved`) are unchanged by the v3 writer fence, and `cancel` or `checkpoint` on a run never clears or closes `open` rows in `writer_attempts`.

## Recovering an interrupted writer attempt after a reboot

Use this procedure only for an `open` `writer_attempts` row left by an interrupted Team writer supervisor. It is a bookkeeping receipt, not a takeover or reset: a schema-v3 attempt shipped by this release needs no earlier boot, PID, or process evidence, because `arm` records the current host boot, machine identity, and PID-namespace observation in an append-only `writer_recovery_events` row. Address the attempt by its exact ID (`wa-` plus 32 lowercase hex characters) and start with the read-only check:

```bash
pi-team-run writer-recovery status wa-<32-lowercase-hex>
```

1. **Arm on the original host**, from the original linked worktree, with the exact issue and the same binding as the `open` row:

   ```bash
   pi-team-run writer-recovery arm wa-<32-lowercase-hex> --cwd /path/to/linked-worktree \
     --issue REPO-123 --run-id PIPELINE_RUN_ID --confirm-local-ledger
   # Unbound attempt: use --unbound instead of --run-id PIPELINE_RUN_ID.
   ```

2. **Reboot the original host separately.** This is a distinct, explicitly authorized operator action; `arm` and `retire` never reboot, restart, or signal any host or process.

3. **Retire after that reboot has completed**, with the same attempt ID, `--cwd`, `--issue`, binding, and attestation, then confirm with `status`:

   ```bash
   pi-team-run writer-recovery retire wa-<32-lowercase-hex> --cwd /path/to/linked-worktree \
     --issue REPO-123 --run-id PIPELINE_RUN_ID --confirm-local-ledger
   ```

`--confirm-local-ledger` is the operator attestation: `original host, same original private local ledger and scope, no sharing, copying, restore, cloned machine-ID, or replay`. Both actions require Linux on `x86_64` or `aarch64` with `openat2(2)` (`RESOLVE_BENEATH | RESOLVE_NO_XDEV | RESOLVE_NO_SYMLINKS`) and independently verify the session's lowercase host boot UUID (read relative to a pinned `/proc` root FD verified against the unique `proc` mount in `mountinfo`), hashed machine identity, initial host PID namespace, the exact linked worktree `.git` gitfile matching the pinned worktree admin directory's `gitdir` backlink (copied sibling `.git` pointers and missing/malformed `gitdir` metadata refuse), and the ledger file as a normalized symlink-free path with private `0700`/`0600` permissions, a single-link inode, a filesystem ID, and a supported persistent local filesystem (`ext4`, `xfs`, `btrfs`, `f2fs`). `--run-id` is matched verbatim against the bound run ID without trimming or length truncation (use `--run-id=VALUE` when punctuation or leading `-` is present). The ledger must be the same existing file and inode in the same repository and worktree scope. There is no ledger copy, restore, clone, alternate path, or proc-shadow fallback: unsupported architectures, mount/symlink crossings under `/proc`, non-private, non-local, network, overlay, or `nsfs`-masked evidence, a changed inode or filesystem, a v1/v2 or unknown ledger version, or any other unsupported or ambiguous input refuses before any write. Keep the verified linked worktree admin directory and issue/run scope unchanged; do not move, re-link, re-create, or re-point them between `arm` and `retire`.

`retire` additionally requires the same machine identity, initial PID namespace, and ledger provenance, and a boot UUID different from the one `arm` observed. A matching boot UUID refuses, so retirement is never a same-boot override and cannot substitute for the separately authorized reboot. On success the row becomes `closed` with `exit_code` NULL and the receipt records the `interrupted` disposition: that marks an interrupted writer, not a successful one, and it is never a success outcome for the attempt.

Neither action advances a run or review stage, completes a wait, or takes, releases, or alters a reservation. Run rows stay untouched, so a run left `waiting` for the same issue/worktree can still block a new writer after retirement. Nothing is reset or cleared automatically, and repeating `arm` or `retire` on an attempt that already has that event refuses.

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
