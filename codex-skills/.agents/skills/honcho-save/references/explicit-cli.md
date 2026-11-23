# Explicit CLI save

Read this only when the user explicitly authorized saving the specified facts and audience, an approved exact grant exists, and native publishing is unavailable. A missing or denied automatic grant does not authorize creating a replacement. Do not borrow another session's scope or credentials.

The installed executable is `codex-honcho-mcp`. Its source contract is documented in `~/dotfiles/codex/honcho/README.md` and implemented in `codex/.codex/honcho/{server,gateway,rest}.py`; inspect those files if the installed interface differs. Do not print connection configuration or fetch credentials into tool output.

Use absolute paths to owner-owned regular JSON files outside repositories, mode `0600`, inside a private directory. No secrets belong in grant or payload files. The grant contains exactly `workspace_id`, `peer_id`, `target_peer_id`, `session_id`, and `task`, all from the approved scope. Do not guess the workspace, observer, target, or IDs. All grant values must satisfy the deployed identifier constraints.

Inspect the grant through the publisher:

```sh
codex-honcho-mcp --grant /absolute/private/grant.json --call get_grant
```

Use the returned exact scope in a mode-0600 readback argument file containing only `{"scope": <exact grant>}`. Check existing records before writing:

```sh
codex-honcho-mcp --grant /absolute/private/grant.json --call readback --arguments-file /absolute/private/readback.json
```

Create a mode-0600 payload JSON file containing exactly `scope`, `candidate`, `checks`, `verification`, and `conclusion`, following the main skill's evidence requirements and field limits. Pass JSON via the argument file rather than shell interpolation:

```sh
codex-honcho-mcp --grant /absolute/private/grant.json --call publish_verified --arguments-file /absolute/private/payload.json
codex-honcho-mcp --grant /absolute/private/grant.json --call readback --arguments-file /absolute/private/readback.json
```

Parse the CLI's MCP content envelope and the JSON text inside it. Require the same exact-session record and complete evidence suffix as the native workflow. Apply the same failure and bounded-retry rules. Remove only temporary files you created after confirmed readback; never remove native automatic grants. Do not change MCP settings or launch a differently scoped session merely to bypass a rejection.
