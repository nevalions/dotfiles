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
