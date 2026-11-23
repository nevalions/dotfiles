# Honcho for Codex

The installed Pi setup has `saveMessages=false` and per-turn injection disabled.
This integration follows that behavior: no prompt, reply or transcript capture.
It uses Pi's existing workspace `hermes-personal`, observer `pi-coordinator`,
repository routing and exact-scope verified-conclusion gateway. Codex speaks
stdio MCP locally and uses the same direct v3 REST API as Pi upstream; it does
not depend on the separate upstream MCP gateway.
A Codex observer would need separate provisioning and would not automatically
have Pi's observer-relative memory. No peer is provisioned by this integration.

All runtime Python modules, the launcher and the generated hook file are
symlinked into this Stow package. Hook generation preserves machine-local
settings; no personal paths or credentials are committed. The generated
`hooks.json` is ignored by Git, like the existing generated Codex config.

The launcher reads Pi's existing `~/.honcho/config.json` (or
`HONCHO_CONFIG_PATH`), including its configured REST base URL and `hosts.pi.apiKey`,
into process memory. Supported Pi environment overrides take precedence:
`HONCHO_API_KEY`, `HONCHO_BASE_URL`/`HONCHO_URL`/`HONCHO_ENDPOINT`, and
`HONCHO_WORKSPACE`/`HONCHO_WORKSPACE_ID`. The fixed shared workspace must match
`hermes-personal`. A root shared API key is also supported. OAuth refresh is not
implemented; this deployment uses Pi's existing API key.

Only when no configured API key exists, the launcher uses the existing
`Honcho Codex` rbw password against that same REST endpoint. Unlock rbw in your
own terminal if needed. HTTP authentication failures never switch credentials,
retry through another endpoint, or fall back to the upstream MCP gateway.
No credential is printed or copied into dotfiles. The MCP registration forwards
only the named supported Honcho environment variables plus `XDG_RUNTIME_DIR`
for rbw's existing agent; existing custom allowlist entries are preserved.

The existing tailnet HTTP API requires a route through `tailscale0` before each
request. HTTPS and loopback HTTP API endpoints are supported. Redirects are
rejected so a credential is never forwarded to another endpoint. No packages
are installed by the bridge.

After pulling dotfiles on another Linux host, run the standard setup:
`python3 codex/install.py --skip-plugins`. It also installs this integration.
For a targeted update, run `python3 codex/honcho/install.py --check`, then omit
`--check` to deploy. Python 3.11+, GNU Stow, rbw, Linux iproute2 and a working
Tailscale route to the existing service are required, matching Pi. Windows and
macOS are not validated by this Linux integration. Missing credentials or an
unavailable route produce a bounded failure and leave ordinary work usable.
This narrowly merges the MCP registration and SessionStart hook and links the
launcher to this checkout, preserving other settings. Backups remain private
under `~/.codex/backups`. Keep this worktree while those links are deployed.
New MCP tools need a new Codex session. The hook may need enabling in `/hooks`;
the installer does not bypass Codex hook trust.

At SessionStart, the hook reads the repository peer card for an approved local
checkout. Linked worktrees resolve through their common Git directory. No
mapping means no automatic recall. Fork starts skip recall; workers should use
the parent handoff. The hook supplies historical context with an instruction to
verify it. Use `recall` for relevant decisions on the first repository target,
`project-*` for cross-repository findings and `code-wide` for broadly reusable
research. Query `linroot` only for user preferences. Empty memory is different
from unavailable memory. The hook does not send raw prompts or logs.

## Automatic repository publishing

The installed MCP registration uses `--auto-grant`. On top-level SessionStart
(startup), checkouts under `~/code` and the `~/ansible` repository receive an
exact repository/thread/task grant. Resume and compact renew only a
previously registered parent thread; they never promote a child or fork.
Sessions created before this integration need a fresh top-level start. Linked worktrees use
the canonical common Git directory. Dotfiles and unmapped roots stay recall-only.
No peers are provisioned and startup performs no upstream writes. Publishing
still verifies both existing peers and all exact-scope evidence fields.

Grants live as owner-only regular files under the mode-0700
`~/.codex/honcho-grants` directory, outside Git. The runtime selects a grant from
Codex-authored `params._meta.threadId`, rather than model arguments. Workers use
SubagentStart and forks are excluded, so they receive no automatic grant even
when the native runtime shares an MCP connection. Missing metadata, unsafe
permissions, symlink grants and unmatched threads deny publisher calls. These
files persist for same-thread resume; they contain scope only, never credentials
or conversation text. Starting an unmapped checkout revokes that thread's grant.

Only the parent publishes eligible verified repository findings at task
completion: inspect `get_grant`, use its exact scope, cite checked immutable
evidence and independent verification, then confirm the exact conclusion with
`readback`. User preferences still require explicit saving authorization and an
explicit `linroot` grant. A denied append must not be bypassed. Existing explicit
server arguments are preserved by the installer; remove an old custom override
or configure `args = ["--auto-grant"]` deliberately to adopt automatic mode.
New sessions and trusted SessionStart hooks are required for automatic grants.
MCP tools are discoverable in all sessions; their presence grants no write scope.

This guard follows the native [tool-call metadata implementation](https://github.com/openai/codex/blob/ccf9be8cc458bd6b8336fe84d68d8893f2691a5e/codex-rs/core/src/mcp_tool_call.rs)
(`with_mcp_tool_call_ids_meta` overwrites `threadId` with the calling thread), and
[hook event implementation](https://github.com/openai/codex/blob/ccf9be8cc458bd6b8336fe84d68d8893f2691a5e/codex-rs/hooks/src/events/session_start.rs)
(SessionStart uses the same ThreadId; SubagentStart is a separate event).
These sources are pinned to the installed Codex 0.171.0 release. Unsupported
clients without native thread metadata remain recall-only. This is a guard for
a trusted Unix user, not isolation from arbitrary processes with shell access.

## Explicit publishing from the current session

Outside a matching automatic repository grant, a request to save memory
authorizes only its requested facts and target; routine work and recall do not
authorize publication. Only the parent/coordinator may
publish; children return evidence-backed drafts. Do not use an available grant
to widen the audience or publish to unrelated peers. Existing observer and target peers must already be provisioned. After all
exact-grant and evidence checks pass, explicit publishing verifies both peers
and looks up only the granted content session. If missing, it creates that
session with task metadata and both observation flags disabled, without any
messages. An existing session is reused without rewriting it; conflicting task
metadata is denied. Recall and readback never create sessions.

Create an owner-only regular JSON grant outside the repository, with these exact
fields (use the approved repository peer or `linroot` for an authorized preference):

```json
{"workspace_id":"hermes-personal","peer_id":"pi-coordinator","target_peer_id":"example-repo","session_id":"existing-task-session","task":"existing-task-id"}
```

Set mode 0600. No token belongs in the grant. Inspect it using:

```sh
codex-honcho-mcp --grant /absolute/private/grant.json --call get_grant
```

Create a second mode-0600 JSON file with `scope` equal to that exact grant, plus
single-line nonempty `candidate` (immutable revision or primary source), `checks`
(checks and results), `verification` (independent verification/review), and
`conclusion` (one durable verified fact). Never save raw transcripts, secrets,
unverified drafts or personal data beyond an authorized preference.

```sh
codex-honcho-mcp --grant /absolute/private/grant.json --call publish_verified --arguments-file /absolute/private/payload.json
```

Read back using a mode-0600 argument file containing only `{"scope": <exact grant>}`:

```sh
codex-honcho-mcp --grant /absolute/private/grant.json --call readback --arguments-file /absolute/private/readback.json
```

Confirm the exact conclusion before reporting success. On an ambiguous error,
read back before retrying to avoid duplicates. A denied write stays denied; do
not switch credentials, provision peers, call a direct API, or remove scope.
Remove only your temporary grant/payload files after successful readback.
The CLI workflow works immediately through shell tools without changing MCP
configuration or restarting Codex. To expose the same publisher as MCP tools
in a separately scoped session, launch Codex with the Honcho server `args` set
to `["--grant", "/absolute/private/grant.json"]` via a session config override.

The grant is a connection-level guard for a trusted Unix user, not isolation
from processes with the same account and shell/vault access. It allows verified
appends and scoped readback, never memory deletion, edits or administration.

## Moving deployed links after integration

The default installer refuses links owned by another checkout. After the files
have been integrated into the intended retained checkout, run from that checkout:

```sh
python3 codex/honcho/install.py --check --relink-existing
python3 codex/honcho/install.py --relink-existing
```

This opt-in replaces only verified Honcho launcher/module/generated-hook
symlinks from the previous checkout. It preserves existing settings, hooks,
other files and the previous checkout. It never removes a worktree. Do not
relink to a checkout that does not yet contain the integrated source.
