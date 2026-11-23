"""Role-history opt-out preserves explicit task continuity in a shared board."""
from contextlib import closing
from pathlib import Path

import pytest

from hermes_cli import kanban_db as kb
from hermes_cli.kanban_db_connect import connect
from hermes_cli.config import atomic_config_write
from hermes_constants import reset_hermes_home_override, set_hermes_home_override


@pytest.mark.parametrize("enabled", [False, True, None])
def test_worker_context_role_history_uses_bound_owner(tmp_path, monkeypatch, enabled):
    home = tmp_path / ".hermes"
    owner = home / "profiles" / "worker"
    author = home / "profiles" / "author"
    owner.mkdir(parents=True)
    author.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(author))
    # The launch/author profile deliberately disagrees with the owner.
    atomic_config_write(author / "config.yaml", {"kanban": {"include_role_history": enabled is False}})
    atomic_config_write(owner / "config.yaml", {
        "kanban": {} if enabled is None else {"include_role_history": enabled},
    })
    with closing(connect(tmp_path / "board.db")) as conn:
        old = kb.create_task(conn, title="Unrelated old card", assignee="worker")
        assert kb.complete_task(conn, old, result="UNRELATED_OLD_SENTINEL")
        parent = kb.create_task(conn, title="Explicit prerequisite", assignee="worker")
        assert kb.complete_task(conn, parent, result="PARENT_HANDOFF_SENTINEL")
        task = kb.create_task(conn, title="Current task", assignee="worker", parents=[parent])
        assert kb.claim_task(conn, task)
        assert kb.block_task(conn, task, reason="SAME_TASK_ATTEMPT_SENTINEL")
        kb.add_comment(conn, task, "worker", "SAME_TASK_COMMENT_SENTINEL")
        token = set_hermes_home_override(str(owner))
        try:
            context = kb.build_worker_context(conn, task)
        finally:
            reset_hermes_home_override(token)
        assert ("UNRELATED_OLD_SENTINEL" in context) is (enabled is not False)
        assert ("## Recent work by @worker" in context) is (enabled is not False)
        assert "PARENT_HANDOFF_SENTINEL" in context
        assert "SAME_TASK_ATTEMPT_SENTINEL" in context
        assert "SAME_TASK_COMMENT_SENTINEL" in context
