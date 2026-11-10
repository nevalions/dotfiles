# Environment and SDK prerequisite

## Shared installation

The operator's shared configuration is `~/.honcho/config.json`:

- Self-hosted `baseUrl`: `http://100.64.0.16:18000`.
- Shared workspace: `hermes-personal`.
- User peer: `linroot`.
- One AI peer per bot profile; default host `hermes` currently uses `hermes-main`.
- Repo peers live in the shared workspace, so every bot profile using that workspace can address them explicitly. This does not imply that every observer's conclusion listing is identical.

Verify settings at execution time. Config resolution can select `$HERMES_HOME/honcho.json`, then `~/.hermes/honcho.json`, before `~/.honcho/config.json`. Host keys are `hermes` for default or `hermes_<profile>` for a named profile. Use the executing session's resolved host and workspace, not an unrelated bot's credentials. Do not print the full config. Never change the shared config as part of ingestion.

## Materialize a peer

The installed Python SDK's `Honcho.peer(id)` performs a get-or-create API request. `workspace_id` must be explicit: omitting it can trigger workspace creation and a 401 with a workspace-scoped key.

After resolving `config_path`, `host_key`, and the exact `repo_peer` in memory, use:

```python
import json
from pathlib import Path
import honcho

cfg = json.loads(Path(config_path).expanduser().read_text())
host = cfg['hosts'][host_key]
KEY = host.get('apiKey') or cfg.get('apiKey')
BASE = cfg.get('baseUrl')
workspace = host['workspace']
if not KEY or not BASE:
    raise RuntimeError('Missing Honcho credentials or base URL; stop without printing config')
if workspace != 'hermes-personal':
    raise RuntimeError('Workspace differs from the requested shared workspace; resolve before writing')
client = honcho.Honcho(api_key=KEY, base_url=BASE, workspace_id='hermes-personal')
client.peer(repo_peer)
```

This is a template, not a self-contained command: supply only verified non-secret input variables. Load credentials directly from authorized config and keep them out of logs. Do not execute this snippet merely to test a skill installation. If the SDK is unavailable, stop and report the prerequisite rather than installing it without authorization.

## Evidence and version sensitivity

The materialization pitfall was supplied by the operator's validated kube-lvl47 workflow. Local inspection confirmed the installed SDK constructor and `peer` API, and the plugin's observer-scoped creation and card-writing paths. Other plugin versions may fix target creation; explicit get-or-create remains a safe prerequisite within authorized ingestion.

The plugin's `list_conclusions` uses a default limit of twenty and resolves conclusions through an observer's `conclusions_of(target)`. For complete readback, inspect the installed SDK and plugin before selecting pagination or observer scope; never assume a global target-only collection.
