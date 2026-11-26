# Bay-Claw Unattended Dispatcher Runbook

`pi-team-dispatch` is a bounded, offline, model-free v1 dispatcher that advances at most one explicitly authorized Beads issue per tick through claim, plan, isolated worker execution, exact-candidate checks, and independent structured review, stopping locally at `candidate_ready`, `blocked`, `cancelled`, `quarantined`, or `no_work`.

## Local-Only Provenance and Boundaries

- **Strictly local**: Produces verified local candidate commits inside private dispatcher Git state (`${XDG_STATE_HOME:-~/.local/state}/pi-team-dispatch/git-store/`).
- **Never mutates delivery or remote state**: Never closes Beads issues, syncs tracker state, pushes branches, opens/merges PRs, deploys, publishes Honcho/wiki entries, or enables/starts systemd units.
- **Default-deny live executors**: Only `"executor": {"mode": "fake", ...}` is accepted in v1. Live LLM/Pi/AGY executors and unknown executor modes fail closed.
- **Shared reservation**: Uses the same XDG pipeline ledger (`${XDG_STATE_HOME:-~/.local/state}/pi-team-run/state.db`, `runs` partial unique index on canonical `git-common-dir`). Interactive `pi-team-run` mutations (`wait`, `checkpoint`, `cancel`, `monitor --run-id`) are refused on dispatcher-owned runs, and `pi-team-dispatch` refuses to touch repos reserved by active interactive runs.

## Prerequisites

1. Python 3.10+ with Linux `os.pidfd_open` and `signal.pidfd_send_signal`.
2. `/usr/bin/bwrap` (0.13.1+) supporting `--unshare-user --unshare-pid --unshare-net --unshare-ipc --unshare-uts --unshare-cgroup --disable-userns --die-with-parent --new-session --clearenv --info-fd --seccomp` on little-endian `x86_64` or `aarch64`. The seccomp cBPF filter (denying `x32` ABI on `x86_64`, `io_uring_*`, and socket entrypoints) is **mandatory**; unsupported architectures or failed seccomp probes fail closed.
3. Git and `bd` 1.3.1+ with an existing local embedded Dolt tracker at canonical `<repo_root>/.beads` and `<repo_root>/.beads/embeddeddolt` (non-symlink directories verified against `bd --readonly --sandbox where --json` by device/inode and path). All `BEADS_*` / `BD_*` environment overrides, `.beads/redirect`, global/redirected routing, remote/sync config (`sync-branch`, `remote`, `sync_remote`, `auto_push`), `no_db`, custom `dolt_data_dir`/`database_path`/`db_path`, and Dolt server modes (`dolt_server_host`, `dolt_server_port`, non-`embedded` `dolt_mode`/`backend`) fail closed.
4. Owner-private (`0600` or `0400`, regular non-symlink file) version 1 policy JSON located **outside** all repository checkouts, `.git`/`.beads`, and XDG state directories, e.g. `~/.config/pi-team/dispatch-policy.json`.

## Standing Policy Contract (v1)

- `version`: `1`
- `repo`: absolute path to an existing non-bare local Git repository
- `risk_class`: `"low"`
- `base_sha` (and optional `base_ref`): pinned full 40/64-hex commit SHA
- `allowed_paths`: non-empty list of at most **4** unique exact repo-relative non-symlink regular file paths existing in `base_sha` (`100644` or `100755`, no globs, `..`, `.git`, `.beads`)
- `allowed_ops`: `["replace"]` only — exact in-place content replacement (write/truncate on prebound regular files without mode changes); `create`, `delete`, rename, hardlinks/symlinks, and permission changes are unsupported and fail closed
- `checks`: list of `{"name", "argv", "timeout_sec"}` run on fresh read-only candidate trees
- `timeouts`: `plan_sec`, `worker_sec`, `review_sec`, `run_sec` (each finite and `<= 3600` seconds)
- `budget`: `max_attempts` (`1`–`20`), `max_spend_usd` (`>= 0.0`)
- `tracker`: `{"type": "beads", "actor", "issue_allowlist", "required_labels", "require_acceptance_criteria"}`
- `executor`: `{"mode": "fake", "stages": ...}`

Pin the exact policy digest on every invocation with `--policy-sha256 <sha256>`.

### Fixed Sandbox and Workspace Bounds (v1)

- **Worker writes**: Prebound in-place writable files only inside a read-only `/workspace` and `--remount-ro /`, capped at `1 MiB` (`1,048,576` bytes) per file (via `RLIMIT_FSIZE`, seccomp `fallocate` denial, and importer check) and `4 MiB` (`4,194,304` bytes) total changed bytes across at most `4` unique files.
- **Tmpfs and output**: `/tmp` and `/scratch` are bounded to `8 MiB` (`8,388,608` bytes) tmpfs each; per-stage captured stdout/stderr is capped at `256 KiB` (`262,144` bytes).
- **Materialization and importer**: `4 MiB` per materialized file, `32 MiB` (`33,554,432` bytes) total materialized bytes, `4,096` max tree/workspace entries, and `32` max directory depth.

## Operations

### 1. Dry-run (Read-Only Selector)

Checks for active/quarantined runs and persistent repo stop markers first, runs the read-only capped ready query (`bd --readonly --sandbox ready --limit 0 --max-rows 10000 --brief --json`, failing closed if `>= 10000` rows are returned) and intersects `tracker.issue_allowlist` locally outside SQLite write locks, selects at most one eligible issue deterministically by `(priority, id)`, evaluates parking/dedupe rules, and emits a bounded nonsecret report without creating state files, claiming issues, or launching sandboxes. When a persistent repo stop marker is active (and no existing dispatch run is pending recovery), `dry-run` returns `outcome: "cancelled"` with `reason: "repo_stop_marker_active"` before reporting any new issue selection:

```bash
~/.pi/agent/bin/pi-team-dispatch dry-run \
  --policy ~/.config/pi-team/dispatch-policy.json \
  --policy-sha256 <64-hex-sha256> \
  --json
```

### 2. Tick (Single-Issue Run or Recovery)

Recovers any active dispatcher run for the repository first; otherwise selects with the same read-only capped ready query outside SQLite write locks, reserves the repo, rechecks readiness with the same capped `bd --readonly --sandbox ready --limit 0 --max-rows 10000 --brief --json` lookup under `.bd.lock` (outside SQLite write locks), claims the selected issue atomically inside `bwrap` bound to kernel-held `.beads` and `.beads/embeddeddolt` directory handles (`--bind-fd`, `--sync-fd` on `.bd.lock`, and a pre-GO verified namespace-init PID1 gate) running `bd --sandbox --actor <unique_actor> update <id> --claim`, revalidates ownership, and executes isolated stages inside `bwrap`:

```bash
~/.pi/agent/bin/pi-team-dispatch tick \
  --policy ~/.config/pi-team/dispatch-policy.json \
  --policy-sha256 <64-hex-sha256> \
  --json
```

### 3. Stop / Revoke

`stop` and `revoke` share the same revocation path. Passing `--policy` or `--repo` writes an independent persistent repo stop marker (`${XDG_STATE_HOME:-~/.local/state}/pi-team-dispatch/stops/repo-<hash>.stop`) that blocks subsequent `tick` runs and `dry-run` issue selection until the operator inspects and removes it. When an active run matches (`--run-id`, `--policy`, or `--repo`), it writes a per-run stop marker (`stops/<run_id>.stop`) and sets `dispatch_runs.stop_requested = 1` in SQLite, acquires `.tick.lock` (if held by an in-flight `tick`, returns `stop_requested` so the active `tick` observes the stop marker/flag, kills its sandbox PID1, and cancels) and `.bd.lock`, reconciles any interrupted claim read-only, kills only the verified namespace PID1 via `pidfd` (destroying all detached descendants without PID-reuse risk), awaits exit proof, and transitions the run to `cancelled` (or `quarantined` if exit cannot be proven or `.bd.lock`/claim reconciliation fails; an already-quarantined run with unknown claim state remains `quarantined` with its reservation intact on repeated `stop`/`revoke`):

```bash
~/.pi/agent/bin/pi-team-dispatch stop --run-id <RUN_ID> --reason "operator halt" --json
~/.pi/agent/bin/pi-team-dispatch revoke --policy ~/.config/pi-team/dispatch-policy.json --json
```

### 4. Reconcile After Crash

Re-running `tick` against a repository with an interrupted `dispatch_runs` row recovers that run before considering new issues:

- **Lost claim acknowledgement (`claiming`)**: Acquires the inherited host `bd` flock, queries `bd show` read-only, and reconciles exact actor ownership without duplicating claims or replaying notes.
- **In-flight sandbox processes**: Checks `boot_id`, `/proc/<pid1>/stat` starttime, and `/proc/<pid1>/ns/pid` before touching any PID. If identity matches, kills verified PID1 and awaits exit; if PID reuse is detected, does not kill the unrelated process; if launch identity is missing (`launching`), quarantines immediately.

### 5. Quarantine and Operator Handoff

- **Quarantine and `claim_retained: "unknown"`**: `claim_retained` is tri-state (`true`, `false`, or `"unknown"`). When exit verification fails, launch identity is ambiguous (`launching`), `.bd.lock` or claim reconciliation fails during recovery or `stop`, tracker identity drifts/becomes unavailable during `claiming` or authority revalidation, or policy digest drifts while `claiming` and ownership cannot be proven, the dispatcher reports `claim_retained: "unknown"` (including on `quarantined` outcomes or `blocked` `tracker_revalidation_failed`). On `quarantined`, `dispatch_runs` transitions to `quarantined` while `runs.status` remains `active`, holding the repository reservation so neither interactive `pi-team-run` nor unattended `tick` can launch another writer. Inspect `pi-team-dispatch status --run-id <RUN_ID> --json`, confirm no sandbox or descendant processes remain, check actual Beads claim ownership with `bd --readonly --sandbox show <ISSUE_ID> --json` and private Git store state, and resolve manually before clearing—**never make blind ledger edits to `state.db`** to clear a quarantine or reservation.
- **Candidate-ready handoff**: On `candidate_ready`, the verified claim (`in_progress` + `assignee = actor`) is intentionally retained in Beads for operator handoff (`claim_retained: true`). Inspect the private candidate commit (`candidate_sha` / `candidate_ref`) in the dispatcher's private Git store, review check/review receipts, integrate manually, and close/sync Beads separately.
- **Blocked / cancelled handoff**: On `blocked` or `cancelled`, `runs.status` transitions to `cancelled` (releasing the repository reservation, though a persistent repo stop marker still blocks new `tick` and `dry-run` issue selection until cleared). If failure or stop occurred before acquiring a claim (`claim_retained: false`), the Beads issue remains `open` and unassigned; once claimed (`claim_retained: true`), the verified Beads claim (`in_progress` + `assignee = actor`) is intentionally **retained** rather than auto-released or closed; if claim status could not be verified (`claim_retained: "unknown"`), inspect `bd show` manually before acting. Inspect `report.reason` and follow `report.next_action` (reviewing any partial `candidate_sha`, check/review summaries, or policy/tracker drift) before manually unclaiming, retrying, or removing a stop marker.

## Opt-In Inert Systemd User Units

Stowing `pi` installs `~/.config/systemd/user/pi-team-dispatch.service` and `pi-team-dispatch.timer` **opt-in, disabled, unstarted, and never active by default**. **Never enable or start these units** while live pilot blockers remain or without an explicit operator policy:

```bash
# Inspect status only (do not enable for live unattended work while blockers remain)
systemctl --user status pi-team-dispatch.timer
```

## Remaining Live Pilot Blockers

1. **No live executor support**: Live LLM/Pi/AGY stage execution is intentionally denied in v1 (`mode != "fake"` fails closed).
2. **No secretless credential proxy**: Isolated sandboxes have `--unshare-net` and no host credentials/config; a scoped provider proxy is required before any live model calls.
3. **No automated integration/delivery**: Candidate commits remain in private dispatcher Git state; branch/PR publication, merge, deployment, and Beads closure/sync require explicit operator handoff or separately authorized delivery flows.
4. **Deferred integrations**: Jev shadow-mode routing and Honcho/wiki closeout remain out of scope for unattended dispatch.
