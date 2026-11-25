# Honcho publishing from Pi CLI

Interactive `pi` and `pi-team` in mapped Git repositories under `~/code/` and in `~/ansible` (including their linked worktrees) attach a session-scoped publisher on startup or same-directory resume. Check `/mcp` for `honcho_publish`. Only the repository peer is eligible; project and code-wide recall targets are not write targets. The peer must already exist. Workers, `~/dotfiles`, and unmapped checkouts do not get this registration. The local broker reads the existing `Honcho Codex` vault item with `rbw`; no credential is stored in dotfiles. This is tool separation, not isolation from other processes running as the same Unix user with vault access.

The wrapper chains to `~/.pi/agent/bin/pi.managed`. On a fresh managed Pi installation, preserve the original regular executable `~/.pi/agent/bin/pi` at that sibling path **before** stowing `pi` with `--no-folding`. Do not replace an existing `pi.managed` or move the wrapper into that slot. Recall configuration and credentials remain machine-local.

**Do not add this server or extension to shared config or the discovered `extensions/` directory.** For a separate explicit grant, launch with:

```sh
~/.pi/agent/bin/pi-honcho pi /absolute/path/to/grant.json
~/.pi/agent/bin/pi-honcho pi-team /absolute/path/to/grant.json
```

The wrapper loads a session-only extension. The bundled team extension launches a fresh CLI process without the parent's `--extension` argument. Planner/reviewer return task-scoped drafts in their handoffs, not in Honcho.

An operator must first provision the workspace, observer and target peers, and a session dedicated to the task, outside Pi. Confirm the target is the approved repository peer, or `linroot` for a specifically authorized preference. Issue a dedicated workspace-scoped token with the least upstream privileges available. There is no default grant and no use of the shared recall credential. Save the raw bearer token and this grant as owner-only regular files (mode 0600, outside the repository):

```json
{
  "url": "https://honcho.example/mcp",
  "token_file": "/absolute/private/pi-honcho-token",
  "scope": {
    "workspace_id": "example-workspace",
    "peer_id": "pi-coordinator",
    "target_peer_id": "example-repo",
    "session_id": "example-repo-123",
    "task": "example-repo-123"
  }
}
```

Use the scoped endpoint. HTTPS and numeric loopback HTTP are accepted by default. For this installation's Honcho endpoint only, set `"url": "http://100.64.0.16:18080/mcp"` and add `"allow_tailnet_http": true` to the grant. This requires Linux `ip` at `/usr/bin/ip` and an active route through `tailscale0` at startup and before each upstream request. No other remote HTTP URL is accepted. The route check is not a substitute for tailnet ACLs or Honcho permissions. The MCP server authorizes every request against the exact launch grant and reconstructs the upstream arguments from it. Only grant inspection, scoped readback and one-conclusion append per call are offered. Evidence fields are mandatory, but the server cannot establish that the evidence is true. The coordinator checks it against primary sources, checks and review before publishing. On ambiguity or timeout, read back before retrying to avoid duplicates.

The stdio server trusts its launching Unix account and is not an OS sandbox. It prevents alternate scopes, raw upstream methods, or forged roles **through this MCP connection**. A process running as the same user with shell or file access is not isolated from the grant/token. Do not use this to segregate mutually untrusted agents; use a separately administered remote gateway with distinct credentials for that deployment.

## Identity-bound Pi aliases

`recall-scopes.py` maps four fixed checkout paths (including their linked worktrees) only when the repository's local `<git-common-dir>/config` defines a single matching `remote.origin.url` (read with `git config --no-includes --get-all`, ignoring global includes and `insteadOf` rewrites):

- `~/code/purpleflow` -> `hermes-flow` (`git.butakov.su/nevalions/hermes-flow`)
- `~/code/portals/videooperator.su` -> `videooperator-su` (`git.butakov.su/nevalions/videooperator.su`)
- `~/code/portals/ochistka-musoroprovoda.ru` -> `ochistka-musoroprovoda-ru` (`git.butakov.su/nevalions/ochistka-musoroprovoda.ru`)
- `~/code/portals/portal-contact` -> `portal-contact` (`git.butakov.su/nevalions/portal-contact`)

Accepted URL forms are Forgejo SSH on port `2222` (`ssh://git@git.butakov.su:2222/...` or `ssh://git.butakov.su:2222/...`), SCP (`git@git.butakov.su:...` or `git.butakov.su:...`), or credential-free HTTPS (`https://git.butakov.su/...`), with an optional `.git` suffix and no user credentials, query, or fragment. Missing, mismatched, or multiple `remote.origin.url` entries fail closed (`[]`). Legacy aliases and other repository routes are unchanged.

## Batch publishing (`--batch`)

For explicit multi-repository batch publishing without registering a model tool or MCP endpoint, launch an interactive TUI session with:

```sh
~/.pi/agent/bin/pi-honcho pi --batch /absolute/private/manifest.json
~/.pi/agent/bin/pi-honcho pi-team --batch /absolute/private/manifest.json
```

Batch launch rules and isolation:

- Requires an interactive TTY on both stdin and stdout, accepts no extra Pi CLI switches (start a fresh session to pick up a manifest; `--continue`/`--resume` are rejected), refuses to run when `PI_OFFLINE` is present in the environment (even if empty, enforced by `pi-honcho` for both `pi` and `pi-team` in both single-grant and `--batch` modes as well as in the `/honcho-batch` handler), and refuses `--batch` when `PI_HONCHO_NESTED`, `PI_HONCHO_PUBLISH_GRANT`, or `PI_HONCHO_BATCH_MANIFEST` is present (even if empty).
- `pi-honcho` sets `PI_HONCHO_BATCH_MANIFEST` only as a private-path selector and passes `--extension ~/.pi/agent/honcho-cli/batch-command.ts`. Explicit `--extension` suppresses automatic publisher registration; never install `batch-command.ts` in the auto-discovered `extensions/` directory, and never register a model tool or MCP endpoint for batch publishing.
- `batch-command.ts` resolves `batch.py` strictly as its `file://` sibling (`~/.pi/agent/honcho-cli/batch.py`, with no `cwd` fallback) and pins the startup session ID and working directory once per launcher Node process on `session_start` (`reason === "startup"`). Extension reloads in that original startup session retain the pin; `/new`, `/resume`, `/fork`, replacement `startup` events, or reloads in any other session cannot rebind or apply.
- The spawned Pi wrapper marks the Pi process and child processes with `PI_HONCHO_NESTED`, and team/worker children do not inherit parent `--extension` arguments and cannot start a second batch through `pi-honcho`.
- Same OS user trust assumption: `pi-honcho`, `batch-command.ts`, and `batch.py` trust the launching Unix account and are not an OS sandbox against other processes running as the same UID. Grant files and bearer tokens never enter JS, environment variables, process arguments, or chat transcripts. The private full preview (including formatted notes) enters `batch-command.ts` (JS) solely for interactive TUI editor display and unchanged-text verification, and never enters environment variables, process arguments, or chat transcripts.

### Manifest schema and pre-provisioned grants

There is no automatic provisioning. Before launching, the operator must pre-provision:

- The `"hermes-personal"` workspace and `"pi-coordinator"` observer peer.
- Each approved repository target peer (never `linroot`, `pi-coordinator`, `code-wide`, `preferences`, `project-*`, or wildcard targets).
- A **distinct, exclusive, dedicated session** (`session_id`) and separate owner-only grant file for each repository item in the batch.
- When preparing batch surveys of already-verified repositories, omit `build-host` and `media-api` from the manifest rather than adding hardcoded deny rules in code.

Save the manifest, each per-repo grant file, and each raw bearer token as owner-only regular files (`chmod 0600`, non-symlink, outside any repository).

Manifest schema (`1` to `32` items, max `256 KiB`, unique JSON keys; each item must bind a distinct `checkout`, distinct `grant`, distinct repository route, and distinct upstream `(workspace_id, session_id)` — even when target peers differ):

```json
{
  "items": [
    {
      "checkout": "/home/user/code/example-repo",
      "grant": "/home/user/.private/example-repo-grant.json",
      "scope": {
        "workspace_id": "hermes-personal",
        "peer_id": "pi-coordinator",
        "target_peer_id": "example-repo",
        "session_id": "example-repo-batch-1",
        "task": "example-repo-batch-1"
      },
      "candidate": "abc1234",
      "checks": "unit tests ok",
      "verification": "reviewed diff",
      "conclusion": "Verified example-repo change."
    }
  ]
}
```

Each referenced `grant` file must be an owner-only regular file (`0600`) with the exact 5-field `scope` matching the manifest item, a `0600` `token_file`, and an allowed `url` (HTTPS or numeric loopback HTTP by default, or `"http://100.64.0.16:18080/mcp"` with `"allow_tailnet_http": true` requiring `/usr/bin/ip` and an active `tailscale0` route):

```json
{
  "url": "http://100.64.0.16:18080/mcp",
  "allow_tailnet_http": true,
  "token_file": "/home/user/.private/example-repo-token",
  "scope": {
    "workspace_id": "hermes-personal",
    "peer_id": "pi-coordinator",
    "target_peer_id": "example-repo",
    "session_id": "example-repo-batch-1",
    "task": "example-repo-batch-1"
  }
}
```

### Interactive review, zero writes before confirmation, and reporting

Inside the idle TUI session, run `/honcho-batch` with no arguments:

1. **Offline preview (`zero writes`)**: `batch-command.ts` invokes `/usr/bin/python3 -I -B ~/.pi/agent/honcho-cli/batch.py preview <manifest> <pi_session_id>` with a `180s` timeout and `1 MiB` `maxBuffer` limit (rejecting killed or truncated output). This performs zero credential reads, zero local state writes, and zero remote Honcho calls, and computes a pinned SHA-256 `digest` over the session ID, raw manifest bytes, resolved checkouts/routes, grant descriptors, and formatted notes.
2. **Non-transcript review & confirmation**: The full bounded preview opens in the TUI editor (never posted to the chat transcript). Review the preview and submit it unchanged (`Enter` submits in the TUI editor, `Shift+Enter` inserts a newline; `Esc` cancels), then confirm the pinned `digest` in the single explicit `ctx.ui.confirm` dialog. Cancelling, modifying the preview text, declining confirmation, setting `PI_OFFLINE`, or changing Pi session or working directory aborts with **zero writes**.
3. **Verified apply**: Only after exact approval does `batch-command.ts` invoke `/usr/bin/python3 -I -B ~/.pi/agent/honcho-cli/batch.py apply <manifest> <pi_session_id> <digest>` with a `900s` timeout and `128 KiB` `maxBuffer` limit (rejecting killed or truncated output). `batch.py` recomputes the pinned `digest` before opening credentials or making upstream requests. `batch-command.ts` re-validates the startup session, working directory, and launch environment (including `PI_OFFLINE`) again after `apply` returns and before posting to chat so a session switch mid-apply never posts into the wrong conversation.
4. **Sanitized status report**: `batch-command.ts` emits a private chat status message (`customType: "honcho-batch-status"`, `display: true`, `triggerTurn: false`) containing only the digest and per-repo statuses. No note bodies, grant/manifest paths, bearer tokens, raw helper stdout/stderr, or worker transcripts are written to chat. Wiki generation remains independent of publish outcomes and is not assumed to run concurrently or synchronously with batch publishing.

Per-repo results returned by `batch.py apply` use fixed sanitized statuses and reasons:

| Status | Meaning |
| --- | --- |
| `verified` | Exact conclusion appended and confirmed present via paginated readback, or a matching pending conclusion was recovered via readback and its pending marker cleared. |
| `already present` | Exact formatted conclusion was already present during pre-readback; no duplicate append was sent. |
| `blocked` | Item could not be completed or proven safely (e.g., nonblocking lock contention or lock validation/OS error, tailnet route or credential unavailable, `MAX_TOTAL_CONCLUSIONS` reached with exact note absent, malformed/oversized/inconsistent readback pagination, pre-read or post-append readback failed/inconclusive, or a pending marker mismatch/absence). |

### Local lock/pending state and failure recovery

- `batch.py` safely creates missing state directories (`0700`), rejects symlinks at the state directory and state files (`O_NOFOLLOW`), opens state files defensively (`O_NONBLOCK`), and `fsync`s the state directory and parent directory chain before writing any pending marker or sending any append. Failing to sync a parent directory fails closed with zero upstream writes.
- `batch.py` stores per-session lock files (`<binding>.lock`, keyed by all four upstream scope fields `(workspace_id, peer_id, target_peer_id, session_id)`) and write-ahead pending markers (`<binding>.pending.json`, mode `0600`) in `$XDG_STATE_HOME/pi-honcho-batch` (default `~/.local/state/pi-honcho-batch`, mode `0700`). Lock acquisition is nonblocking (`flock(LOCK_EX | LOCK_NB)`); contention or lock validation/OS failures mark only that item `blocked` and continue the batch, preserving the first writer.
- **Readback limits & capacity**: Duplicate detection runs before the `MAX_TOTAL_CONCLUSIONS` (`1000`, `50 * 20` pages) capacity check. If a complete pre-readback shows the exact note is absent and `1000` conclusions already exist, `batch.py` does not write a pending marker or send an impossible-to-verify append, and marks the item `blocked`. Consistent pagination math (`pages == ceil(total / 50)` and exact expected page lengths) and bounded valid response envelopes are required.
- **Local-only state & same-state-directory caveat**: Locks and pending markers are strictly local to the host and state directory. Running from a different host or a different `XDG_STATE_HOME` will not see existing locks or pending markers.
- **No remote exactly-once**: Honcho does not provide remote distributed exactly-once semantics. The dedicated exclusive session and write-ahead pending marker let readback determine whether an ambiguous append succeeded.
- **Handling `pending` or aborted runs**: If a process aborts or times out mid-batch (or returns truncated/invalid helper output), some repositories may have been attempted and retain pending markers. **Never blindly retry.** Re-run `/honcho-batch` under a fresh preview and explicit approval using the **same manifest/note and same private state directory**: `batch.py` will inspect the pending marker, perform exact readback, clear the marker and report `verified` if present, or keep the item `blocked` (`pending conclusion absent on readback; automatic retry disabled`) if absent.

### Offline checks

Run offline handler, wrapper, and batch engine checks without live Honcho credentials or network access:

```sh
python3 -m unittest tests/test_pi_honcho_batch.py
node --test tests/test_pi_honcho_batch_command.mjs
```
