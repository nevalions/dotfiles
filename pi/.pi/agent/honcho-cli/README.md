# Honcho publishing from Pi CLI

Plain `pi`, `pi-team`, and PurpleFlow keep their current user MCP config. **Do not add this server or extension to shared config or the discovered `extensions/` directory.** Launch explicitly with:

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

Use the scoped endpoint; only HTTPS or numeric HTTP loopback is accepted. The MCP server authorizes every request against the exact launch grant and reconstructs the upstream arguments from it. Only grant inspection, scoped readback and one-conclusion append per call are offered. Evidence fields are mandatory, but the server cannot establish that the evidence is true. The coordinator checks it against primary sources, checks and review before publishing. On ambiguity or timeout, read back before retrying to avoid duplicates.

The stdio server trusts its launching Unix account and is not an OS sandbox. It prevents alternate scopes, raw upstream methods, or forged roles **through this MCP connection**. A process running as the same user with shell or file access is not isolated from the grant/token. Do not use this to segregate mutually untrusted agents; use a separately administered remote gateway with distinct credentials for that deployment.
