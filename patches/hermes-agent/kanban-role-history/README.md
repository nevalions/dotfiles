# Local patch: `kanban.include_role_history`

A small local modification to the Hermes Agent source tree (`~/.hermes/hermes-agent`), preserved here because that checkout is updater-managed and treats these files as floating local changes.

## What it does

Adds one profile-scoped config key, `kanban.include_role_history` (default `true`). When `false`, a kanban worker's context omits the implicit cross-task "## Recent work by @…" block — the assignee's five latest completed runs on other tasks in the same board. Explicit task history and parent history are unaffected.

- `hermes_cli/config_defaults.py` — registers the key (and restores the truncated kanban comment block).
- `hermes_cli/kanban_db_context.py` — `_ctx_role_history()` returns early when the key is false, read via `load_user_config_effective()` so the executing profile's own config decides.
- `website/docs/user-guide/features/kanban.md` — "Optional recent-role history" section.
- `tests/hermes_cli/test_kanban_role_history.py`, `tests/gateway/test_kanban_role_history_policy.py` — the feature's tests (never committed upstream; no run recorded here).

## Why it is load-bearing, not cosmetic

Every profile on this box sets `kanban.include_role_history: false` (root config plus all named bots in `~/.hermes/profiles/*/config.yaml`). The default is `true`, i.e. stock behavior. So if this patch disappears, the setting becomes an unknown key: the behavior silently reverts to including five recent role runs in every worker's prompt, and nothing reports an error. That is a real prompt-size and context-composition change for every kanban worker.

## Status upstream

Not upstream as of `3b42157858` (`origin/main` has no `include_role_history` in `config_defaults.py`). Pushing to `NousResearch/hermes-agent` is not permitted for this account; a contribution needs a fork (`nevalions`) plus a PR.

## Apply / verify

```bash
cd ~/.hermes/hermes-agent
P=/home/linroot/dotfiles/patches/hermes-agent/kanban-role-history
git apply --check "$P/0001-kanban-include-role-history.patch"
git apply "$P/0001-kanban-include-role-history.patch"
cp "$P/tests/test_kanban_role_history_policy.py" tests/gateway/
cp "$P/tests/test_kanban_role_history.py" tests/hermes_cli/
```

Verify the running code has it:

```bash
cd ~/.hermes/hermes-agent && ~/.hermes/tools/python-3.14*/bin/python3 - <<'EOF'
from hermes_cli.config_defaults import DEFAULT_CONFIG as D
import inspect, hermes_cli.kanban_db_context as k
print('default:', D['kanban'].get('include_role_history'))
print('guard:', 'include_role_history' in inspect.getsource(k._ctx_role_history))
EOF
```

Revert (back to stock behavior — the default is `true`):

```bash
cd ~/.hermes/hermes-agent && git checkout -- hermes_cli/config_defaults.py hermes_cli/kanban_db_context.py website/docs/user-guide/features/kanban.md
```

Re-check after every `hermes update`: the updater restores local working-tree changes on top of the new code, but a conflict in `_ctx_role_history()` or `config_defaults.py` could silently drop or duplicate this patch.
