"""Native admission uses the owning profile's history policy, not the launcher's."""
from contextlib import closing
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from hermes_cli import kanban_db as kb
from hermes_cli.config import atomic_config_write
from hermes_cli.config_effective import load_user_config_effective
from hermes_cli.kanban_db_connect import connect
from gateway.session_authorities import owner_scope
from gateway.session_contract import SessionActor
from gateway.session_kanban import build_kanban_policy


@pytest.mark.parametrize("enabled", [False, True])
def test_native_admission_freezes_owner_role_history_policy(tmp_path, monkeypatch, enabled):
    home = tmp_path / ".hermes"
    owner = home / "profiles" / "worker"
    owner.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(home))
    # owner_scope lazily imports gateway.run and its process bootstrap. The
    # runner already prepared dependencies; admission must not recover/update
    # the actual checkout. Keep the real bootstrap API and home-I/O guard.
    from hermes_cli import _early_recovery, venv_sync
    from pm import environments

    with monkeypatch.context() as boot:
        boot.setattr(_early_recovery, "restore_interrupted_pull", lambda *_: False)
        boot.setattr(_early_recovery, "recover_if_needed", lambda *_: False)
        boot.setattr(venv_sync, "prepare_launch", lambda *_: None)
        boot.setattr(environments, "activate_dependencies", lambda *_: None)
        import gateway.run  # noqa: F401
    atomic_config_write(home / "config.yaml", {"kanban": {"include_role_history": not enabled}})
    atomic_config_write(owner / "config.yaml", {
        "kanban": {"include_role_history": enabled},
        "model": {"default": "test-model", "provider": "custom"},
    })
    board_db = tmp_path / "board.db"
    with closing(connect(board_db)) as conn:
        old = kb.create_task(conn, title="Old unrelated task", assignee="worker")
        assert kb.complete_task(conn, old, result="OLD_POLICY_SENTINEL")
        task_id = kb.create_task(conn, title="Current task", assignee="worker",
                                 workspace_kind="dir", workspace_path=str(tmp_path))
        task = kb.claim_task(conn, task_id)
        assert task is not None
    authority = SimpleNamespace(profile_id=str(owner),
        runner=SimpleNamespace(config=SimpleNamespace(multiplex_profiles=True)))
    connection = SimpleNamespace(authority=authority, native_owner=True,
        actor=SessionActor("owner", str(owner), frozenset({"session:create"}), "transport"))
    params = dict(board="default", db=str(board_db), task_id=task.id,
                  run_id=task.current_run_id, claim_lock=task.claim_lock)
    # Same scope used around native RPC handlers; no mocked config/profile resolution.
    with owner_scope(authority):
        policy, _ = build_kanban_policy(connection, params, load_user_config_effective())
    context = json.loads(policy.kanban_json)["context"]
    assert ("OLD_POLICY_SENTINEL" in context) is enabled
    assert "Current task" in context
    assert policy.config()["kanban"]["include_role_history"] is enabled
