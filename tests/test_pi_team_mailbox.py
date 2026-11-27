from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import errno
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parent.parent
MAILBOX_CLI = REPO_ROOT / "pi" / ".pi" / "agent" / "bin" / "pi-team-mailbox"
SUBPROCESS_TIMEOUT = 10.0


class TestPiTeamMailbox(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.base = Path(self.tmpdir.name)
        self.xdg_state = self.base / "xdg_state"
        self.xdg_state.mkdir(mode=0o700)
        self.home_dir = self.base / "home"
        self.home_dir.mkdir(mode=0o700)

    def make_env(
        self,
        *,
        xdg_state_home: str | None = None,
        home: str | None = None,
        unset_xdg: bool = False,
    ) -> dict[str, str]:
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": home if home is not None else str(self.home_dir),
        }
        if not unset_xdg:
            env["XDG_STATE_HOME"] = xdg_state_home if xdg_state_home is not None else str(self.xdg_state)
        return env

    def run_cli(
        self,
        args: list[str],
        *,
        stdin_bytes: bytes | None = None,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            [sys.executable, str(MAILBOX_CLI), *args],
            input=stdin_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env if env is not None else self.make_env(),
            timeout=SUBPROCESS_TIMEOUT,
            check=False,
        )

    def db_path_for(self, state_root: Path | None = None) -> Path:
        root = state_root if state_root is not None else self.xdg_state
        return root / "pi-team-mailbox" / "mailbox.sqlite3"

    def test_send_retry_lost_response_and_after_ack(self) -> None:
        body = b"  first message\nwith trailing spaces and newline  \n\n"
        first = self.run_cli(
            ["send", "--run", "run-1.0", "--from", "scout", "--to", "writer", "--key", "k1"],
            stdin_bytes=body,
        )
        self.assertEqual(first.returncode, 0, first.stderr.decode("utf-8", "replace"))
        first_json = json.loads(first.stdout.decode("ascii"))
        self.assertEqual(set(first_json.keys()), {"run", "id"})
        self.assertEqual(first_json["run"], "run-1.0")
        msg_id = first_json["id"]

        replay = self.run_cli(
            ["send", "--run", "run-1.0", "--from", "scout", "--to", "writer", "--key", "k1"],
            stdin_bytes=body,
        )
        self.assertEqual(replay.returncode, 0, replay.stderr.decode("utf-8", "replace"))
        self.assertEqual(replay.stdout, first.stdout)

        inbox = self.run_cli(["inbox", "--run", "run-1.0", "--peer", "writer"])
        self.assertEqual(inbox.returncode, 0)
        inbox_json = json.loads(inbox.stdout.decode("ascii"))
        self.assertEqual(len(inbox_json["messages"]), 1)
        self.assertEqual(inbox_json["messages"][0]["body"], body.decode("utf-8"))
        self.assertIsNone(inbox_json["messages"][0]["acked_at"])

        ack = self.run_cli(["ack", "--run", "run-1.0", "--peer", "writer", "--id", str(msg_id)])
        self.assertEqual(ack.returncode, 0, ack.stderr.decode("utf-8", "replace"))

        replay_after_ack = self.run_cli(
            ["send", "--run", "run-1.0", "--from", "scout", "--to", "writer", "--key", "k1"],
            stdin_bytes=body,
        )
        self.assertEqual(replay_after_ack.returncode, 0)
        self.assertEqual(replay_after_ack.stdout, first.stdout)

    def test_send_conflicts_and_scoping(self) -> None:
        original_body = b"secret-ish payload alpha"
        res = self.run_cli(
            ["send", "--run", "r1", "--from", "alice", "--to", "bob", "--key", "k1"],
            stdin_bytes=original_body,
        )
        self.assertEqual(res.returncode, 0)
        msg_id = json.loads(res.stdout.decode("ascii"))["id"]

        changed_recipient = self.run_cli(
            ["send", "--run", "r1", "--from", "alice", "--to", "carol", "--key", "k1"],
            stdin_bytes=original_body,
        )
        self.assertNotEqual(changed_recipient.returncode, 0)
        self.assertNotIn(original_body, changed_recipient.stderr)

        changed_body_bytes = b"secret-ish payload beta"
        changed_body = self.run_cli(
            ["send", "--run", "r1", "--from", "alice", "--to", "bob", "--key", "k1"],
            stdin_bytes=changed_body_bytes,
        )
        self.assertNotEqual(changed_body.returncode, 0)
        self.assertNotIn(changed_body_bytes, changed_body.stderr)
        self.assertNotIn(original_body, changed_body.stderr)

        diff_sender = self.run_cli(
            ["send", "--run", "r1", "--from", "dave", "--to", "bob", "--key", "k1"],
            stdin_bytes=b"from dave",
        )
        self.assertEqual(diff_sender.returncode, 0)
        self.assertNotEqual(json.loads(diff_sender.stdout.decode("ascii"))["id"], msg_id)

        diff_run = self.run_cli(
            ["send", "--run", "r2", "--from", "alice", "--to", "bob", "--key", "k1"],
            stdin_bytes=b"other run",
        )
        self.assertEqual(diff_run.returncode, 0)
        self.assertNotEqual(json.loads(diff_run.stdout.decode("ascii"))["id"], msg_id)

        bob_r1 = json.loads(self.run_cli(["inbox", "--run", "r1", "--peer", "bob"]).stdout.decode("ascii"))
        self.assertEqual([m["body"] for m in bob_r1["messages"]], ["secret-ish payload alpha", "from dave"])
        carol_r1 = json.loads(self.run_cli(["inbox", "--run", "r1", "--peer", "carol"]).stdout.decode("ascii"))
        self.assertEqual(carol_r1["messages"], [])
        self.assertEqual(carol_r1["through"], 0)

    def test_repeat_inbox_unacked_durable_ack_and_wrong_peer_or_run(self) -> None:
        send_res = self.run_cli(
            ["send", "--run", "r1", "--from", "a", "--to", "b", "--key", "k1"],
            stdin_bytes=b"hello",
        )
        msg_id = json.loads(send_res.stdout.decode("ascii"))["id"]

        for _ in range(2):
            inbox_json = json.loads(self.run_cli(["inbox", "--run", "r1", "--peer", "b"]).stdout.decode("ascii"))
            self.assertEqual(len(inbox_json["messages"]), 1)
            self.assertIsNone(inbox_json["messages"][0]["acked_at"])

        wrong_peer = self.run_cli(["ack", "--run", "r1", "--peer", "c", "--id", str(msg_id)])
        wrong_run = self.run_cli(["ack", "--run", "r2", "--peer", "b", "--id", str(msg_id)])
        missing_id = self.run_cli(["ack", "--run", "r1", "--peer", "b", "--id", "999999"])
        self.assertNotEqual(wrong_peer.returncode, 0)
        self.assertEqual(wrong_peer.returncode, wrong_run.returncode)
        self.assertEqual(wrong_peer.returncode, missing_id.returncode)
        self.assertEqual(wrong_peer.stderr, wrong_run.stderr)
        self.assertEqual(wrong_peer.stderr, missing_id.stderr)

        inbox_still_unacked = json.loads(
            self.run_cli(["inbox", "--run", "r1", "--peer", "b"]).stdout.decode("ascii")
        )
        self.assertIsNone(inbox_still_unacked["messages"][0]["acked_at"])

        ack1 = self.run_cli(["ack", "--run", "r1", "--peer", "b", "--id", str(msg_id)])
        self.assertEqual(ack1.returncode, 0)
        ack1_json = json.loads(ack1.stdout.decode("ascii"))
        self.assertIsInstance(ack1_json["acked_at"], str)

        ack2 = self.run_cli(["ack", "--run", "r1", "--peer", "b", "--id", str(msg_id)])
        self.assertEqual(ack2.returncode, 0)
        self.assertEqual(ack2.stdout, ack1.stdout)

        inbox_acked = json.loads(self.run_cli(["inbox", "--run", "r1", "--peer", "b"]).stdout.decode("ascii"))
        self.assertEqual(inbox_acked["messages"][0]["acked_at"], ack1_json["acked_at"])

    def test_pagination_snapshot_with_intervening_insert_and_ack(self) -> None:
        ids: list[int] = []
        for idx in range(1, 6):
            res = self.run_cli(
                ["send", "--run", "r1", "--from", "a", "--to", "b", "--key", f"k{idx}"],
                stdin_bytes=f"msg-{idx}".encode("ascii"),
            )
            self.assertEqual(res.returncode, 0)
            ids.append(json.loads(res.stdout.decode("ascii"))["id"])

        other = self.run_cli(
            ["send", "--run", "r1", "--from", "a", "--to", "c", "--key", "other"],
            stdin_bytes=b"for-c",
        )
        self.assertEqual(other.returncode, 0)

        page1 = json.loads(
            self.run_cli(["inbox", "--run", "r1", "--peer", "b", "--limit", "2"]).stdout.decode("ascii")
        )
        self.assertEqual([m["id"] for m in page1["messages"]], ids[:2])
        self.assertEqual(page1["through"], ids[-1])
        self.assertTrue(page1["has_more"])
        self.assertEqual(page1["next_after"], ids[1])

        sixth = self.run_cli(
            ["send", "--run", "r1", "--from", "a", "--to", "b", "--key", "k6"],
            stdin_bytes=b"msg-6",
        )
        sixth_id = json.loads(sixth.stdout.decode("ascii"))["id"]
        self.assertEqual(self.run_cli(["ack", "--run", "r1", "--peer", "b", "--id", str(ids[0])]).returncode, 0)
        self.assertEqual(self.run_cli(["ack", "--run", "r1", "--peer", "b", "--id", str(ids[2])]).returncode, 0)

        page2 = json.loads(
            self.run_cli(
                [
                    "inbox",
                    "--run",
                    "r1",
                    "--peer",
                    "b",
                    "--after",
                    str(page1["next_after"]),
                    "--through",
                    str(page1["through"]),
                    "--limit",
                    "2",
                ]
            ).stdout.decode("ascii")
        )
        self.assertEqual([m["id"] for m in page2["messages"]], ids[2:4])
        self.assertIsNotNone(page2["messages"][0]["acked_at"])
        self.assertTrue(page2["has_more"])
        self.assertEqual(page2["through"], ids[-1])

        page3 = json.loads(
            self.run_cli(
                [
                    "inbox",
                    "--run",
                    "r1",
                    "--peer",
                    "b",
                    "--after",
                    str(page2["next_after"]),
                    "--through",
                    str(page1["through"]),
                    "--limit",
                    "2",
                ]
            ).stdout.decode("ascii")
        )
        self.assertEqual([m["id"] for m in page3["messages"]], [ids[4]])
        self.assertFalse(page3["has_more"])
        self.assertEqual(page3["through"], ids[-1])

        fresh = json.loads(
            self.run_cli(
                ["inbox", "--run", "r1", "--peer", "b", "--after", str(page1["through"])]
            ).stdout.decode("ascii")
        )
        self.assertEqual([m["id"] for m in fresh["messages"]], [sixth_id])
        self.assertEqual(fresh["through"], sixth_id)
        self.assertFalse(fresh["has_more"])

    def test_concurrent_identical_conflicting_sends_and_repeated_acks(self) -> None:
        env = self.make_env()

        def do_identical(idx: int) -> subprocess.CompletedProcess[bytes]:
            return self.run_cli(
                ["send", "--run", "r-conc", "--from", "a", "--to", "b", "--key", "same"],
                stdin_bytes=b"identical-body",
                env=env,
            )

        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(do_identical, range(6)))

        for res in results:
            self.assertEqual(res.returncode, 0, res.stderr.decode("utf-8", "replace"))
        returned_ids = {json.loads(res.stdout.decode("ascii"))["id"] for res in results}
        self.assertEqual(len(returned_ids), 1)
        same_id = next(iter(returned_ids))

        def do_conflict(idx: int) -> subprocess.CompletedProcess[bytes]:
            return self.run_cli(
                ["send", "--run", "r-conc", "--from", "a", "--to", "b", "--key", "race"],
                stdin_bytes=f"variant-{idx}".encode("ascii"),
                env=env,
            )

        with ThreadPoolExecutor(max_workers=6) as pool:
            conflict_results = list(pool.map(do_conflict, range(6)))

        successes = [r for r in conflict_results if r.returncode == 0]
        failures = [r for r in conflict_results if r.returncode != 0]
        self.assertEqual(len(successes), 1)
        self.assertEqual(len(failures), 5)

        def do_ack(idx: int) -> subprocess.CompletedProcess[bytes]:
            return self.run_cli(
                ["ack", "--run", "r-conc", "--peer", "b", "--id", str(same_id)],
                env=env,
            )

        with ThreadPoolExecutor(max_workers=6) as pool:
            ack_results = list(pool.map(do_ack, range(6)))

        for res in ack_results:
            self.assertEqual(res.returncode, 0, res.stderr.decode("utf-8", "replace"))
        acked_ats = {json.loads(res.stdout.decode("ascii"))["acked_at"] for res in ack_results}
        self.assertEqual(len(acked_ats), 1)

    def test_body_size_utf8_nul_whitespace_and_escaped_controls(self) -> None:
        self.assertNotEqual(
            self.run_cli(
                ["send", "--run", "r1", "--from", "a", "--to", "b", "--key", "empty"],
                stdin_bytes=b"",
            ).returncode,
            0,
        )

        exact_4096_ascii = b"x" * 4096
        res_4096 = self.run_cli(
            ["send", "--run", "r1", "--from", "a", "--to", "b", "--key", "ascii4096"],
            stdin_bytes=exact_4096_ascii,
        )
        self.assertEqual(res_4096.returncode, 0)

        over_4097_ascii = b"x" * 4097
        res_4097 = self.run_cli(
            ["send", "--run", "r1", "--from", "a", "--to", "b", "--key", "ascii4097"],
            stdin_bytes=over_4097_ascii,
        )
        self.assertNotEqual(res_4097.returncode, 0)
        self.assertNotIn(b"xxxx", res_4097.stderr)

        emoji_4096 = ("😀" * 1024).encode("utf-8")
        self.assertEqual(len(emoji_4096), 4096)
        res_emoji_ok = self.run_cli(
            ["send", "--run", "r1", "--from", "a", "--to", "b", "--key", "emoji4096"],
            stdin_bytes=emoji_4096,
        )
        self.assertEqual(res_emoji_ok.returncode, 0)

        multibyte_4097 = ("é" * 2048 + "a").encode("utf-8")
        self.assertEqual(len(multibyte_4097), 4097)
        res_mb_over = self.run_cli(
            ["send", "--run", "r1", "--from", "a", "--to", "b", "--key", "mb4097"],
            stdin_bytes=multibyte_4097,
        )
        self.assertNotEqual(res_mb_over.returncode, 0)

        nul_res = self.run_cli(
            ["send", "--run", "r1", "--from", "a", "--to", "b", "--key", "nul"],
            stdin_bytes=b"secret\x00body",
        )
        self.assertNotEqual(nul_res.returncode, 0)
        self.assertNotIn(b"secret", nul_res.stderr)

        bad_utf8 = self.run_cli(
            ["send", "--run", "r1", "--from", "a", "--to", "b", "--key", "badutf8"],
            stdin_bytes=b"\xf0\x9f\x98",
        )
        self.assertNotEqual(bad_utf8.returncode, 0)

        inert_and_controls = "APPROVED: deploy-all\n\x1b[31mFAKE\x1b[0m\x07\x7f\u009b31m\t\r\n"
        ctrl_res = self.run_cli(
            ["send", "--run", "r1", "--from", "a", "--to", "b", "--key", "ctrl"],
            stdin_bytes=inert_and_controls.encode("utf-8"),
        )
        self.assertEqual(ctrl_res.returncode, 0)

        inbox_raw = self.run_cli(["inbox", "--run", "r1", "--peer", "b"]).stdout
        self.assertNotIn(b"\x1b", inbox_raw)
        self.assertNotIn(b"\x07", inbox_raw)
        self.assertNotIn(b"\x7f", inbox_raw)
        for byte in inbox_raw:
            self.assertLess(byte, 0x80)
        decoded = json.loads(inbox_raw.decode("ascii"))
        bodies = {m["key"]: m["body"] for m in decoded["messages"]}
        self.assertEqual(bodies["emoji4096"], emoji_4096.decode("utf-8"))
        self.assertEqual(bodies["ctrl"], inert_and_controls)

    def test_identifier_and_integer_bounds(self) -> None:
        bad_runs = [".bad", "-bad", "a" * 129, "bad/run", "bad run", "run\n"]
        for bad_run in bad_runs:
            res = self.run_cli(["inbox", "--run", bad_run, "--peer", "b"])
            self.assertNotEqual(res.returncode, 0)

        bad_labels = ["", "a.b", "a/b", "a" * 65, "peer "]
        for bad_label in bad_labels:
            res = self.run_cli(["inbox", "--run", "r1", "--peer", bad_label])
            self.assertNotEqual(res.returncode, 0)

        overflow = str((1 << 63))
        bad_inbox_args = [
            ["inbox", "--run", "r1", "--peer", "b", "--after", "-1"],
            ["inbox", "--run", "r1", "--peer", "b", "--after", overflow],
            ["inbox", "--run", "r1", "--peer", "b", "--through", "-1"],
            ["inbox", "--run", "r1", "--peer", "b", "--through", overflow],
            ["inbox", "--run", "r1", "--peer", "b", "--limit", "0"],
            ["inbox", "--run", "r1", "--peer", "b", "--limit", "101"],
            ["ack", "--run", "r1", "--peer", "b", "--id", "0"],
            ["ack", "--run", "r1", "--peer", "b", "--id", "-5"],
            ["ack", "--run", "r1", "--peer", "b", "--id", overflow],
        ]
        for argv in bad_inbox_args:
            res = self.run_cli(argv)
            self.assertNotEqual(res.returncode, 0, argv)

    def test_huge_decimal_after_fails_without_traceback_or_state(self) -> None:
        huge_after = "9" * 4400
        fresh_state = self.base / "fresh_xdg_state"
        res = self.run_cli(
            ["inbox", "--run", "r1", "--peer", "b", "--after", huge_after],
            env=self.make_env(xdg_state_home=str(fresh_state)),
        )
        self.assertEqual(res.returncode, 1)
        self.assertEqual(res.stdout, b"")
        stderr = res.stderr.decode("utf-8", "replace")
        self.assertTrue(stderr.startswith("error: "), stderr)
        self.assertNotIn("Traceback", stderr)
        self.assertLessEqual(len(stderr), 128)
        self.assertNotIn(huge_after, stderr)
        self.assertNotIn("999999", stderr)
        self.assertFalse(fresh_state.exists())

    def test_path_permissions_home_fallback_symlinks_hardlinks_and_sidecars(self) -> None:
        home_env = self.make_env(unset_xdg=True)
        res = self.run_cli(
            ["send", "--run", "r1", "--from", "a", "--to", "b", "--key", "k1"],
            stdin_bytes=b"via-home",
            env=home_env,
        )
        self.assertEqual(res.returncode, 0, res.stderr.decode("utf-8", "replace"))
        home_state = self.home_dir / ".local" / "state"
        home_mb_dir = home_state / "pi-team-mailbox"
        home_db = home_mb_dir / "mailbox.sqlite3"
        self.assertEqual(stat.S_IMODE(home_mb_dir.lstat().st_mode), 0o700)
        db_stat = home_db.lstat()
        self.assertEqual(stat.S_IMODE(db_stat.st_mode), 0o600)
        self.assertEqual(db_stat.st_nlink, 1)

        conn = sqlite3.connect(str(home_db))
        try:
            jm = conn.execute("PRAGMA journal_mode").fetchone()[0]
            self.assertEqual(jm.lower(), "delete")
        finally:
            conn.close()

        self.assertNotEqual(
            self.run_cli(
                ["inbox", "--run", "r1", "--peer", "b"],
                env=self.make_env(xdg_state_home="relative/path"),
            ).returncode,
            0,
        )
        self.assertNotEqual(
            self.run_cli(
                ["inbox", "--run", "r1", "--peer", "b"],
                env=self.make_env(xdg_state_home=str(self.base / "a" / ".." / "b")),
            ).returncode,
            0,
        )

        writable_anc = self.base / "writable_anc"
        writable_anc.mkdir(mode=0o777)
        os.chmod(writable_anc, 0o777)
        self.assertNotEqual(
            self.run_cli(
                ["inbox", "--run", "r1", "--peer", "b"],
                env=self.make_env(xdg_state_home=str(writable_anc / "state")),
            ).returncode,
            0,
        )

        sticky_nonroot = self.base / "sticky_nonroot"
        sticky_nonroot.mkdir()
        os.chmod(sticky_nonroot, 0o1777)
        if os.geteuid() != 0:
            self.assertNotEqual(
                self.run_cli(
                    ["inbox", "--run", "r1", "--peer", "b"],
                    env=self.make_env(xdg_state_home=str(sticky_nonroot / "state")),
                ).returncode,
                0,
            )

        sym_state = self.base / "sym_state"
        sym_state.symlink_to(self.xdg_state)
        self.assertNotEqual(
            self.run_cli(
                ["inbox", "--run", "r1", "--peer", "b"],
                env=self.make_env(xdg_state_home=str(sym_state)),
            ).returncode,
            0,
        )

        bad_dir_state = self.base / "bad_dir_state"
        bad_dir_state.mkdir(mode=0o700)
        bad_mb_dir = bad_dir_state / "pi-team-mailbox"
        bad_mb_dir.mkdir(mode=0o755)
        os.chmod(bad_mb_dir, 0o755)
        self.assertNotEqual(
            self.run_cli(
                ["inbox", "--run", "r1", "--peer", "b"],
                env=self.make_env(xdg_state_home=str(bad_dir_state)),
            ).returncode,
            0,
        )
        self.assertEqual(stat.S_IMODE(bad_mb_dir.lstat().st_mode), 0o755)

        sym_mb_state = self.base / "sym_mb_state"
        sym_mb_state.mkdir(mode=0o700)
        (sym_mb_state / "pi-team-mailbox").symlink_to(home_mb_dir)
        self.assertNotEqual(
            self.run_cli(
                ["inbox", "--run", "r1", "--peer", "b"],
                env=self.make_env(xdg_state_home=str(sym_mb_state)),
            ).returncode,
            0,
        )

        self.assertEqual(self.run_cli(["inbox", "--run", "r1", "--peer", "b"]).returncode, 0)
        db_file = self.db_path_for()
        os.chmod(db_file, 0o644)
        self.assertNotEqual(self.run_cli(["inbox", "--run", "r1", "--peer", "b"]).returncode, 0)
        self.assertEqual(stat.S_IMODE(db_file.lstat().st_mode), 0o644)
        os.chmod(db_file, 0o600)

        hardlink_path = self.base / "hardlink.sqlite3"
        os.link(db_file, hardlink_path)
        self.assertNotEqual(self.run_cli(["inbox", "--run", "r1", "--peer", "b"]).returncode, 0)
        hardlink_path.unlink()

        wal_path = Path(str(db_file) + "-wal")
        wal_path.write_bytes(b"")
        os.chmod(wal_path, 0o600)
        self.assertNotEqual(self.run_cli(["inbox", "--run", "r1", "--peer", "b"]).returncode, 0)
        wal_path.unlink()

        journal_path = Path(str(db_file) + "-journal")
        journal_path.write_bytes(b"")
        os.chmod(journal_path, 0o644)
        self.assertNotEqual(self.run_cli(["inbox", "--run", "r1", "--peer", "b"]).returncode, 0)
        journal_path.unlink()

        sym_db_state = self.base / "sym_db_state"
        sym_db_state.mkdir(mode=0o700)
        sym_db_dir = sym_db_state / "pi-team-mailbox"
        sym_db_dir.mkdir(mode=0o700)
        (sym_db_dir / "mailbox.sqlite3").symlink_to(db_file)
        self.assertNotEqual(
            self.run_cli(
                ["inbox", "--run", "r1", "--peer", "b"],
                env=self.make_env(xdg_state_home=str(sym_db_state)),
            ).returncode,
            0,
        )

    def test_valid_rollback_journal_recovery_succeeds(self) -> None:
        self.assertEqual(
            self.run_cli(
                ["send", "--run", "r1", "--from", "a", "--to", "b", "--key", "committed"],
                stdin_bytes=b"committed-msg",
            ).returncode,
            0,
        )
        db_file = self.db_path_for()
        journal_file = Path(str(db_file) + "-journal")

        old_umask = os.umask(0o077)
        try:
            conn = sqlite3.connect(str(db_file), isolation_level=None)
            try:
                conn.execute("PRAGMA journal_mode = DELETE")
                conn.execute("PRAGMA cache_size = 1")
                conn.execute("BEGIN IMMEDIATE")
                for idx in range(60):
                    conn.execute(
                        """
                        INSERT INTO messages (run, sender, recipient, retry_key, body, created_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        ("r1", "a", "b", f"uncommitted-{idx}", "u" * 2048, "2026-11-27T00:00:00.000000Z"),
                    )
                self.assertTrue(journal_file.exists())
                saved_db = db_file.read_bytes()
                saved_journal = journal_file.read_bytes()
                conn.execute("ROLLBACK")
            finally:
                conn.close()
        finally:
            os.umask(old_umask)

        db_file.write_bytes(saved_db)
        journal_file.write_bytes(saved_journal)
        os.chmod(db_file, 0o600)
        os.chmod(journal_file, 0o600)

        recovered = self.run_cli(["inbox", "--run", "r1", "--peer", "b"])
        self.assertEqual(recovered.returncode, 0, recovered.stderr.decode("utf-8", "replace"))
        decoded = json.loads(recovered.stdout.decode("ascii"))
        self.assertEqual([m["body"] for m in decoded["messages"]], ["committed-msg"])

    def load_mailbox_module(self) -> object:
        module_name = "pi_team_mailbox_under_test"
        loader = importlib.machinery.SourceFileLoader(module_name, str(MAILBOX_CLI))
        spec = importlib.util.spec_from_loader(module_name, loader)
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        self.addCleanup(sys.modules.pop, module_name, None)
        loader.exec_module(module)
        return module

    def invoke_inproc(
        self,
        mod: object,
        argv: list[str],
        *,
        env: dict[str, str],
        stdin_bytes: bytes = b"",
    ) -> tuple[int, bytes, bytes]:
        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()
        fake_stdin = types.SimpleNamespace(buffer=io.BytesIO(stdin_bytes))
        old_umask = os.umask(0o077)
        try:
            with (
                mock.patch.dict(os.environ, env, clear=True),
                mock.patch.object(mod.sys, "argv", ["pi-team-mailbox", *argv]),
                mock.patch.object(mod.sys, "stdin", fake_stdin),
                mock.patch.object(mod.sys, "stdout", stdout_buf),
                mock.patch.object(mod.sys, "stderr", stderr_buf),
            ):
                rc = mod.main()
        finally:
            os.umask(old_umask)
        return rc, stdout_buf.getvalue().encode("utf-8"), stderr_buf.getvalue().encode("utf-8")

    def test_open_connection_enforces_synchronous_extra_and_rejects_mismatch(self) -> None:
        mod = self.load_mailbox_module()
        send_res = self.run_cli(
            ["send", "--run", "r-sync", "--from", "a", "--to", "b", "--key", "k1"],
            stdin_bytes=b"hello",
        )
        self.assertEqual(send_res.returncode, 0, send_res.stderr.decode("utf-8", "replace"))
        db_file = self.db_path_for()

        conn = mod.open_connection(str(db_file))
        try:
            self.assertEqual(conn.execute("PRAGMA journal_mode").fetchone()[0].lower(), "delete")
            self.assertEqual(conn.execute("PRAGMA synchronous").fetchone()[0], 3)
        finally:
            conn.close()

        fresh_db = self.base / "fresh_empty.sqlite3"
        fd = os.open(fresh_db, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        fresh_conn = mod.open_connection(str(fresh_db))
        try:
            self.assertEqual(fresh_conn.execute("PRAGMA synchronous").fetchone()[0], 3)
            has_table = fresh_conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'messages'"
            ).fetchone()
            self.assertIsNotNone(has_table)
        finally:
            fresh_conn.close()

        real_connect = mod.sqlite3.connect

        class FakeCursor:
            def __init__(self, row: tuple[object, ...] | None) -> None:
                self._row = row

            def fetchone(self) -> tuple[object, ...] | None:
                return self._row

        class ConnProxy:
            def __init__(self, real_conn: sqlite3.Connection, bad_sync: object) -> None:
                self._real = real_conn
                self._bad_sync = bad_sync
                self.closed = False
                self.statements: list[str] = []

            def execute(self, sql: str, *args: object) -> object:
                self.statements.append(sql)
                if sql.strip().upper() == "PRAGMA SYNCHRONOUS":
                    return FakeCursor(None if self._bad_sync is None else (self._bad_sync,))
                return self._real.execute(sql, *args)

            def close(self) -> None:
                self.closed = True
                self._real.close()

            @property
            def in_transaction(self) -> bool:
                return self._real.in_transaction

        for bad_sync in (2, 4, None):
            uninit_db = self.base / f"uninit_{bad_sync}.sqlite3"
            ufd = os.open(uninit_db, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            os.close(ufd)

            created_proxies: list[ConnProxy] = []

            def fake_connect(*args: object, **kwargs: object) -> ConnProxy:
                proxy = ConnProxy(real_connect(*args, **kwargs), bad_sync)
                created_proxies.append(proxy)
                return proxy

            with mock.patch.object(mod.sqlite3, "connect", side_effect=fake_connect):
                with self.assertRaises(mod.MailboxError):
                    mod.open_connection(str(uninit_db))

            self.assertEqual(len(created_proxies), 1)
            self.assertTrue(created_proxies[0].closed)
            self.assertIn("PRAGMA synchronous = EXTRA", created_proxies[0].statements)
            self.assertFalse(any("CREATE TABLE" in stmt for stmt in created_proxies[0].statements))

    def run_with_dir_sync_trace(
        self,
        mod: object,
        argv: list[str],
        *,
        env: dict[str, str],
        stdin_bytes: bytes = b"",
        fail_path: str | None = None,
    ) -> tuple[int, bytes, bytes, list[str], list[tuple[str, int]], dict[int, str]]:
        real_open = os.open
        real_fsync = os.fsync
        real_close = os.close
        synced: list[str] = []
        opened: list[tuple[str, int]] = []
        open_dir_fds: dict[int, str] = {}

        def traced_open(path: object, flags: int, *args: object, **kwargs: object) -> int:
            fd = real_open(path, flags, *args, **kwargs)
            if flags & os.O_DIRECTORY:
                path_str = os.fspath(path)
                opened.append((path_str, flags))
                open_dir_fds[fd] = path_str
            return fd

        def traced_fsync(fd: int) -> None:
            dir_path = open_dir_fds.get(fd)
            if dir_path is not None:
                if fail_path is not None and dir_path == fail_path:
                    raise OSError(errno.EIO, "simulated fsync error")
                synced.append(dir_path)
            real_fsync(fd)

        def traced_close(fd: int) -> None:
            open_dir_fds.pop(fd, None)
            real_close(fd)

        with (
            mock.patch.object(mod.os, "open", side_effect=traced_open),
            mock.patch.object(mod.os, "fsync", side_effect=traced_fsync),
            mock.patch.object(mod.os, "close", side_effect=traced_close),
        ):
            rc, out, err = self.invoke_inproc(mod, argv, env=env, stdin_bytes=stdin_bytes)
        return rc, out, err, synced, opened, open_dir_fds

    def test_directory_sync_ordering_precreated_and_mutation_only(self) -> None:
        mod = self.load_mailbox_module()
        precreated_parent = self.base / "precreated_parent"
        precreated_parent.mkdir(mode=0o700)
        precreated_state = precreated_parent / "xdg_state"
        precreated_state.mkdir(mode=0o700)
        precreated_mb = precreated_state / "pi-team-mailbox"
        precreated_mb.mkdir(mode=0o700)

        expected_dirs = ["/"]
        cur = Path("/")
        for part in precreated_mb.parts[1:]:
            cur = cur / part
            expected_dirs.append(str(cur))

        env = self.make_env(xdg_state_home=str(precreated_state))

        rc, out, err, synced, opened, remaining = self.run_with_dir_sync_trace(
            mod,
            ["send", "--run", "r1", "--from", "scout", "--to", "writer", "--key", "k1"],
            env=env,
            stdin_bytes=b"hello",
        )
        self.assertEqual(rc, 0, err.decode("utf-8", "replace"))
        msg_id = json.loads(out.decode("ascii"))["id"]
        self.assertEqual(synced, expected_dirs)
        self.assertEqual([path for path, _ in opened], expected_dirs)
        self.assertEqual(remaining, {})
        for _, flags in opened:
            self.assertEqual(flags & (os.O_DIRECTORY | os.O_NOFOLLOW), os.O_DIRECTORY | os.O_NOFOLLOW)
            self.assertEqual(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT), 0)

        rc, replay_out, err, synced, opened, remaining = self.run_with_dir_sync_trace(
            mod,
            ["send", "--run", "r1", "--from", "scout", "--to", "writer", "--key", "k1"],
            env=env,
            stdin_bytes=b"hello",
        )
        self.assertEqual(rc, 0, err.decode("utf-8", "replace"))
        self.assertEqual(replay_out, out)
        self.assertEqual(synced, expected_dirs)
        self.assertEqual([path for path, _ in opened], expected_dirs)
        self.assertEqual(remaining, {})

        rc, inbox_out, err, synced, opened, remaining = self.run_with_dir_sync_trace(
            mod,
            ["inbox", "--run", "r1", "--peer", "writer"],
            env=env,
        )
        self.assertEqual(rc, 0, err.decode("utf-8", "replace"))
        self.assertEqual(len(json.loads(inbox_out.decode("ascii"))["messages"]), 1)
        self.assertEqual(synced, [])
        self.assertEqual(opened, [])
        self.assertEqual(remaining, {})

        rc, ack_out, err, synced, opened, remaining = self.run_with_dir_sync_trace(
            mod,
            ["ack", "--run", "r1", "--peer", "writer", "--id", str(msg_id)],
            env=env,
        )
        self.assertEqual(rc, 0, err.decode("utf-8", "replace"))
        self.assertEqual(synced, expected_dirs)
        self.assertEqual([path for path, _ in opened], expected_dirs)
        self.assertEqual(remaining, {})

        rc, ack_replay_out, err, synced, opened, remaining = self.run_with_dir_sync_trace(
            mod,
            ["ack", "--run", "r1", "--peer", "writer", "--id", str(msg_id)],
            env=env,
        )
        self.assertEqual(rc, 0, err.decode("utf-8", "replace"))
        self.assertEqual(ack_replay_out, ack_out)
        self.assertEqual(synced, expected_dirs)
        self.assertEqual([path for path, _ in opened], expected_dirs)
        self.assertEqual(remaining, {})

    def test_directory_fsync_failure_prevents_receipt_and_retry_remains_safe(self) -> None:
        mod = self.load_mailbox_module()
        env = self.make_env()
        mb_dir = str(self.xdg_state / "pi-team-mailbox")

        rc, out, err, _, _, remaining = self.run_with_dir_sync_trace(
            mod,
            ["send", "--run", "r-fail", "--from", "a", "--to", "b", "--key", "k1"],
            env=env,
            stdin_bytes=b"durable-payload",
            fail_path=mb_dir,
        )
        self.assertEqual(rc, 1)
        self.assertEqual(out, b"")
        err_text = err.decode("utf-8", "replace")
        self.assertTrue(err_text.startswith("error: "), err_text)
        self.assertNotIn("Traceback", err_text)
        self.assertEqual(remaining, {})

        rc, out, err, _, _, remaining = self.run_with_dir_sync_trace(
            mod,
            ["send", "--run", "r-fail", "--from", "a", "--to", "b", "--key", "k1"],
            env=env,
            stdin_bytes=b"durable-payload",
        )
        self.assertEqual(rc, 0, err.decode("utf-8", "replace"))
        msg_id = json.loads(out.decode("ascii"))["id"]
        self.assertEqual(remaining, {})

        rc, ack_out, err, _, _, remaining = self.run_with_dir_sync_trace(
            mod,
            ["ack", "--run", "r-fail", "--peer", "b", "--id", str(msg_id)],
            env=env,
            fail_path=str(self.xdg_state),
        )
        self.assertEqual(rc, 1)
        self.assertEqual(ack_out, b"")
        self.assertTrue(err.decode("utf-8", "replace").startswith("error: "))
        self.assertEqual(remaining, {})

        rc, ack_out, err, _, _, remaining = self.run_with_dir_sync_trace(
            mod,
            ["ack", "--run", "r-fail", "--peer", "b", "--id", str(msg_id)],
            env=env,
        )
        self.assertEqual(rc, 0, err.decode("utf-8", "replace"))
        ack_json = json.loads(ack_out.decode("ascii"))
        self.assertIsInstance(ack_json["acked_at"], str)
        self.assertEqual(remaining, {})

        inbox_res = self.run_cli(["inbox", "--run", "r-fail", "--peer", "b"], env=env)
        self.assertEqual(inbox_res.returncode, 0)
        inbox_json = json.loads(inbox_res.stdout.decode("ascii"))
        self.assertEqual(len(inbox_json["messages"]), 1)
        self.assertEqual(inbox_json["messages"][0]["id"], msg_id)
        self.assertEqual(inbox_json["messages"][0]["acked_at"], ack_json["acked_at"])


if __name__ == "__main__":
    unittest.main()
