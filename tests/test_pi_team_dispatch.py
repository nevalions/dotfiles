#!/usr/bin/env python3
"""Integration and fail-closed tests for pi-team-dispatch using real Git, Beads, XDG state, and bwrap."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from datetime import datetime, timedelta, timezone
import fcntl
from hashlib import sha256
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
DISPATCH_BIN = REPO_ROOT / 'pi' / '.pi' / 'agent' / 'bin' / 'pi-team-dispatch'
RUN_BIN = REPO_ROOT / 'pi' / '.pi' / 'agent' / 'bin' / 'pi-team-run'


def _load_dispatch_module():
    loader = importlib.machinery.SourceFileLoader('pi_team_dispatch_test', str(DISPATCH_BIN))
    spec = importlib.util.spec_from_loader('pi_team_dispatch_test', loader)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _check_capabilities() -> str | None:
    if not shutil.which('git'):
        return 'git CLI unavailable'
    if not shutil.which('bd'):
        return 'bd CLI unavailable'
    if not os.path.isfile('/usr/bin/bwrap') or not os.access('/usr/bin/bwrap', os.X_OK):
        return '/usr/bin/bwrap unavailable'
    mod = _load_dispatch_module()
    try:
        mod.BwrapRunner().probe_capabilities()
    except mod.DispatchError as exc:
        return f'bwrap capability unavailable: {exc}'
    return None


class PiTeamDispatchFailClosedTests(unittest.TestCase):
    """Standalone fail-closed unit tests that do not require bwrap or bd runtime capabilities."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix='pi-dispatch-unit-')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.mod = _load_dispatch_module()
        self.db_path = self.base / 'xdg-state' / 'pi-team-run' / 'state.db'
        self.state_dir = self.base / 'xdg-state' / 'pi-team-dispatch'
        self.policy_dir = self.base / 'policies'
        self.policy_dir.mkdir(mode=0o700)

        self.repo = self.base / 'repo'
        self.repo.mkdir()
        self.git_env = {
            'PATH': os.environ.get('PATH', '/usr/bin:/bin'),
            'HOME': '/nonexistent',
            'LANG': 'C.UTF-8',
            'LC_ALL': 'C.UTF-8',
            'GIT_CONFIG_NOSYSTEM': '1',
            'GIT_CONFIG_GLOBAL': '/dev/null',
            'GIT_TERMINAL_PROMPT': '0',
        }
        subprocess.run(['git', '-C', str(self.repo), 'init', '-b', 'main'], env=self.git_env, check=True, capture_output=True, timeout=15)
        subprocess.run(['git', '-C', str(self.repo), 'config', 'user.name', 'Test'], env=self.git_env, check=True, capture_output=True, timeout=15)
        subprocess.run(['git', '-C', str(self.repo), 'config', 'user.email', 'test@local.invalid'], env=self.git_env, check=True, capture_output=True, timeout=15)
        (self.repo / 'allowed.txt').write_text('initial\n', encoding='utf-8')
        subprocess.run(['git', '-C', str(self.repo), 'add', 'allowed.txt'], env=self.git_env, check=True, capture_output=True, timeout=15)
        subprocess.run(['git', '-C', str(self.repo), 'commit', '-m', 'init'], env=self.git_env, check=True, capture_output=True, timeout=15)
        self.base_sha = subprocess.run(
            ['git', '-C', str(self.repo), 'rev-parse', 'HEAD'], env=self.git_env, check=True, capture_output=True, text=True, timeout=15
        ).stdout.strip()

    def _base_policy(self) -> dict:
        return {
            'version': 1,
            'repo': str(self.repo),
            'risk_class': 'low',
            'base_sha': self.base_sha,
            'base_ref': 'main',
            'allowed_paths': ['allowed.txt'],
            'allowed_ops': ['replace'],
            'checks': [{'name': 'chk', 'argv': ['/usr/bin/true'], 'timeout_sec': 5}],
            'timeouts': {'plan_sec': 10, 'worker_sec': 10, 'review_sec': 10, 'run_sec': 30},
            'budget': {'max_attempts': 1, 'max_spend_usd': 0.0},
            'tracker': {
                'type': 'beads',
                'actor': 'disp-unit',
                'issue_allowlist': ['disp-1'],
                'required_labels': ['low-risk'],
                'require_acceptance_criteria': True,
            },
            'executor': {
                'mode': 'fake',
                'stages': {
                    'worker': {'script': 'pass'},
                    'review': {'response': {'verdict': 'pass'}},
                },
            },
        }

    def _write_raw_policy(self, name: str, raw_text: str, mode: int = 0o600) -> Path:
        p = self.policy_dir / name
        p.write_text(raw_text, encoding='utf-8')
        os.chmod(p, mode)
        return p

    def test_bwrap_probe_fails_closed_on_missing_seccomp_or_binary(self) -> None:
        with self.assertRaises(self.mod.DispatchError):
            self.mod.BwrapRunner('/nonexistent/bwrap').probe_capabilities()

        runner = self.mod.BwrapRunner('/usr/bin/python3')
        runner.seccomp_bpf = None
        with self.assertRaisesRegex(self.mod.DispatchError, 'seccomp'):
            runner.probe_capabilities()

        runner2 = self.mod.BwrapRunner('/usr/bin/python3')
        runner2.seccomp_bpf = b'\x00' * 8
        with patch.object(runner2, '_probe_once', return_value=(False, 'seccomp denied')) as m_probe:
            with self.assertRaisesRegex(self.mod.DispatchError, 'seccomp'):
                runner2.probe_capabilities()
            m_probe.assert_called_once()
            self.assertEqual(m_probe.call_args.kwargs.get('use_seccomp'), True)

    def test_pidfd_exit_requires_positive_readability_not_proc_errors(self) -> None:
        r_fd, w_fd = os.pipe()
        try:
            with self.assertRaises(self.mod.QuarantineError):
                self.mod._await_pidfd_gone(r_fd, 999999, '1', 'pid:[1]', timeout_sec=0.05)
        finally:
            os.close(r_fd)
            os.close(w_fd)

    def test_policy_rejects_bypasses_nonfinite_and_nonzero_fake_cost(self) -> None:
        bad_cases: list[tuple[str, str]] = []

        p = self._base_policy()
        p['executor'] = {'mode': 'live'}
        bad_cases.append(('live.json', json.dumps(p)))

        p = self._base_policy()
        p['tracker']['issue_allowlist'] = None
        bad_cases.append(('no_allowlist.json', json.dumps(p)))

        p = self._base_policy()
        p['tracker']['issue_allowlist'] = []
        bad_cases.append(('empty_allowlist.json', json.dumps(p)))

        p = self._base_policy()
        p['tracker']['required_labels'] = []
        bad_cases.append(('empty_labels.json', json.dumps(p)))

        p = self._base_policy()
        p['tracker']['required_labels'] = ['custom-only']
        bad_cases.append(('missing_low_risk.json', json.dumps(p)))

        p = self._base_policy()
        p['tracker']['require_acceptance_criteria'] = False
        bad_cases.append(('no_ac.json', json.dumps(p)))

        p = self._base_policy()
        p['executor']['stages']['worker'] = {'script': 'pass', 'spend_usd': 0.5}
        bad_cases.append(('nonzero_fake_cost.json', json.dumps(p)))

        p = self._base_policy()
        raw_nan = json.dumps(p).replace('"max_spend_usd": 0.0', '"max_spend_usd": NaN')
        bad_cases.append(('nan_budget.json', raw_nan))

        raw_inf = json.dumps(p).replace('"worker_sec": 10', '"worker_sec": Infinity')
        bad_cases.append(('inf_timeout.json', raw_inf))

        p = self._base_policy()
        p['allowed_ops'] = ['create']
        bad_cases.append(('unsupported_create.json', json.dumps(p)))

        p = self._base_policy()
        p['allowed_ops'] = ['delete']
        bad_cases.append(('unsupported_delete.json', json.dumps(p)))

        p = self._base_policy()
        p['allowed_paths'] = ['allowed.txt', 'b.txt', 'c.txt', 'd.txt', 'e.txt']
        bad_cases.append(('too_many_paths.json', json.dumps(p)))

        p = self._base_policy()
        p['allowed_paths'] = ['missing.txt']
        bad_cases.append(('missing_path.json', json.dumps(p)))

        p = self._base_policy()
        p['tracker']['issue_allowlist'] = ['bad,id']
        bad_cases.append(('bad_issue_id.json', json.dumps(p)))

        p = self._base_policy()
        p['tracker']['actor'] = 'a' * 65
        bad_cases.append(('actor_prefix_too_long.json', json.dumps(p)))

        raw_dup = json.dumps(self._base_policy())[:-1] + ', "version": 1}'
        bad_cases.append(('dup_key.json', raw_dup))

        for fname, raw in bad_cases:
            pol_path = self._write_raw_policy(fname, raw)
            with self.assertRaises(self.mod.DispatchError, msg=fname):
                self.mod.load_and_validate_policy(
                    str(pol_path), db_path=self.db_path, dispatch_state_dir=self.state_dir,
                )

    def test_parse_json_output_canonical_ac_allowlist_and_importer_bounds(self) -> None:
        self.assertIsNone(self.mod._parse_json_output(b'{"verdict":"pass"}', truncated=True))
        self.assertIsNone(self.mod._parse_json_output(b'{"verdict":"pass"}\n{"verdict":"pass"}'))
        self.assertIsNone(self.mod._parse_json_output(b'log line\n{"verdict":"pass"}'))
        self.assertIsNone(self.mod._parse_json_output(b'{"verdict":"changes_requested","verdict":"pass"}'))
        self.assertEqual(self.mod._parse_json_output(b'  {"verdict": "pass"}  '), {'verdict': 'pass'})

        pol = self._base_policy()
        inline_issue = {
            'id': 'disp-1',
            'status': 'open',
            'priority': 1,
            'title': 'Inline AC',
            'description': 'Fix allowed.txt\nAcceptance Criteria:   must pass checks  \r\n',
            'labels': ['low-risk'],
        }
        self.assertIsNone(self.mod._evaluate_issue_eligibility(inline_issue, pol))
        ac, err = self.mod._canonical_acceptance_criteria(inline_issue)
        self.assertIsNone(err)
        self.assertEqual(ac, 'must pass checks')
        tbd_inline = dict(inline_issue, description='Fix allowed.txt\nAcceptance Criteria: TBD\n')
        self.assertEqual(self.mod._evaluate_issue_eligibility(tbd_inline, pol), 'ambiguous_acceptance_criteria')
        empty_inline = dict(inline_issue, description='Fix allowed.txt\nAcceptance Criteria:   \n')
        self.assertEqual(self.mod._evaluate_issue_eligibility(empty_inline, pol), 'missing_acceptance_criteria')

        seen_cmds: list[list[str]] = []

        def fake_run_bd(repo_root, args, **kwargs):
            seen_cmds.append(list(args))
            self.assertNotIn('list', args[:4])
            return json.dumps([
                {'id': 'disp-other', 'priority': 0, 'status': 'open'},
                {'id': 'disp-105', 'priority': 2, 'status': 'open'},
            ])

        with patch.object(self.mod, '_run_bd', side_effect=fake_run_bd):
            got = self.mod._parse_bd_ready_allowlist(self.repo, ['disp-105', 'disp-105', 'disp-missing'])
        self.assertEqual(got, [{'id': 'disp-105', 'priority': 2, 'status': 'open'}])
        self.assertEqual(
            seen_cmds[0],
            ['--readonly', '--sandbox', 'ready', '--limit', '0', '--max-rows', '10000', '--brief', '--json'],
        )

        capped_payload = json.dumps([
            {'id': f'disp-{idx}', 'priority': 1, 'status': 'open'}
            for idx in range(self.mod.MAX_BD_READY_ROWS)
        ])
        with patch.object(self.mod, '_run_bd', return_value=capped_payload):
            with self.assertRaisesRegex(self.mod.DispatchError, 'row cap'):
                self.mod._parse_bd_ready_allowlist(self.repo, ['disp-0'])

        with patch.object(self.mod, '_run_bd', side_effect=self.mod.DispatchError('bd failed')):
            with self.assertRaisesRegex(self.mod.DispatchError, 'bd failed'):
                self.mod._parse_bd_ready_allowlist(self.repo, ['disp-105'])

        with patch.object(self.mod, '_run_bd', return_value='{"not": "a list"}'):
            with self.assertRaisesRegex(self.mod.DispatchError, 'unexpected bd ready'):
                self.mod._parse_bd_ready_allowlist(self.repo, ['disp-105'])

        # Importer counts entries before sorting and cumulative bytes before allocating.
        ws_entries = self.base / 'ws-entries'
        ws_entries.mkdir()
        (ws_entries / 'allowed.txt').write_text('initial\n', encoding='utf-8')
        for idx in range(5):
            (ws_entries / f'f{idx}.txt').write_text('x', encoding='utf-8')
        with patch.object(self.mod, 'MAX_TREE_ENTRIES', 3):
            with self.assertRaisesRegex(self.mod.DispatchError, 'excessive workspace entry count'):
                self.mod._validate_and_commit_candidate(
                    store_dir=self.repo,
                    scratch_dir=self.base,
                    run_id='r1',
                    attempt=1,
                    base_sha=self.base_sha,
                    worker_dir=ws_entries,
                    allowed_paths=['allowed.txt'],
                    allowed_ops=['replace'],
                )

        ws_bytes = self.base / 'ws-bytes'
        ws_bytes.mkdir()
        (ws_bytes / 'allowed.txt').write_text('updated\n', encoding='utf-8')
        with patch.object(self.mod, 'MAX_TOTAL_CHANGED_BYTES', 4):
            with self.assertRaisesRegex(self.mod.DispatchError, 'excess total changed bytes'):
                self.mod._validate_and_commit_candidate(
                    store_dir=self.repo,
                    scratch_dir=self.base,
                    run_id='r2',
                    attempt=1,
                    base_sha=self.base_sha,
                    worker_dir=ws_bytes,
                    allowed_paths=['allowed.txt'],
                    allowed_ops=['replace'],
                )

    def test_gitattributes_export_ignore_does_not_drift_materialized_tree(self) -> None:
        (self.repo / '.gitattributes').write_text('allowed.txt export-ignore\n', encoding='utf-8')
        subprocess.run(['git', '-C', str(self.repo), 'add', '.gitattributes'], env=self.git_env, check=True, capture_output=True, timeout=15)
        subprocess.run(['git', '-C', str(self.repo), 'commit', '-m', 'add gitattributes'], env=self.git_env, check=True, capture_output=True, timeout=15)
        sha = subprocess.run(
            ['git', '-C', str(self.repo), 'rev-parse', 'HEAD'], env=self.git_env, check=True, capture_output=True, text=True, timeout=15
        ).stdout.strip()
        dest = self.base / 'mat'
        self.mod._materialize_commit(self.repo, sha, dest)
        self.assertTrue((dest / 'allowed.txt').is_file())
        self.assertEqual((dest / 'allowed.txt').read_text(encoding='utf-8'), 'initial\n')

    def test_policy_rejects_separate_gitdir_subdirectory_and_spoofed_worktree(self) -> None:
        sub = self.repo / 'subdir'
        sub.mkdir()
        (sub / 'x.txt').write_text('x\n', encoding='utf-8')
        p_sub = self._base_policy()
        p_sub['repo'] = str(sub)
        sub_pol = self._write_raw_policy('subdir.json', json.dumps(p_sub))
        with self.assertRaisesRegex(self.mod.DispatchError, 'exact Git checkout root'):
            self.mod.load_and_validate_policy(str(sub_pol), db_path=self.db_path, dispatch_state_dir=self.state_dir)

        sep_wt = self.base / 'sep-checkout'
        sep_git = self.base / 'sep-gitdir' / '.git'
        sep_git.parent.mkdir(parents=True)
        subprocess.run(
            ['git', 'init', '-b', 'main', '--separate-git-dir', str(sep_git), str(sep_wt)],
            env=self.git_env, check=True, capture_output=True, timeout=15,
        )
        subprocess.run(['git', '-C', str(sep_wt), 'config', 'user.name', 'Test'], env=self.git_env, check=True, capture_output=True, timeout=15)
        subprocess.run(['git', '-C', str(sep_wt), 'config', 'user.email', 'test@local.invalid'], env=self.git_env, check=True, capture_output=True, timeout=15)
        (sep_wt / 'allowed.txt').write_text('initial\n', encoding='utf-8')
        subprocess.run(['git', '-C', str(sep_wt), 'add', 'allowed.txt'], env=self.git_env, check=True, capture_output=True, timeout=15)
        subprocess.run(['git', '-C', str(sep_wt), 'commit', '-m', 'init'], env=self.git_env, check=True, capture_output=True, timeout=15)
        sep_sha = subprocess.run(
            ['git', '-C', str(sep_wt), 'rev-parse', 'HEAD'], env=self.git_env, check=True, capture_output=True, text=True, timeout=15,
        ).stdout.strip()
        p_sep = self._base_policy()
        p_sep['repo'] = str(sep_wt)
        p_sep['base_sha'] = sep_sha
        sep_pol = self._write_raw_policy('sep_gitdir.json', json.dumps(p_sep))
        with self.assertRaisesRegex(
            self.mod.DispatchError,
            'separate gitdir|mismatched owning checkout|linked worktree git-dir does not belong to owning git-common-dir|readable Git',
        ):
            self.mod.load_and_validate_policy(str(sep_pol), db_path=self.db_path, dispatch_state_dir=self.state_dir)

        fake_wt = self.base / 'fake-wt'
        fake_wt.mkdir()
        (fake_wt / '.git').write_text(f'gitdir: {self.repo / ".git"}\n', encoding='utf-8')
        p_fake = self._base_policy()
        p_fake['repo'] = str(fake_wt)
        fake_pol = self._write_raw_policy('fake_wt.json', json.dumps(p_fake))
        with self.assertRaisesRegex(self.mod.DispatchError, 'linked worktree|registered'):
            self.mod.load_and_validate_policy(str(fake_pol), db_path=self.db_path, dispatch_state_dir=self.state_dir)

    def test_canonical_acceptance_criteria_multiline_and_heading_bounds(self) -> None:
        two_bullets = {
            'id': 'disp-ml',
            'status': 'open',
            'priority': 1,
            'title': 'Multiline inline AC',
            'description': (
                'Summary line\n'
                'Acceptance Criteria:\n'
                '- Criterion one: passes\n'
                '- Criterion two: keeps scope\n'
                '\n'
                '## Notes\n'
                'Trailing note outside AC\n'
            ),
            'labels': ['low-risk'],
        }
        ac, err = self.mod._canonical_acceptance_criteria(two_bullets)
        self.assertIsNone(err)
        self.assertEqual(ac, '- Criterion one: passes\n- Criterion two: keeps scope')
        self.assertIsNone(self.mod._evaluate_issue_eligibility(two_bullets, self._base_policy()))

        empty_before_heading = dict(
            two_bullets,
            description='Summary\nAcceptance Criteria:   \n## Notes\nShould not be captured\n',
        )
        ac2, err2 = self.mod._canonical_acceptance_criteria(empty_before_heading)
        self.assertIsNone(ac2)
        self.assertEqual(err2, 'missing_acceptance_criteria')

    def _seed_claiming_run(
        self,
        run_id: str,
        issue_id: str,
        actor: str,
        *,
        repo_key: str | None = None,
        dispatch_state: str = 'claiming',
        run_status: str = 'active',
        deadline_at: str | None = 'default',
    ) -> tuple[str, datetime]:
        self.mod.ensure_dispatch_dirs(self.state_dir)
        rkey = str(self.repo / '.git') if repo_key is None else repo_key
        git_dev, git_ino = self.mod._stat_git_common_dir(self.repo / '.git')
        now_dt = self.mod.utc_now()
        now_iso = self.mod.format_utc(now_dt)
        future_dt = now_dt + timedelta(seconds=60)
        db_deadline = self.mod.format_utc(future_dt) if deadline_at == 'default' else deadline_at
        with self.mod.open_dispatch_tx(self.db_path) as conn:
            for tbl in ('dispatch_stage_procs', 'dispatch_runs', 'runs'):
                conn.execute(f'DELETE FROM {tbl}')
            conn.execute(
                "INSERT INTO runs (run_id, repo_key, status, current_stage, wait_generation, commit_only, no_ci, with_deploy, with_honcho, with_wiki, created_at, updated_at) VALUES (?, ?, ?, 'admit', 0, 1, 0, 0, 0, 0, ?, ?)",
                (run_id, rkey, run_status, now_iso, now_iso),
            )
            conn.execute(
                "INSERT INTO dispatch_runs (run_id, repo_key, repo_root, beads_dir, beads_db_path, beads_dir_dev, beads_dir_ino, beads_db_dev, beads_db_ino, git_common_dir_dev, git_common_dir_ino, issue_id, actor, policy_path, policy_digest, base_sha, fingerprint, dispatch_state, attempt, max_attempts, spend_usd, max_spend_usd, deadline_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 1, 1, 1, 2, ?, ?, ?, ?, '/tmp/pol.json', '0', ?, 'fp', ?, 0, 1, 0.0, 0.0, ?, ?, ?)",
                (run_id, rkey, str(self.repo), str(self.repo / '.beads'), str(self.repo / '.beads' / 'embeddeddolt'), git_dev, git_ino, issue_id, actor, self.base_sha, dispatch_state, db_deadline, now_iso, now_iso),
            )
        return rkey, future_dt

    def test_bound_bd_claim_identity_mismatch_quarantines_without_signaling(self) -> None:
        if not hasattr(os, 'pidfd_open'):
            self.skipTest('os.pidfd_open unavailable')
        sleeper = subprocess.Popen(
            ['/usr/bin/python3', '-I', '-c', 'import time; time.sleep(30)'],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        dead_proc = subprocess.Popen(
            ['/usr/bin/python3', '-I', '-c', 'pass'],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        dead_proc.wait(timeout=5)
        beads_fd = db_fd = lock_fd = -1
        try:
            beads_fd = os.open(self.base, os.O_RDONLY | os.O_DIRECTORY)
            db_fd = os.open(self.base, os.O_RDONLY | os.O_DIRECTORY)
            lock_fd = os.open(self.base / 'bd.lock', os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            cfg_path = self.base / 'fake_bwrap_cfg.json'
            go_path = self.base / 'fake_bwrap_go.bin'
            fake_bwrap = self.base / 'fake-bwrap'
            fake_bwrap.write_text(
                '#!/usr/bin/python3 -I\n'
                'import json, os, pathlib, sys, time\n'
                'args = sys.argv[1:]\n'
                'info_fd = int(args[args.index("--info-fd") + 1])\n'
                'sec_fd = int(args[args.index("--seccomp") + 1])\n'
                'sync_fd = int(args[args.index("--sync-fd") + 1])\n'
                'os.read(sec_fd, 4096)\n'
                'os.close(sec_fd)\n'
                f'cfg = json.loads(pathlib.Path({str(cfg_path)!r}).read_text(encoding="utf-8"))\n'
                'os.write(info_fd, json.dumps(cfg["info"]).encode("utf-8"))\n'
                'os.close(info_fd)\n'
                'b = os.read(0, 1)\n'
                'if b:\n'
                f'    pathlib.Path({str(go_path)!r}).write_bytes(b)\n'
                'if cfg.get("sleep_sec"):\n'
                '    time.sleep(cfg["sleep_sec"])\n'
                'os.close(sync_fd)\n',
                encoding='utf-8',
            )
            os.chmod(fake_bwrap, 0o700)
            sleeper_ns = os.readlink(f'/proc/{sleeper.pid}/ns/pid')
            handles = {'beads_fd': beads_fd, 'db_fd': db_fd, 'bd_bin': '/usr/bin/python3'}
            seccomp_bpf = self.mod._build_seccomp_bpf() or (b'\x00' * 8)

            rkey, gate_deadline = self._seed_claiming_run('disp-id-1', 'disp-1', 'disp:t1')
            cfg_path.write_text(
                json.dumps({'info': {'child-pid': sleeper.pid, 'pid-namespace': sleeper_ns}}),
                encoding='utf-8',
            )
            with self.assertRaises(self.mod.QuarantineError):
                self.mod._run_bound_bd_claim(
                    handles=handles, bd_lock_fd=lock_fd, actor='disp:t1', issue_id='disp-1',
                    seccomp_bpf=seccomp_bpf, bwrap_bin=str(fake_bwrap), timeout=2.0,
                    db_path=self.db_path, state_dir=self.state_dir, repo_key=rkey,
                    run_id='disp-id-1', deadline_at=gate_deadline,
                )
            self.assertFalse(go_path.exists())
            self.assertIsNone(sleeper.poll(), 'host PID must never be signaled on namespace/init mismatch')

            rkey, gate_deadline = self._seed_claiming_run('disp-id-2', 'disp-1', 'disp:t2')
            cfg_path.write_text(
                json.dumps({'info': {'child-pid': sleeper.pid, 'pid-namespace': 1}}),
                encoding='utf-8',
            )
            with self.assertRaises(self.mod.QuarantineError):
                self.mod._run_bound_bd_claim(
                    handles=handles, bd_lock_fd=lock_fd, actor='disp:t2', issue_id='disp-1',
                    seccomp_bpf=seccomp_bpf, bwrap_bin=str(fake_bwrap), timeout=2.0,
                    db_path=self.db_path, state_dir=self.state_dir, repo_key=rkey,
                    run_id='disp-id-2', deadline_at=gate_deadline,
                )
            self.assertFalse(go_path.exists())
            self.assertIsNone(sleeper.poll())

            rkey, gate_deadline = self._seed_claiming_run('disp-id-3', 'disp-1', 'disp:t3')
            cfg_path.write_text(
                json.dumps({'info': {'child-pid': dead_proc.pid, 'pid-namespace': 1}}),
                encoding='utf-8',
            )
            with self.assertRaises(self.mod.QuarantineError):
                self.mod._run_bound_bd_claim(
                    handles=handles, bd_lock_fd=lock_fd, actor='disp:t3', issue_id='disp-1',
                    seccomp_bpf=seccomp_bpf, bwrap_bin=str(fake_bwrap), timeout=2.0,
                    db_path=self.db_path, state_dir=self.state_dir, repo_key=rkey,
                    run_id='disp-id-3', deadline_at=gate_deadline,
                )
            self.assertFalse(go_path.exists())

            rkey, gate_deadline = self._seed_claiming_run('disp-id-4', 'disp-1', 'disp:t4')
            cfg_path.write_text(
                json.dumps({'info': {'child-pid': sleeper.pid, 'pid-namespace': sleeper_ns}, 'sleep_sec': 1.5}),
                encoding='utf-8',
            )
            with patch.object(
                self.mod,
                '_verify_bwrap_pid1_identity',
                side_effect=lambda proc, info, **kw: (sleeper.pid, os.pidfd_open(sleeper.pid, 0), 'boot', '', ''),
            ):
                with self.assertRaises(self.mod.QuarantineError):
                    self.mod._run_bound_bd_claim(
                        handles=handles, bd_lock_fd=lock_fd, actor='disp:t4', issue_id='disp-1',
                        seccomp_bpf=seccomp_bpf, bwrap_bin=str(fake_bwrap), timeout=0.5,
                        db_path=self.db_path, state_dir=self.state_dir, repo_key=rkey,
                        run_id='disp-id-4', deadline_at=gate_deadline,
                    )
            self.assertIsNone(sleeper.poll(), 'unproven helper must not be signaled on claim timeout')
        finally:
            for fd in (beads_fd, db_fd, lock_fd):
                if fd >= 0:
                    os.close(fd)
            if sleeper.poll() is None:
                sleeper.kill()
                sleeper.wait(timeout=5)

    def test_bound_bd_claim_go_gate_refuses_missing_or_inconsistent_context(self) -> None:
        if not hasattr(os, 'pidfd_open'):
            self.skipTest('os.pidfd_open unavailable')
        beads_fd = db_fd = lock_fd = -1
        try:
            beads_fd = os.open(self.base, os.O_RDONLY | os.O_DIRECTORY)
            db_fd = os.open(self.base, os.O_RDONLY | os.O_DIRECTORY)
            lock_fd = os.open(self.base / 'bd.lock', os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            go_path = self.base / 'gate_go.bin'
            fake_bwrap = self.base / 'gate-fake-bwrap'
            fake_bwrap.write_text(
                '#!/usr/bin/python3 -I\n'
                'import json, os, pathlib, sys\n'
                'args = sys.argv[1:]\n'
                'info_fd = int(args[args.index("--info-fd") + 1])\n'
                'sec_fd = int(args[args.index("--seccomp") + 1])\n'
                'sync_fd = int(args[args.index("--sync-fd") + 1])\n'
                'os.read(sec_fd, 4096)\n'
                'os.close(sec_fd)\n'
                'os.write(info_fd, json.dumps({"child-pid": os.getpid(), "pid-namespace": 1}).encode("utf-8"))\n'
                'os.close(info_fd)\n'
                'b = os.read(0, 1)\n'
                'if b:\n'
                f'    pathlib.Path({str(go_path)!r}).write_bytes(b)\n'
                'os.close(sync_fd)\n',
                encoding='utf-8',
            )
            os.chmod(fake_bwrap, 0o700)
            handles = {'beads_fd': beads_fd, 'db_fd': db_fd, 'bd_bin': '/usr/bin/python3'}
            seccomp_bpf = self.mod._build_seccomp_bpf() or (b'\x00' * 8)
            rkey = str(self.repo / '.git')
            future_dt = self.mod.utc_now() + timedelta(seconds=60)

            with self.assertRaises(TypeError):
                self.mod._run_bound_bd_claim(
                    handles=handles, bd_lock_fd=lock_fd, actor='disp:t', issue_id='disp-1',
                    seccomp_bpf=seccomp_bpf, bwrap_bin=str(fake_bwrap),
                )

            invalid_ctx_cases = [
                {'db_path': None, 'state_dir': self.state_dir, 'repo_key': rkey, 'run_id': 'r1', 'deadline_at': future_dt},
                {'db_path': self.db_path, 'state_dir': None, 'repo_key': rkey, 'run_id': 'r1', 'deadline_at': future_dt},
                {'db_path': self.db_path, 'state_dir': self.state_dir, 'repo_key': '', 'run_id': 'r1', 'deadline_at': future_dt},
                {'db_path': self.db_path, 'state_dir': self.state_dir, 'repo_key': rkey, 'run_id': '', 'deadline_at': future_dt},
                {'db_path': self.db_path, 'state_dir': self.state_dir, 'repo_key': rkey, 'run_id': 'r1', 'deadline_at': None},
                {'db_path': self.db_path, 'state_dir': self.state_dir, 'repo_key': rkey, 'run_id': 'r1', 'deadline_at': datetime(2026, 1, 1)},
            ]
            for ctx in invalid_ctx_cases:
                with self.assertRaises(self.mod.QuarantineError):
                    self.mod._run_bound_bd_claim(
                        handles=handles, bd_lock_fd=lock_fd, actor='disp:t', issue_id='disp-1',
                        seccomp_bpf=seccomp_bpf, bwrap_bin=str(fake_bwrap), **ctx,
                    )
                with self.assertRaises(self.mod.QuarantineError):
                    self.mod._run_bound_bd_op(
                        handles=handles, bd_lock_fd=lock_fd,
                        bd_args=['--sandbox', '--actor', 'disp:t', 'update', 'disp-1', '--claim', '--json'],
                        seccomp_bpf=seccomp_bpf, bwrap_bin=str(fake_bwrap), check_go_gate=True, **ctx,
                    )
            with self.assertRaises(self.mod.QuarantineError):
                self.mod._run_bound_bd_op(
                    handles=handles, bd_lock_fd=lock_fd,
                    bd_args=['--sandbox', 'update', 'disp-1', '--claim', '--json'],
                    seccomp_bpf=seccomp_bpf, bwrap_bin=str(fake_bwrap), check_go_gate=False,
                )
            self.assertFalse(go_path.exists())

            def verify_live_child(proc, info, **kw):
                return (
                    proc.pid,
                    os.pidfd_open(proc.pid, 0),
                    'boot',
                    self.mod._read_proc_starttime(proc.pid),
                    self.mod._read_proc_ns_pid(proc.pid),
                )

            with patch.object(self.mod, '_verify_bwrap_pid1_identity', side_effect=verify_live_child):
                with self.assertRaises(self.mod.QuarantineError):
                    self.mod._run_bound_bd_claim(
                        handles=handles, bd_lock_fd=lock_fd, actor='disp:t', issue_id='disp-1',
                        seccomp_bpf=seccomp_bpf, bwrap_bin=str(fake_bwrap), timeout=2.0,
                        db_path=self.base / 'missing-state.db', state_dir=self.state_dir,
                        repo_key=rkey, run_id='missing-run', deadline_at=future_dt,
                    )
                self.assertFalse(go_path.exists())

                self._seed_claiming_run('disp-gate-1', 'disp-1', 'disp:gate')
                gate_refusals = [
                    ('missing_row', 'disp-missing', rkey, 'disp:gate', 'claiming', 'active', 'default', self.mod.QuarantineError),
                    ('wrong_state', 'disp-gate-1', rkey, 'disp:gate', 'claimed', 'active', 'default', self.mod.QuarantineError),
                    ('inactive_run', 'disp-gate-1', rkey, 'disp:gate', 'claiming', 'cancelled', 'default', self.mod.QuarantineError),
                    ('wrong_repo', 'disp-gate-1', str(self.base / 'other/.git'), 'disp:gate', 'claiming', 'active', 'default', self.mod.QuarantineError),
                    ('wrong_actor', 'disp-gate-1', rkey, 'disp:other', 'claiming', 'active', 'default', self.mod.QuarantineError),
                    ('missing_deadline', 'disp-gate-1', rkey, 'disp:gate', 'claiming', 'active', None, self.mod.QuarantineError),
                    ('bad_deadline', 'disp-gate-1', rkey, 'disp:gate', 'claiming', 'active', 'not-a-timestamp', self.mod.QuarantineError),
                    ('expired_deadline', 'disp-gate-1', rkey, 'disp:gate', 'claiming', 'active', '2000-01-01T00:00:00Z', self.mod.ClaimDeniedBeforeGoError),
                ]
                for label, call_run_id, seed_rkey, call_actor, dstate, rstat, dl_val, exc_cls in gate_refusals:
                    self._seed_claiming_run(
                        'disp-gate-1', 'disp-1', 'disp:gate',
                        repo_key=seed_rkey, dispatch_state=dstate, run_status=rstat, deadline_at=dl_val,
                    )
                    with self.assertRaises(exc_cls, msg=label):
                        self.mod._run_bound_bd_claim(
                            handles=handles, bd_lock_fd=lock_fd, actor=call_actor, issue_id='disp-1',
                            seccomp_bpf=seccomp_bpf, bwrap_bin=str(fake_bwrap), timeout=2.0,
                            db_path=self.db_path, state_dir=self.state_dir,
                            repo_key=rkey, run_id=call_run_id, deadline_at=future_dt,
                        )
                    self.assertFalse(go_path.exists(), msg=f'GO byte written for {label}')
        finally:
            for fd in (beads_fd, db_fd, lock_fd):
                if fd >= 0:
                    os.close(fd)

    def test_canonical_assignee_exact_match_and_human_id_preservation(self) -> None:
        pol = self._base_policy()
        actor = 'disp-unit:disp-run-1'
        base_issue = {
            'id': 'disp-1',
            'status': 'in_progress',
            'title': 'Exact actor check',
            'description': 'Fix allowed.txt\nAcceptance Criteria: exact check\n',
            'labels': ['low-risk'],
        }

        self.assertEqual(self.mod._extract_verified_issue_state(dict(base_issue, assignee=None), 'disp-1'), ('in_progress', ''))
        self.assertEqual(self.mod._extract_verified_issue_state(dict(base_issue, assignee=''), 'disp-1'), ('in_progress', ''))
        self.assertEqual(self.mod._extract_verified_issue_state(dict(base_issue, assignee=actor), 'disp-1'), ('in_progress', actor))
        self.assertEqual(
            self.mod._extract_verified_issue_state(dict(base_issue, assignee='Alice Smith'), 'disp-1'),
            ('in_progress', 'Alice Smith'),
        )
        self.assertEqual(
            self.mod._extract_verified_issue_state(dict(base_issue, assignee='human.owner@local'), 'disp-1'),
            ('in_progress', 'human.owner@local'),
        )
        self.assertIsNone(self.mod._evaluate_claimed_issue_eligibility(dict(base_issue, assignee=actor), pol, actor))
        for human_id in ('Alice Smith', 'human.owner@local', 'other-owner', None, ''):
            self.assertEqual(
                self.mod._evaluate_claimed_issue_eligibility(dict(base_issue, assignee=human_id), pol, actor),
                'ownership_mismatch',
                msg=repr(human_id),
            )
        self.assertEqual(
            self.mod._evaluate_claimed_issue_eligibility(dict(base_issue, status='open', assignee='Alice Smith'), pol, actor),
            'status_not_in_progress:open',
        )
        self.assertEqual(
            self.mod._evaluate_claimed_issue_eligibility(dict(base_issue, status='open', assignee=actor), pol, actor),
            'tracker_revalidation_failed',
        )
        for bad_assignee in (f'{actor} ', f' {actor}', f'{actor}\n', ' ', '\t', ' alice ', 123):
            bad_issue = dict(base_issue, assignee=bad_assignee)
            self.assertIsNone(self.mod._extract_verified_issue_state(bad_issue, 'disp-1'), msg=repr(bad_assignee))
            self.assertEqual(
                self.mod._evaluate_claimed_issue_eligibility(bad_issue, pol, actor),
                'tracker_revalidation_failed',
                msg=repr(bad_assignee),
            )

    def test_policy_selector_rejects_parent_traversal_and_stop_selectors_mutually_exclusive(self) -> None:
        valid_pol = self._write_raw_policy('valid.json', json.dumps(self._base_policy()))
        sub_dir = self.policy_dir / 'sub'
        sub_dir.mkdir(mode=0o700)
        rel_pol = sub_dir / 'rel.json'
        rel_pol.write_bytes(valid_pol.read_bytes())
        os.chmod(rel_pol, 0o600)
        dotdot_name_pol = sub_dir / 'dot..name.json'
        dotdot_name_pol.write_bytes(valid_pol.read_bytes())
        os.chmod(dotdot_name_pol, 0o600)
        sym_link = self.policy_dir / 'link'
        sym_link.symlink_to(sub_dir)

        self.assertIn(str(valid_pol), self.mod._policy_path_lookup_keys(str(valid_pol)))
        self.assertIn(str(dotdot_name_pol), self.mod._policy_path_lookup_keys(str(dotdot_name_pol)))

        old_cwd = os.getcwd()
        try:
            os.chdir(self.policy_dir)
            self.assertIn(str(valid_pol), self.mod._policy_path_lookup_keys('valid.json'))
            self.assertIn(str(rel_pol), self.mod._policy_path_lookup_keys('./sub/rel.json'))
            for bad_sel in (
                'link/../valid.json',
                '../policies/valid.json',
                './../policies/valid.json',
                '..',
                str(self.policy_dir / 'link' / '..' / 'valid.json'),
            ):
                with self.assertRaisesRegex(self.mod.DispatchError, r'\.\.', msg=bad_sel):
                    self.mod._policy_path_lookup_keys(bad_sel)
                with self.assertRaisesRegex(self.mod.DispatchError, r'\.\.', msg=bad_sel):
                    self.mod._normalize_policy_path(bad_sel)
                with self.assertRaisesRegex(self.mod.DispatchError, r'\.\.', msg=bad_sel):
                    self.mod._resolve_policy_identity(
                        bad_sel, db_path=self.db_path, dispatch_state_dir=self.state_dir,
                    )
        finally:
            os.chdir(old_cwd)

        parser = self.mod.build_parser()
        for ok_argv in (
            ['stop', '--run-id', 'r1'],
            ['stop', '--repo', '/tmp/r'],
            ['stop', '--policy', str(valid_pol), '--policy-sha256', '0' * 64],
            ['revoke', '--run-id', 'r1', '--reason', 'halt'],
        ):
            parsed = parser.parse_args(ok_argv)
            self.assertIn(parsed.command, ('stop', 'revoke'))

        for bad_argv in (
            ['stop'],
            ['revoke'],
            ['stop', '--run-id', 'r1', '--repo', '/tmp/r'],
            ['stop', '--run-id', 'r1', '--policy', str(valid_pol)],
            ['revoke', '--repo', '/tmp/r', '--policy', str(valid_pol)],
            ['stop', '--run-id', 'r1', '--repo', '/tmp/r', '--policy', str(valid_pol)],
        ):
            with self.assertRaises(SystemExit, msg=repr(bad_argv)) as ctx:
                parser.parse_args(bad_argv)
            self.assertEqual(ctx.exception.code, 2, msg=repr(bad_argv))

        isolated_xdg = self.base / 'xdg-unit-stop'
        with patch.dict(os.environ, {'XDG_STATE_HOME': str(isolated_xdg)}, clear=True):
            for bad_ns in (
                SimpleNamespace(run_id='r1', repo=str(self.repo), policy=None, policy_sha256=None, reason='mix'),
                SimpleNamespace(run_id='r1', repo=None, policy=str(valid_pol), policy_sha256=None, reason='mix'),
                SimpleNamespace(run_id=None, repo=str(self.repo), policy=str(valid_pol), policy_sha256=None, reason='mix'),
                SimpleNamespace(run_id=None, repo=None, policy=None, policy_sha256=None, reason='none'),
            ):
                with self.assertRaisesRegex(self.mod.DispatchError, 'mutually exclusive|requires'):
                    self.mod.cmd_stop(bad_ns)
        self.assertFalse(isolated_xdg.exists())


class PiTeamDispatchTests(unittest.TestCase):
    """Real-tool offline dispatcher integration suite."""

    def setUp(self) -> None:
        reason = _check_capabilities()
        if reason is not None:
            self.skipTest(reason)

        self.tmp = tempfile.TemporaryDirectory(prefix='pi-dispatch-test-')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.home_dir = self.base / 'home'
        self.xdg_config = self.base / 'xdg-config'
        self.xdg_data = self.base / 'xdg-data'
        self.xdg_cache = self.base / 'xdg-cache'
        self.xdg_state = self.base / 'xdg-state'
        self.tmp_dir = self.base / 'tmp'
        for d in (self.home_dir, self.xdg_config, self.xdg_data, self.xdg_cache, self.xdg_state, self.tmp_dir):
            d.mkdir(mode=0o700)

        self.policy_dir = self.base / 'policies'
        self.policy_dir.mkdir(mode=0o700)
        self.repo = self.base / 'repo'
        self.repo.mkdir()
        self.worktree = self.base / 'repo-wt'

        self.env = self._build_clean_env()
        self._git(self.repo, 'init', '-b', 'main')
        self._git(self.repo, 'config', 'user.name', 'Test User')
        self._git(self.repo, 'config', 'user.email', 'test@local.invalid')
        (self.repo / 'allowed.txt').write_text('initial\n', encoding='utf-8')
        (self.repo / 'other.txt').write_text('other\n', encoding='utf-8')
        self._git(self.repo, 'add', 'allowed.txt', 'other.txt')
        self._git(self.repo, 'commit', '-m', 'initial commit')
        self.base_sha = self._git(self.repo, 'rev-parse', 'HEAD').stdout.strip()
        self._git(self.repo, 'worktree', 'add', str(self.worktree), '-b', 'wt-branch')

        init_bd = self._bd(self.repo, 'init', '--sandbox', '--stealth', '--skip-agents', '--skip-hooks', '--prefix', 'disp')
        self.assertEqual(init_bd.returncode, 0, msg=f'bd init failed: {init_bd.stderr}\n{init_bd.stdout}')
        self.assertEqual(self._git(self.repo, 'rev-parse', 'HEAD').stdout.strip(), self.base_sha)

    def _build_clean_env(self) -> dict[str, str]:
        return {
            'PATH': os.environ.get('PATH', '/usr/bin:/bin'),
            'USER': os.environ.get('USER', 'disp-test'),
            'HOME': str(self.home_dir),
            'XDG_CONFIG_HOME': str(self.xdg_config),
            'XDG_DATA_HOME': str(self.xdg_data),
            'XDG_CACHE_HOME': str(self.xdg_cache),
            'XDG_STATE_HOME': str(self.xdg_state),
            'TMPDIR': str(self.tmp_dir),
            'LANG': 'C.UTF-8',
            'LC_ALL': 'C.UTF-8',
            'DO_NOT_TRACK': '1',
            'GIT_CONFIG_NOSYSTEM': '1',
            'GIT_CONFIG_GLOBAL': '/dev/null',
            'GIT_TERMINAL_PROMPT': '0',
            'GIT_ATTR_NOSYSTEM': '1',
            'GIT_NO_REPLACE_OBJECTS': '1',
        }

    def _git(self, cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
        proc = subprocess.run(
            ['git', '-C', str(cwd), *args],
            env=self.env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, msg=f'git {args} failed: {proc.stderr}')
        return proc

    def _bd(self, cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ['bd', *args],
            cwd=str(cwd),
            env=self.env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

    def _create_issue(
        self,
        title: str,
        *,
        priority: int = 1,
        acceptance: str = 'allowed.txt updated cleanly',
        description: str = 'Update allowed.txt',
        labels: str = 'low-risk',
    ) -> str:
        cmd = ['--sandbox', 'create', title, '-d', description, '-p', str(priority), '--json']
        if acceptance:
            cmd.extend(['--acceptance', acceptance])
        if labels:
            cmd.extend(['-l', labels])
        proc = self._bd(self.repo, *cmd)
        self.assertEqual(proc.returncode, 0, msg=f'bd create failed: {proc.stderr}\n{proc.stdout}')
        data = json.loads(proc.stdout)
        if isinstance(data, list):
            data = data[0]
        return data['id']

    def _show_issue(self, issue_id: str) -> dict:
        proc = self._bd(self.repo, '--readonly', '--sandbox', 'show', issue_id, '--json')
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        data = json.loads(proc.stdout)
        return data[0] if isinstance(data, list) else data

    def _write_policy(
        self,
        name: str = 'policy.json',
        *,
        repo: Path | None = None,
        actor: str = 'disp-test',
        issue_allowlist: list[str] | None = None,
        plan_script: str | None = None,
        worker_script: str | None = None,
        review_script: str | None = None,
        checks: list[dict] | None = None,
        max_attempts: int = 2,
        run_sec: float = 60,
        allowed_ops: list[str] | None = None,
        mode: int = 0o600,
        executor_override: dict | None = None,
    ) -> Path:
        if worker_script is None:
            worker_script = (
                'from pathlib import Path\n'
                'Path("/workspace/allowed.txt").write_text("updated\\n", encoding="utf-8")\n'
            )
        if review_script is None:
            review_script = (
                'import json, os\n'
                'with open(os.environ["DISPATCH_INPUT"], encoding="utf-8") as f:\n'
                '    inp = json.load(f)\n'
                'print(json.dumps({\n'
                '    "issue_id": inp["issue_id"],\n'
                '    "run_id": inp["run_id"],\n'
                '    "attempt": inp["attempt"],\n'
                '    "candidate_sha": inp["candidate_sha"],\n'
                '    "verdict": "pass",\n'
                '    "findings": [],\n'
                '    "evidence_refs": [f"check:{c[\'name\']}" for c in inp["checks"]],\n'
                '}))\n'
            )
        if checks is None:
            checks = [{
                'name': 'verify-allowed',
                'argv': ['/usr/bin/python3', '-I', '-c',
                         'from pathlib import Path; assert Path("/workspace/allowed.txt").read_text() == "updated\\n"'],
                'timeout_sec': 10,
            }]
        stages: dict = {
            'worker': {'script': worker_script},
            'review': {'script': review_script},
        }
        if plan_script is not None:
            stages['plan'] = {'script': plan_script}
        policy = {
            'version': 1,
            'repo': str(repo or self.repo),
            'risk_class': 'low',
            'base_sha': self.base_sha,
            'base_ref': 'main',
            'allowed_paths': ['allowed.txt'],
            'allowed_ops': allowed_ops or ['replace'],
            'checks': checks,
            'timeouts': {'plan_sec': 15, 'worker_sec': 15, 'review_sec': 15, 'run_sec': run_sec},
            'budget': {'max_attempts': max_attempts, 'max_spend_usd': 0.0},
            'tracker': {
                'type': 'beads',
                'actor': actor,
                'issue_allowlist': issue_allowlist if issue_allowlist is not None else ['disp-placeholder'],
                'required_labels': ['low-risk'],
                'require_acceptance_criteria': True,
            },
            'executor': executor_override if executor_override is not None else {
                'mode': 'fake',
                'stages': stages,
            },
        }
        p = self.policy_dir / name
        p.write_text(json.dumps(policy, indent=2), encoding='utf-8')
        os.chmod(p, mode)
        return p

    def _run_dispatch(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(DISPATCH_BIN), *args],
            env=self.env,
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )

    def _run_ledger(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(RUN_BIN), *args],
            env=self.env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

    def _seed_git_pin(self, common_dir: Path | str | None = None) -> tuple[int, int]:
        st = os.stat(Path(common_dir or (self.repo / '.git')), follow_symlinks=False)
        return int(st.st_dev), int(st.st_ino)

    def test_success_and_no_redispatch_and_interactive_refusal(self) -> None:
        issue_id = self._create_issue('Fix allowed file')
        policy_path = self._write_policy(issue_allowlist=[issue_id])

        res = self._run_dispatch('tick', '--policy', str(policy_path), '--json')
        self.assertEqual(res.returncode, 0, msg=res.stderr + res.stdout)
        rep = json.loads(res.stdout)
        self.assertEqual(rep['outcome'], 'candidate_ready')
        self.assertEqual(rep['issue_id'], issue_id)
        self.assertEqual(rep['base_sha'], self.base_sha)
        self.assertEqual(rep['spend_usd'], 0.0)
        self.assertTrue(rep['checks'][0]['passed'])
        self.assertEqual(rep['review']['verdict'], 'pass')
        self.assertEqual(rep['review']['check_ids'], ['verify-allowed'])
        self.assertNotIn('findings', rep['review'])
        self.assertNotIn('evidence_refs', rep['review'])

        store_dir = Path(rep['git_store'])
        parent = subprocess.run(
            ['git', '-C', str(store_dir), 'rev-parse', f'{rep["candidate_sha"]}^1'],
            env=self.env, capture_output=True, text=True, timeout=15, check=True,
        ).stdout.strip()
        self.assertEqual(parent, self.base_sha)
        blob = subprocess.run(
            ['git', '-C', str(store_dir), 'show', f'{rep["candidate_sha"]}:allowed.txt'],
            env=self.env, capture_output=True, text=True, timeout=15, check=True,
        ).stdout
        self.assertEqual(blob, 'updated\n')

        self.assertEqual(self._git(self.repo, 'status', '--porcelain').stdout.strip(), '')
        self.assertEqual((self.repo / 'allowed.txt').read_text(encoding='utf-8'), 'initial\n')

        issue = self._show_issue(issue_id)
        self.assertEqual(issue['status'], 'in_progress')
        self.assertEqual(issue['assignee'], rep['actor'])

        refuse_wait = self._run_ledger('wait', rep['run_id'], 'admit', '--target', 'user')
        self.assertNotEqual(refuse_wait.returncode, 0)
        refuse_ckpt = self._run_ledger('checkpoint', rep['run_id'], 'admit', '--evidence', 'x')
        self.assertNotEqual(refuse_ckpt.returncode, 0)
        refuse_cancel = self._run_ledger('cancel', rep['run_id'], 'admit')
        self.assertNotEqual(refuse_cancel.returncode, 0)

        again = self._run_dispatch('tick', '--policy', str(policy_path), '--json')
        self.assertEqual(again.returncode, 0, msg=again.stderr + again.stdout)
        self.assertEqual(json.loads(again.stdout)['outcome'], 'no_work')

        max_prefix = 'a' * 64
        max_issue = self._create_issue('Max actor prefix claim')
        max_pol = self._write_policy('max_actor.json', actor=max_prefix, issue_allowlist=[max_issue])
        max_res = self._run_dispatch('tick', '--policy', str(max_pol), '--json')
        self.assertEqual(max_res.returncode, 0, msg=max_res.stderr + max_res.stdout)
        max_rep = json.loads(max_res.stdout)
        self.assertEqual(max_rep['outcome'], 'candidate_ready')
        self.assertTrue(max_rep['actor'].startswith(f'{max_prefix}:disp-'))
        self.assertGreater(len(max_rep['actor']), 64)
        self.assertEqual(self._show_issue(max_issue)['assignee'], max_rep['actor'])

    def _snapshot_tree(self, root: Path) -> list[tuple[str, bool, int | None, str | None]]:
        if not root.exists():
            return []
        entries: list[tuple[str, bool, int | None, str | None]] = []
        for p in sorted(root.rglob('*')):
            rel = str(p.relative_to(root))
            if p.is_dir() and not p.is_symlink():
                entries.append((rel, True, None, None))
            elif p.is_file() and not p.is_symlink():
                data = p.read_bytes()
                entries.append((rel, False, len(data), sha256(data).hexdigest()))
            else:
                entries.append((rel, False, None, 'other'))
        return entries

    def test_dry_run_read_only_no_side_effects(self) -> None:
        i2 = self._create_issue('Second', priority=2)
        i1 = self._create_issue('First', priority=1)
        policy_path = self._write_policy(issue_allowlist=[i1, i2])

        before_xdg = self._snapshot_tree(self.xdg_state)
        self.assertEqual(before_xdg, [])
        before_worktrees = self._git(self.repo, 'worktree', 'list', '--porcelain').stdout
        before_head = self._git(self.repo, 'rev-parse', 'HEAD').stdout
        before_status = self._git(self.repo, 'status', '--porcelain').stdout
        before_allowed = (self.repo / 'allowed.txt').read_text(encoding='utf-8')
        before_other = (self.repo / 'other.txt').read_text(encoding='utf-8')

        res = self._run_dispatch('dry-run', '--policy', str(policy_path), '--json')
        self.assertEqual(res.returncode, 0, msg=res.stderr + res.stdout)
        rep = json.loads(res.stdout)
        self.assertEqual(rep['outcome'], 'selected')
        self.assertEqual(rep['issue_id'], i1)
        self.assertEqual(self._snapshot_tree(self.xdg_state), before_xdg)
        self.assertFalse((self.xdg_state / 'pi-team-run').exists())
        self.assertFalse((self.xdg_state / 'pi-team-dispatch').exists())
        self.assertEqual(self._git(self.repo, 'worktree', 'list', '--porcelain').stdout, before_worktrees)
        self.assertEqual(self._git(self.repo, 'rev-parse', 'HEAD').stdout, before_head)
        self.assertEqual(self._git(self.repo, 'status', '--porcelain').stdout, before_status)
        self.assertEqual((self.repo / 'allowed.txt').read_text(encoding='utf-8'), before_allowed)
        self.assertEqual((self.repo / 'other.txt').read_text(encoding='utf-8'), before_other)
        for iid in (i1, i2):
            issue = self._show_issue(iid)
            self.assertEqual(issue['status'], 'open')
            self.assertEqual((issue.get('assignee') or '').strip(), '')

        stop_res = self._run_dispatch('stop', '--policy', str(policy_path), '--reason', 'halt dry-run', '--json')
        self.assertEqual(stop_res.returncode, 0, msg=stop_res.stderr + stop_res.stdout)
        after_stop_xdg = self._snapshot_tree(self.xdg_state)
        self.assertFalse((self.xdg_state / 'pi-team-run').exists())

        stopped_dry = self._run_dispatch('dry-run', '--policy', str(policy_path), '--json')
        self.assertEqual(stopped_dry.returncode, 0, msg=stopped_dry.stderr + stopped_dry.stdout)
        rep_stop = json.loads(stopped_dry.stdout)
        self.assertEqual(rep_stop['outcome'], 'cancelled')
        self.assertEqual(rep_stop['reason'], 'repo_stop_marker_active')
        self.assertIsNone(rep_stop.get('issue_id'))
        self.assertEqual(self._snapshot_tree(self.xdg_state), after_stop_xdg)
        self.assertFalse((self.xdg_state / 'pi-team-run').exists())
        self.assertEqual(self._git(self.repo, 'worktree', 'list', '--porcelain').stdout, before_worktrees)
        self.assertEqual(self._git(self.repo, 'rev-parse', 'HEAD').stdout, before_head)
        self.assertEqual(self._git(self.repo, 'status', '--porcelain').stdout, before_status)
        for iid in (i1, i2):
            issue = self._show_issue(iid)
            self.assertEqual(issue['status'], 'open')
            self.assertEqual((issue.get('assignee') or '').strip(), '')

        beads_path = self.repo / '.beads'
        beads_bak = self.base / 'dry_run_beads_bak'
        beads_path.rename(beads_bak)
        try:
            stopped_no_beads = self._run_dispatch('dry-run', '--policy', str(policy_path), '--json')
            self.assertEqual(stopped_no_beads.returncode, 0, msg=stopped_no_beads.stderr + stopped_no_beads.stdout)
            self.assertEqual(json.loads(stopped_no_beads.stdout)['reason'], 'repo_stop_marker_active')
        finally:
            beads_bak.rename(beads_path)
        self.assertEqual(self._snapshot_tree(self.xdg_state), after_stop_xdg)

        started = self._run_ledger('start', str(self.repo), '--json')
        self.assertEqual(started.returncode, 0, msg=started.stderr + started.stdout)
        int_run_id = json.loads(started.stdout)['run_id']
        beads_path.rename(beads_bak)
        try:
            int_dry = self._run_dispatch('dry-run', '--policy', str(policy_path), '--json')
            self.assertEqual(int_dry.returncode, 0, msg=int_dry.stderr + int_dry.stdout)
            self.assertEqual(json.loads(int_dry.stdout)['reason'], 'interactive_run_active')
        finally:
            beads_bak.rename(beads_path)
        self.assertEqual(self._run_ledger('cancel', int_run_id, 'admit', '--json').returncode, 0)

    def test_linked_worktree_race_and_manual_interactive_reservation_race(self) -> None:
        i1 = self._create_issue('Linked race')
        p_main = self._write_policy('main.json', repo=self.repo, issue_allowlist=[i1])
        p_wt = self._write_policy('wt.json', repo=self.worktree, issue_allowlist=[i1])

        with ThreadPoolExecutor(max_workers=2) as pool:
            f1 = pool.submit(self._run_dispatch, 'tick', '--policy', str(p_main), '--json')
            f2 = pool.submit(self._run_dispatch, 'tick', '--policy', str(p_wt), '--json')
            r1, r2 = f1.result(), f2.result()

        reps = [json.loads(r1.stdout), json.loads(r2.stdout)]
        outcomes = [r['outcome'] for r in reps]
        self.assertEqual(outcomes.count('candidate_ready'), 1, msg=reps)
        winner = next(r for r in reps if r['outcome'] == 'candidate_ready')

        db_path = self.xdg_state / 'pi-team-run' / 'state.db'
        with closing(sqlite3.connect(f'{db_path.resolve().as_uri()}?mode=ro', uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            run_rows = conn.execute('SELECT * FROM dispatch_runs WHERE issue_id = ?', (i1,)).fetchall()
            self.assertEqual(len(run_rows), 1)
            self.assertEqual(run_rows[0]['run_id'], winner['run_id'])
            worker_rows = conn.execute(
                "SELECT * FROM dispatch_stage_procs WHERE run_id = ? AND stage = 'worker'",
                (winner['run_id'],),
            ).fetchall()
            self.assertEqual(len(worker_rows), 1)
        issue_state = self._show_issue(i1)
        self.assertEqual(issue_state['status'], 'in_progress')
        self.assertEqual(issue_state['assignee'], winner['actor'])

        i2 = self._create_issue('Interactive blocks dispatch')
        p2 = self._write_policy('p2.json', repo=self.repo, issue_allowlist=[i2])
        start_wt = self._run_ledger('start', str(self.worktree), '--json')
        self.assertEqual(start_wt.returncode, 0, msg=start_wt.stderr)
        dup_main = self._run_ledger('start', str(self.repo), '--json')
        self.assertNotEqual(dup_main.returncode, 0)

        blocked = self._run_dispatch('tick', '--policy', str(p2), '--json')
        self.assertNotEqual(blocked.returncode, 0)
        self.assertEqual(json.loads(blocked.stdout)['outcome'], 'blocked')
        self.assertEqual(json.loads(blocked.stdout)['reason'], 'interactive_run_active')
        self.assertEqual(self._show_issue(i2)['status'], 'open')

    def test_crash_after_claim_before_ack_reconciles_without_duplicate_work(self) -> None:
        issue_id = self._create_issue('Crash after claim')
        policy_path = self._write_policy(issue_allowlist=[issue_id])

        crash_wrapper = (
            'import importlib.machinery, importlib.util, os, sys\n'
            'loader = importlib.machinery.SourceFileLoader("pi_team_dispatch_cli", sys.argv[1])\n'
            'spec = importlib.util.spec_from_loader("pi_team_dispatch_cli", loader)\n'
            'mod = importlib.util.module_from_spec(spec)\n'
            'spec.loader.exec_module(mod)\n'
            'orig_bound_claim = mod._run_bound_bd_claim\n'
            'def wrapped_bound_claim(**kwargs):\n'
            '    out = orig_bound_claim(**kwargs)\n'
            '    os._exit(99)\n'
            'mod._run_bound_bd_claim = wrapped_bound_claim\n'
            'sys.exit(mod.main(["tick", "--policy", sys.argv[2], "--json"]))\n'
        )
        crash_proc = subprocess.run(
            [sys.executable, '-c', crash_wrapper, str(DISPATCH_BIN), str(policy_path)],
            env=self.env, capture_output=True, text=True, timeout=30, check=False,
        )
        self.assertEqual(crash_proc.returncode, 99, msg=crash_proc.stderr + crash_proc.stdout)

        db_path = self.xdg_state / 'pi-team-run' / 'state.db'
        with closing(sqlite3.connect(f'{db_path.resolve().as_uri()}?mode=ro', uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            drows = conn.execute('SELECT * FROM dispatch_runs').fetchall()
            self.assertEqual(len(drows), 1)
            drow = drows[0]
            self.assertEqual(drow['dispatch_state'], 'claiming')
            self.assertEqual(drow['attempt'], 0)
            run_id = drow['run_id']
            actor = drow['actor']
            self.assertTrue(actor.endswith(f':{run_id}'))
            stage_count = conn.execute('SELECT count(*) FROM dispatch_stage_procs').fetchone()[0]
            self.assertEqual(stage_count, 0)

        claimed_issue = self._show_issue(issue_id)
        self.assertEqual(claimed_issue['status'], 'in_progress')
        self.assertEqual(claimed_issue['assignee'], actor)

        journal_file = self.base / 'bd-restart-journal.jsonl'
        restart_wrapper = (
            'import importlib.machinery, importlib.util, json, sys\n'
            'loader = importlib.machinery.SourceFileLoader("pi_team_dispatch_cli", sys.argv[1])\n'
            'spec = importlib.util.spec_from_loader("pi_team_dispatch_cli", loader)\n'
            'mod = importlib.util.module_from_spec(spec)\n'
            'spec.loader.exec_module(mod)\n'
            'orig_run_bd = mod._run_bd\n'
            'orig_bound_claim = mod._run_bound_bd_claim\n'
            'jpath = sys.argv[3]\n'
            'def logged_run_bd(repo_root, args, **kwargs):\n'
            '    with open(jpath, "a", encoding="utf-8") as jf:\n'
            '        jf.write(json.dumps(list(args)) + "\\n")\n'
            '    return orig_run_bd(repo_root, args, **kwargs)\n'
            'def logged_bound_claim(**kwargs):\n'
            '    with open(jpath, "a", encoding="utf-8") as jf:\n'
            '        jf.write(json.dumps(["bound_claim", kwargs.get("issue_id")]) + "\\n")\n'
            '    return orig_bound_claim(**kwargs)\n'
            'mod._run_bd = logged_run_bd\n'
            'mod._run_bound_bd_claim = logged_bound_claim\n'
            'sys.exit(mod.main(["tick", "--policy", sys.argv[2], "--json"]))\n'
        )
        res = subprocess.run(
            [sys.executable, '-c', restart_wrapper, str(DISPATCH_BIN), str(policy_path), str(journal_file)],
            env=self.env, capture_output=True, text=True, timeout=45, check=False,
        )
        self.assertEqual(res.returncode, 0, msg=res.stderr + res.stdout)
        rep = json.loads(res.stdout)
        self.assertEqual(rep['run_id'], run_id)
        self.assertEqual(rep['outcome'], 'candidate_ready')
        self.assertEqual(rep['attempt'], 1)

        bd_calls = [json.loads(line) for line in journal_file.read_text(encoding='utf-8').splitlines() if line.strip()]
        self.assertFalse(any('--claim' in call or call[0] == 'bound_claim' for call in bd_calls), msg=f'unexpected re-claim: {bd_calls}')

        with closing(sqlite3.connect(f'{db_path.resolve().as_uri()}?mode=ro', uri=True)) as conn:
            worker_rows = conn.execute(
                "SELECT * FROM dispatch_stage_procs WHERE run_id = ? AND stage = 'worker'",
                (run_id,),
            ).fetchall()
            self.assertEqual(len(worker_rows), 1)

    def test_ambiguous_claim_reconciles_exact_owner_and_blocks_failed_claim(self) -> None:
        i1 = self._create_issue('Ambiguous claim succeeds in bd')
        p1 = self._write_policy('ambig1.json', issue_allowlist=[i1])
        ambig_wrapper = (
            'import importlib.machinery, importlib.util, json, sys\n'
            'loader = importlib.machinery.SourceFileLoader("pi_team_dispatch_cli", sys.argv[1])\n'
            'spec = importlib.util.spec_from_loader("pi_team_dispatch_cli", loader)\n'
            'mod = importlib.util.module_from_spec(spec)\n'
            'spec.loader.exec_module(mod)\n'
            'orig_run_bd = mod._run_bd\n'
            'orig_bound_readonly = mod._run_bound_bd_readonly\n'
            'orig_bound_claim = mod._run_bound_bd_claim\n'
            'jpath = sys.argv[3]\n'
            'def ambig_run_bd(repo_root, args, **kwargs):\n'
            '    with open(jpath, "a", encoding="utf-8") as jf:\n'
            '        jf.write(json.dumps(list(args)) + "\\n")\n'
            '    return orig_run_bd(repo_root, args, **kwargs)\n'
            'def ambig_bound_readonly(**kwargs):\n'
            '    with open(jpath, "a", encoding="utf-8") as jf:\n'
            '        jf.write(json.dumps(["bound_readonly", kwargs.get("subcommand"), kwargs.get("issue_id")]) + "\\n")\n'
            '    return orig_bound_readonly(**kwargs)\n'
            'def ambig_bound_claim(**kwargs):\n'
            '    orig_bound_claim(**kwargs)\n'
            '    with open(jpath, "a", encoding="utf-8") as jf:\n'
            '        jf.write(json.dumps(["bound_claim", kwargs.get("issue_id")]) + "\\n")\n'
            '    raise mod.DispatchError("simulated bd timeout after claim commit")\n'
            'mod._run_bd = ambig_run_bd\n'
            'mod._run_bound_bd_readonly = ambig_bound_readonly\n'
            'mod._run_bound_bd_claim = ambig_bound_claim\n'
            'sys.exit(mod.main(["tick", "--policy", sys.argv[2], "--json"]))\n'
        )
        j1 = self.base / 'ambig1.jsonl'
        r1 = subprocess.run(
            [sys.executable, '-c', ambig_wrapper, str(DISPATCH_BIN), str(p1), str(j1)],
            env=self.env, capture_output=True, text=True, timeout=45, check=False,
        )
        self.assertEqual(r1.returncode, 0, msg=r1.stderr + r1.stdout)
        rep1 = json.loads(r1.stdout)
        self.assertEqual(rep1['outcome'], 'candidate_ready')
        calls1 = [json.loads(line) for line in j1.read_text(encoding='utf-8').splitlines() if line.strip()]
        self.assertEqual(sum(1 for c in calls1 if c[0] == 'bound_claim'), 1)
        self.assertFalse(any('--claim' in c for c in calls1))

        i2 = self._create_issue('Ambiguous claim failed before commit')
        p2 = self._write_policy('ambig2.json', issue_allowlist=[i2])
        fail_wrapper = (
            'import importlib.machinery, importlib.util, sys\n'
            'loader = importlib.machinery.SourceFileLoader("pi_team_dispatch_cli", sys.argv[1])\n'
            'spec = importlib.util.spec_from_loader("pi_team_dispatch_cli", loader)\n'
            'mod = importlib.util.module_from_spec(spec)\n'
            'spec.loader.exec_module(mod)\n'
            'def fail_bound_claim(**kwargs):\n'
            '    raise mod.DispatchError("bd command failed before mutating")\n'
            'mod._run_bound_bd_claim = fail_bound_claim\n'
            'sys.exit(mod.main(["tick", "--policy", sys.argv[2], "--json"]))\n'
        )
        r2 = subprocess.run(
            [sys.executable, '-c', fail_wrapper, str(DISPATCH_BIN), str(p2)],
            env=self.env, capture_output=True, text=True, timeout=30, check=False,
        )
        self.assertNotEqual(r2.returncode, 0)
        rep2 = json.loads(r2.stdout)
        self.assertEqual(rep2['outcome'], 'blocked')
        self.assertEqual(rep2['reason'], 'claim_failed')
        self.assertIs(rep2['claim_retained'], False)
        self.assertEqual(self._show_issue(i2)['status'], 'open')

        i3 = self._create_issue('Ambiguous claim lost ACK and readback failed')
        p3 = self._write_policy('ambig3.json', issue_allowlist=[i3])
        lost_ack_read_err_wrapper = (
            'import importlib.machinery, importlib.util, json, sys\n'
            'loader = importlib.machinery.SourceFileLoader("pi_team_dispatch_cli", sys.argv[1])\n'
            'spec = importlib.util.spec_from_loader("pi_team_dispatch_cli", loader)\n'
            'mod = importlib.util.module_from_spec(spec)\n'
            'spec.loader.exec_module(mod)\n'
            'orig_run_bd = mod._run_bd\n'
            'orig_bound_readonly = mod._run_bound_bd_readonly\n'
            'orig_bound_claim = mod._run_bound_bd_claim\n'
            'jpath = sys.argv[3]\n'
            'claim_seen = False\n'
            'def wrapped_bound_claim(**kwargs):\n'
            '    global claim_seen\n'
            '    orig_bound_claim(**kwargs)\n'
            '    claim_seen = True\n'
            '    with open(jpath, "a", encoding="utf-8") as jf:\n'
            '        jf.write(json.dumps(["bound_claim", kwargs.get("issue_id")]) + "\\n")\n'
            '    raise mod.DispatchError("lost ACK after claim")\n'
            'def wrapped_bound_readonly(**kwargs):\n'
            '    with open(jpath, "a", encoding="utf-8") as jf:\n'
            '        jf.write(json.dumps(["bound_readonly", kwargs.get("subcommand"), kwargs.get("issue_id"), claim_seen]) + "\\n")\n'
            '    if claim_seen and kwargs.get("subcommand") == "show":\n'
            '        raise mod.DispatchError("tracker readback unavailable")\n'
            '    return orig_bound_readonly(**kwargs)\n'
            'def wrapped_run_bd(repo_root, args, **kwargs):\n'
            '    with open(jpath, "a", encoding="utf-8") as jf:\n'
            '        jf.write(json.dumps(["host_bd", list(args)]) + "\\n")\n'
            '    return orig_run_bd(repo_root, args, **kwargs)\n'
            'mod._run_bound_bd_claim = wrapped_bound_claim\n'
            'mod._run_bound_bd_readonly = wrapped_bound_readonly\n'
            'mod._run_bd = wrapped_run_bd\n'
            'sys.exit(mod.main(["tick", "--policy", sys.argv[2], "--json"]))\n'
        )
        j3 = self.base / 'ambig3.jsonl'
        r3 = subprocess.run(
            [sys.executable, '-c', lost_ack_read_err_wrapper, str(DISPATCH_BIN), str(p3), str(j3)],
            env=self.env, capture_output=True, text=True, timeout=30, check=False,
        )
        self.assertNotEqual(r3.returncode, 0)
        rep3 = json.loads(r3.stdout)
        self.assertEqual(rep3['outcome'], 'quarantined')
        self.assertEqual(rep3['reason'], 'claim_ambiguous_tracker_error')
        self.assertEqual(rep3['claim_retained'], 'unknown')
        calls3 = [json.loads(line) for line in j3.read_text(encoding='utf-8').splitlines() if line.strip()]
        self.assertEqual(sum(1 for c in calls3 if c[0] == 'bound_claim'), 1)
        claim_idx3 = next(idx for idx, c in enumerate(calls3) if c[0] == 'bound_claim')
        self.assertTrue(
            any(c == ['bound_readonly', 'show', i3, True] for c in calls3[claim_idx3 + 1:]),
            msg=calls3,
        )
        self.assertNotEqual(self._run_ledger('start', str(self.repo)).returncode, 0)

    def test_live_descendant_stop_and_revoke_and_persistent_repo_stop(self) -> None:
        issue_id = self._create_issue('Long running descendant')
        marker = f'disp-desc-{os.getpid()}'
        marker_bytes = marker.encode('utf-8')
        worker_script = (
            'import subprocess, time\n'
            f'subprocess.Popen(["/usr/bin/python3", "-I", "-c", "import time; time.sleep(60)", "{marker}"], start_new_session=True)\n'
            'time.sleep(60)\n'
        )
        policy_path = self._write_policy(issue_allowlist=[issue_id], worker_script=worker_script)
        tick_proc = subprocess.Popen(
            [sys.executable, str(DISPATCH_BIN), 'tick', '--policy', str(policy_path), '--json'],
            env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        desc_pid: int | None = None
        try:
            db_path = self.xdg_state / 'pi-team-run' / 'state.db'
            run_id = None
            desc_seen = False
            deadline = time.monotonic() + 15.0
            while time.monotonic() < deadline:
                rc = tick_proc.poll()
                if rc is not None:
                    out, err = tick_proc.communicate(timeout=5)
                    detail = ''
                    try:
                        parsed = json.loads(out) if out.strip() else None
                    except json.JSONDecodeError:
                        parsed = None
                    if isinstance(parsed, dict):
                        detail = f" outcome={parsed.get('outcome')!r} reason={parsed.get('reason')!r}"
                    elif err.strip():
                        detail = f" err={err.strip().splitlines()[0][:120]!r}"
                    self.fail(f'tick exited early with code {rc}{detail}')
                if run_id is None and db_path.exists():
                    try:
                        with closing(sqlite3.connect(f'{db_path.resolve().as_uri()}?mode=ro', uri=True, timeout=1.0)) as conn:
                            conn.row_factory = sqlite3.Row
                            conn.execute('PRAGMA busy_timeout = 1000')
                            has_table = conn.execute(
                                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='dispatch_stage_procs'"
                            ).fetchone()
                            if has_table is not None:
                                row = conn.execute(
                                    "SELECT run_id, pid1 FROM dispatch_stage_procs WHERE stage='worker' AND status='running'"
                                ).fetchone()
                                if row is not None and row['pid1']:
                                    run_id = row['run_id']
                    except sqlite3.OperationalError as exc:
                        err_low = str(exc).lower()
                        if 'locked' not in err_low and 'busy' not in err_low:
                            raise
                if run_id is not None:
                    for pid_dir in Path('/proc').iterdir():
                        if not pid_dir.name.isdigit():
                            continue
                        try:
                            argv_parts = (pid_dir / 'cmdline').read_bytes().split(b'\x00')
                            if marker_bytes not in argv_parts:
                                continue
                            stat_text = (pid_dir / 'stat').read_text(encoding='utf-8')
                        except OSError:
                            continue
                        rparen = stat_text.rfind(')')
                        if rparen != -1 and stat_text[rparen + 2:].startswith('Z'):
                            continue
                        desc_pid = int(pid_dir.name)
                        desc_seen = True
                        break
                    if desc_seen:
                        break
                time.sleep(0.05)
            self.assertIsNotNone(run_id, 'worker sandbox did not reach running state')
            self.assertTrue(desc_seen, 'detached descendant child did not spawn before revoke')
            self.assertIsNotNone(desc_pid)

            stop_proc = self._run_dispatch('stop', '--policy', str(policy_path), '--reason', 'halt test', '--json')
            self.assertEqual(stop_proc.returncode, 0, msg=stop_proc.stderr + stop_proc.stdout)
            stdout, stderr = tick_proc.communicate(timeout=15)
            self.assertNotEqual(tick_proc.returncode, 0)
            rep = json.loads(stdout)
            self.assertEqual(rep['outcome'], 'cancelled')

            for pid_dir in Path('/proc').iterdir():
                if not pid_dir.name.isdigit():
                    continue
                try:
                    cmdline = (pid_dir / 'cmdline').read_bytes()
                except OSError:
                    continue
                self.assertNotIn(marker_bytes, cmdline.split(b'\x00'), 'detached descendant survived stop/revoke!')
                self.assertNotIn(marker_bytes, cmdline, 'sandbox process survived stop/revoke!')

            i2 = self._create_issue('Should stay stopped by repo marker')
            p2 = self._write_policy('after_stop.json', issue_allowlist=[i2])
            blocked_by_stop = self._run_dispatch('tick', '--policy', str(p2), '--json')
            self.assertNotEqual(blocked_by_stop.returncode, 0)
            rep_stop = json.loads(blocked_by_stop.stdout)
            self.assertEqual(rep_stop['outcome'], 'cancelled')
            self.assertEqual(rep_stop['reason'], 'repo_stop_marker_active')
        finally:
            if tick_proc.poll() is None:
                tick_proc.kill()
                tick_proc.communicate(timeout=5)
            if desc_pid is not None:
                try:
                    desc_cmd = Path(f'/proc/{desc_pid}/cmdline').read_bytes()
                    if marker_bytes in desc_cmd.split(b'\x00'):
                        os.kill(desc_pid, signal.SIGKILL)
                except OSError:
                    pass
            if tick_proc.stdout:
                tick_proc.stdout.close()
            if tick_proc.stderr:
                tick_proc.stderr.close()

    def test_stop_on_interrupted_claim_serializes_with_bd_lock(self) -> None:
        issue_id = self._create_issue('Interrupted claim stop')
        pol_path = self._write_policy('int_claim.json', issue_allowlist=[issue_id])
        mod = _load_dispatch_module()
        db_path = self.xdg_state / 'pi-team-run' / 'state.db'
        state_dir = self.xdg_state / 'pi-team-dispatch'
        mod.ensure_dispatch_dirs(state_dir)
        pol, pol_digest, pol_real = mod.load_and_validate_policy(str(pol_path), db_path=db_path, dispatch_state_dir=state_dir)
        tracker = mod._validate_local_beads_tracker(self.repo)
        run_id = 'disp-int-claim-01'
        actor = f'disp-test:{run_id}'
        now_iso = mod.format_utc(mod.utc_now())
        with mod.open_dispatch_tx(db_path) as conn:
            conn.execute(
                "INSERT INTO runs (run_id, repo_key, status, current_stage, wait_generation, commit_only, no_ci, with_deploy, with_honcho, with_wiki, created_at, updated_at) VALUES (?, ?, 'active', 'admit', 0, 1, 0, 0, 0, 0, ?, ?)",
                (run_id, pol['repo_key'], now_iso, now_iso),
            )
            conn.execute(
                "INSERT INTO dispatch_runs (run_id, repo_key, repo_root, beads_dir, beads_db_path, beads_dir_dev, beads_dir_ino, beads_db_dev, beads_db_ino, git_common_dir_dev, git_common_dir_ino, issue_id, actor, policy_path, policy_digest, base_sha, fingerprint, dispatch_state, attempt, max_attempts, spend_usd, max_spend_usd, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'fp', 'claiming', 0, 2, 0.0, 0.0, ?, ?)",
                (run_id, pol['repo_key'], pol['repo_root'], tracker['beads_dir'], tracker['beads_db_path'], tracker['beads_dir_dev'], tracker['beads_dir_ino'], tracker['beads_db_dev'], tracker['beads_db_ino'], *self._seed_git_pin(pol['repo_key']), issue_id, actor, str(pol_real), pol_digest, self.base_sha, now_iso, now_iso),
            )

        locks_dir = state_dir / 'locks'
        bd_lock_path = locks_dir / f'{sha256(pol["repo_key"].encode()).hexdigest()[:16]}.bd.lock'
        holder_script = (
            'import fcntl, os, sys, time\n'
            'fd = os.open(sys.argv[1], os.O_WRONLY | os.O_CREAT, 0o600)\n'
            'fcntl.flock(fd, fcntl.LOCK_EX)\n'
            'open(sys.argv[2], "w").write("locked")\n'
            'time.sleep(0.5)\n'
            'fcntl.flock(fd, fcntl.LOCK_UN)\n'
            'os.close(fd)\n'
        )
        ready_flag = self.base / 'bd_locked'
        holder = subprocess.Popen(
            [sys.executable, '-c', holder_script, str(bd_lock_path), str(ready_flag)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            deadline = time.monotonic() + 5.0
            while not ready_flag.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(ready_flag.exists())
            t0 = time.monotonic()
            stop_res = self._run_dispatch('revoke', '--run-id', run_id, '--reason', 'halt claim', '--json')
            elapsed = time.monotonic() - t0
            self.assertEqual(stop_res.returncode, 0, msg=stop_res.stderr + stop_res.stdout)
            self.assertGreaterEqual(elapsed, 0.35, 'stop released repo key before bd.lock finished!')
            self.assertEqual(json.loads(stop_res.stdout)['outcome'], 'cancelled')
        finally:
            holder.wait(timeout=10)

    def test_crash_recovery_pid_reuse_and_quarantine(self) -> None:
        sleeper = subprocess.Popen(
            ['/usr/bin/python3', '-I', '-c', 'import time; time.sleep(30)'],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            i1 = self._create_issue('PID reuse test')
            p1 = self._write_policy('reuse.json', issue_allowlist=[i1])
            mod = _load_dispatch_module()
            db_path = self.xdg_state / 'pi-team-run' / 'state.db'
            state_dir = self.xdg_state / 'pi-team-dispatch'
            pol, pol_digest, pol_real = mod.load_and_validate_policy(str(p1), db_path=db_path, dispatch_state_dir=state_dir)
            tracker = mod._validate_local_beads_tracker(self.repo)
            run_id = 'disp-pid-reuse-01'
            actor = f'disp-test:{run_id}'
            self._bd(self.repo, '--sandbox', '--actor', actor, 'update', i1, '--claim', '--json')
            issue_data = self._show_issue(i1)
            spec_fp = mod._issue_spec_fingerprint(issue_data, pol_digest, self.base_sha)
            now_iso = mod.format_utc(mod.utc_now())
            with mod.open_dispatch_tx(db_path) as conn:
                conn.execute(
                    "INSERT INTO runs (run_id, repo_key, status, current_stage, wait_generation, commit_only, no_ci, with_deploy, with_honcho, with_wiki, created_at, updated_at) VALUES (?, ?, 'active', 'admit', 0, 1, 0, 0, 0, 0, ?, ?)",
                    (run_id, pol['repo_key'], now_iso, now_iso),
                )
                conn.execute(
                    "INSERT INTO dispatch_runs (run_id, repo_key, repo_root, beads_dir, beads_db_path, beads_dir_dev, beads_dir_ino, beads_db_dev, beads_db_ino, git_common_dir_dev, git_common_dir_ino, issue_id, actor, policy_path, policy_digest, base_sha, fingerprint, dispatch_state, attempt, max_attempts, spend_usd, max_spend_usd, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'working', 0, 2, 0.0, 0.0, ?, ?)",
                    (run_id, pol['repo_key'], pol['repo_root'], tracker['beads_dir'], tracker['beads_db_path'], tracker['beads_dir_dev'], tracker['beads_dir_ino'], tracker['beads_db_dev'], tracker['beads_db_ino'], *self._seed_git_pin(pol['repo_key']), i1, actor, str(pol_real), pol_digest, self.base_sha, spec_fp, now_iso, now_iso),
                )
                conn.execute(
                    "INSERT INTO dispatch_stage_procs (run_id, attempt, stage, launch_token, status, pid1, boot_id, starttime, ns_pid, created_at, updated_at) VALUES (?, 1, 'worker', 'tok', 'running', ?, ?, '0', 'pid:[0]', ?, ?)",
                    (run_id, sleeper.pid, mod._read_boot_id(), now_iso, now_iso),
                )

            res = self._run_dispatch('tick', '--policy', str(p1), '--json')
            self.assertEqual(res.returncode, 0, msg=res.stderr + res.stdout)
            self.assertIsNone(sleeper.poll(), 'PID reuse killed an unrelated host process!')
        finally:
            if sleeper.poll() is None:
                sleeper.kill()
                sleeper.wait(timeout=5)

        i2 = self._create_issue('Quarantine test')
        p2 = self._write_policy('quarantine.json', issue_allowlist=[i2])
        mod = _load_dispatch_module()
        db_path = self.xdg_state / 'pi-team-run' / 'state.db'
        state_dir = self.xdg_state / 'pi-team-dispatch'
        pol, pol_digest, pol_real = mod.load_and_validate_policy(str(p2), db_path=db_path, dispatch_state_dir=state_dir)
        tracker2 = mod._validate_local_beads_tracker(self.repo)
        q_run = 'disp-quarantine-01'
        now_iso = mod.format_utc(mod.utc_now())
        with mod.open_dispatch_tx(db_path) as conn:
            conn.execute(
                "INSERT INTO runs (run_id, repo_key, status, current_stage, wait_generation, commit_only, no_ci, with_deploy, with_honcho, with_wiki, created_at, updated_at) VALUES (?, ?, 'active', 'admit', 0, 1, 0, 0, 0, 0, ?, ?)",
                (q_run, pol['repo_key'], now_iso, now_iso),
            )
            conn.execute(
                "INSERT INTO dispatch_runs (run_id, repo_key, repo_root, beads_dir, beads_db_path, beads_dir_dev, beads_dir_ino, beads_db_dev, beads_db_ino, git_common_dir_dev, git_common_dir_ino, issue_id, actor, policy_path, policy_digest, base_sha, fingerprint, dispatch_state, attempt, max_attempts, spend_usd, max_spend_usd, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'fp', 'working', 1, 2, 0.0, 0.0, ?, ?)",
                (q_run, pol['repo_key'], pol['repo_root'], tracker2['beads_dir'], tracker2['beads_db_path'], tracker2['beads_dir_dev'], tracker2['beads_dir_ino'], tracker2['beads_db_dev'], tracker2['beads_db_ino'], *self._seed_git_pin(pol['repo_key']), i2, f'disp-test:{q_run}', str(pol_real), pol_digest, self.base_sha, now_iso, now_iso),
            )
            conn.execute(
                "INSERT INTO dispatch_stage_procs (run_id, attempt, stage, launch_token, status, created_at, updated_at) VALUES (?, 1, 'worker', 'tok', 'launching', ?, ?)",
                (q_run, now_iso, now_iso),
            )
        q_res = self._run_dispatch('tick', '--policy', str(p2), '--json')
        self.assertNotEqual(q_res.returncode, 0)
        self.assertEqual(json.loads(q_res.stdout)['outcome'], 'quarantined')
        self.assertNotEqual(self._run_ledger('start', str(self.repo)).returncode, 0)

    def test_denied_changed_paths_links_hardlinks_special_modes_size(self) -> None:
        cases = [
            ('unapproved path', 'from pathlib import Path; Path("/workspace/other.txt").write_text("bad")'),
            ('unsafe symlink', 'import os; os.symlink("/etc/hosts", "/workspace/badlink")'),
            ('hardlink', 'import os; os.link("/workspace/allowed.txt", "/workspace/hard.txt")'),
            ('special file', 'import os; os.mkfifo("/workspace/fifo")'),
            ('mode change', 'import os; os.chmod("/workspace/allowed.txt", 0o755)'),
            ('excess file size', 'from pathlib import Path; Path("/workspace/allowed.txt").write_bytes(b"a" * (1024 * 1024 + 10))'),
        ]
        store_dir = (
            self.xdg_state
            / 'pi-team-dispatch'
            / 'git-store'
            / f'{sha256(str((self.repo / ".git").resolve()).encode()).hexdigest()[:16]}.git'
        )
        for label, script in cases:
            issue_id = self._create_issue(f'Reject {label}')
            pol = self._write_policy(f'{label.replace(" ", "_")}.json', issue_allowlist=[issue_id], worker_script=script)
            res = self._run_dispatch('tick', '--policy', str(pol), '--json')
            self.assertNotEqual(res.returncode, 0, msg=f'{label} unexpectedly succeeded')
            rep = json.loads(res.stdout)
            self.assertEqual(rep['outcome'], 'blocked', msg=label)
            self.assertIsNone(rep.get('candidate_sha'), msg=label)
            if label == 'mode change':
                self.assertTrue(rep['reason'].startswith('candidate_rejected:'), msg=rep)
            else:
                self.assertTrue(
                    rep['reason'] == 'worker_failed' or rep['reason'].startswith('candidate_rejected:'),
                    msg=rep,
                )
            if store_dir.exists():
                refs = subprocess.run(
                    ['git', '-C', str(store_dir), 'for-each-ref', f'refs/dispatch/candidates/{rep["run_id"]}'],
                    env=self.env, capture_output=True, text=True, check=True, timeout=15,
                ).stdout.strip()
                self.assertEqual(refs, '', msg=f'unexpected candidate ref for {label}')

    def test_check_failure_and_timeout(self) -> None:
        i1 = self._create_issue('Check failure')
        p1 = self._write_policy(
            'chk_fail.json',
            issue_allowlist=[i1],
            max_attempts=1,
            checks=[{'name': 'fail', 'argv': ['/usr/bin/python3', '-I', '-c', 'import sys; sys.exit(2)'], 'timeout_sec': 5}],
        )
        r1 = self._run_dispatch('tick', '--policy', str(p1), '--json')
        self.assertNotEqual(r1.returncode, 0)
        self.assertEqual(json.loads(r1.stdout)['reason'], 'checks_failed')

        i2 = self._create_issue('Check timeout')
        p2 = self._write_policy(
            'chk_to.json',
            issue_allowlist=[i2],
            max_attempts=1,
            checks=[{'name': 'slow', 'argv': ['/usr/bin/python3', '-I', '-c', 'import time; time.sleep(5)'], 'timeout_sec': 0.3}],
        )
        r2 = self._run_dispatch('tick', '--policy', str(p2), '--json')
        self.assertNotEqual(r2.returncode, 0)
        self.assertEqual(json.loads(r2.stdout)['reason'], 'check_timeout')

    def test_stale_review_sha_and_budget_stop_and_hardening(self) -> None:
        i1 = self._create_issue('Stale review SHA')
        stale_review = (
            'import json, os\n'
            'with open(os.environ["DISPATCH_INPUT"], encoding="utf-8") as f:\n'
            '    inp = json.load(f)\n'
            'print(json.dumps({\n'
            '    "issue_id": inp["issue_id"], "run_id": inp["run_id"], "attempt": inp["attempt"],\n'
            '    "candidate_sha": inp["base_sha"], "verdict": "pass", "findings": [], "evidence_refs": ["check:verify-allowed"]\n'
            '}))\n'
        )
        p1 = self._write_policy('stale_rev.json', issue_allowlist=[i1], review_script=stale_review)
        r1 = self._run_dispatch('tick', '--policy', str(p1), '--json')
        self.assertNotEqual(r1.returncode, 0)
        self.assertEqual(json.loads(r1.stdout)['reason'], 'stale_review_sha')

        i2 = self._create_issue('Budget stop and finding sanitization')
        secret_finding = 'SECRET_ACCEPTANCE_SHOULD_NOT_PERSIST'
        loop_review = (
            'import json, os\n'
            'with open(os.environ["DISPATCH_INPUT"], encoding="utf-8") as f:\n'
            '    inp = json.load(f)\n'
            'print(json.dumps({\n'
            '    "issue_id": inp["issue_id"], "run_id": inp["run_id"], "attempt": inp["attempt"],\n'
            '    "candidate_sha": inp["candidate_sha"], "verdict": "changes_requested",\n'
            f'    "findings": [f"{secret_finding}-{{inp[\'attempt\']}}"], "evidence_refs": ["check:verify-allowed"]\n'
            '}))\n'
        )
        p2 = self._write_policy('budget.json', issue_allowlist=[i2], max_attempts=2, review_script=loop_review)
        r2 = self._run_dispatch('tick', '--policy', str(p2), '--json')
        self.assertNotEqual(r2.returncode, 0)
        self.assertNotIn(secret_finding, r2.stdout)
        rep2 = json.loads(r2.stdout)
        self.assertEqual(rep2['attempt'], 2)
        self.assertEqual(rep2['spend_usd'], 0.0)
        self.assertEqual(rep2['reason'], 'attempt_budget_exhausted')
        db_path = self.xdg_state / 'pi-team-run' / 'state.db'
        with closing(sqlite3.connect(f'{db_path.resolve().as_uri()}?mode=ro', uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                'SELECT review_json, report_json, last_findings_json, repeated_finding_count FROM dispatch_runs WHERE run_id = ?',
                (rep2['run_id'],),
            ).fetchone()
            for col in ('review_json', 'report_json', 'last_findings_json'):
                self.assertNotIn(secret_finding, row[col] or '')
            self.assertEqual(row['repeated_finding_count'], 1)
            stage_rows = conn.execute(
                'SELECT attempt, stage, status FROM dispatch_stage_procs WHERE run_id = ? ORDER BY id ASC',
                (rep2['run_id'],),
            ).fetchall()
            self.assertEqual([(r['attempt'], r['status']) for r in stage_rows if r['stage'] == 'worker'], [(1, 'exited'), (2, 'exited')])
            self.assertEqual([r['attempt'] for r in stage_rows if r['stage'] == 'plan'], [1, 2])
            self.assertEqual([r['attempt'] for r in stage_rows if r['stage'] == 'check:verify-allowed'], [1, 2])
            self.assertEqual([r['attempt'] for r in stage_rows if r['stage'] == 'review'], [1, 2])

        i3 = self._create_issue('Contradictory pass review')
        bad_pass = (
            'import json, os\n'
            'with open(os.environ["DISPATCH_INPUT"], encoding="utf-8") as f:\n'
            '    inp = json.load(f)\n'
            'print(json.dumps({\n'
            '    "issue_id": inp["issue_id"], "run_id": inp["run_id"], "attempt": inp["attempt"],\n'
            '    "candidate_sha": inp["candidate_sha"], "verdict": "pass",\n'
            '    "findings": ["blocker"], "evidence_refs": ["check:verify-allowed"]\n'
            '}))\n'
        )
        p3 = self._write_policy('bad_pass.json', issue_allowlist=[i3], review_script=bad_pass)
        r3 = self._run_dispatch('tick', '--policy', str(p3), '--json')
        self.assertNotEqual(r3.returncode, 0)
        self.assertEqual(json.loads(r3.stdout)['reason'], 'contradictory_review_evidence')

        i4 = self._create_issue('Plan binding mismatch')
        bad_plan = (
            'import json, os\n'
            'with open(os.environ["DISPATCH_INPUT"], encoding="utf-8") as f:\n'
            '    inp = json.load(f)\n'
            'print(json.dumps({"issue_id": "wrong", "run_id": inp["run_id"], "attempt": inp["attempt"], "status": "ok", "steps": ["a"]}))\n'
        )
        p4 = self._write_policy('bad_plan.json', issue_allowlist=[i4], plan_script=bad_plan)
        r4 = self._run_dispatch('tick', '--policy', str(p4), '--json')
        self.assertNotEqual(r4.returncode, 0)
        self.assertEqual(json.loads(r4.stdout)['reason'], 'plan_binding_mismatch')

        i5 = self._create_issue('Missing required executor')
        p5 = self._write_policy('no_rev.json', issue_allowlist=[i5], executor_override={'mode': 'fake', 'stages': {'worker': {'script': 'pass'}}})
        r5 = self._run_dispatch('tick', '--policy', str(p5), '--json')
        self.assertNotEqual(r5.returncode, 0)
        self.assertEqual(json.loads(r5.stdout)['reason'], 'missing_required_executor:review')
        self.assertEqual(self._show_issue(i5)['status'], 'open')

        i6 = self._create_issue('Live executor denied')
        live_pol = self._write_policy('live.json', issue_allowlist=[i6], executor_override={'mode': 'live'})
        r_live = self._run_dispatch('dry-run', '--policy', str(live_pol), '--json')
        self.assertNotEqual(r_live.returncode, 0)
        self.assertIn('executor denied', r_live.stderr.lower())
        self.assertEqual(self._show_issue(i6)['status'], 'open')

        i7 = self._create_issue('Bad policy permissions')
        bad_perm = self._write_policy('perm.json', issue_allowlist=[i7], mode=0o644)
        r_perm = self._run_dispatch('dry-run', '--policy', str(bad_perm), '--json')
        self.assertNotEqual(r_perm.returncode, 0)
        self.assertIn('permissions must be owner-only', r_perm.stderr.lower())
        self.assertEqual(self._show_issue(i7)['status'], 'open')

    def test_check_retry_same_finding_limit_and_recovered_commit_resume(self) -> None:
        i_chk = self._create_issue('Check retry advances')
        chk_worker = (
            'import os\n'
            'from pathlib import Path\n'
            'text = "bad\\n" if os.environ["DISPATCH_ATTEMPT"] == "1" else "updated\\n"\n'
            'Path("/workspace/allowed.txt").write_text(text, encoding="utf-8")\n'
        )
        p_chk = self._write_policy('chk_retry.json', issue_allowlist=[i_chk], max_attempts=2, worker_script=chk_worker)
        r_chk = self._run_dispatch('tick', '--policy', str(p_chk), '--json')
        self.assertEqual(r_chk.returncode, 0, msg=r_chk.stderr + r_chk.stdout)
        rep_chk = json.loads(r_chk.stdout)
        self.assertEqual(rep_chk['outcome'], 'candidate_ready')
        self.assertEqual(rep_chk['attempt'], 2)

        db_path = self.xdg_state / 'pi-team-run' / 'state.db'
        with closing(sqlite3.connect(f'{db_path.resolve().as_uri()}?mode=ro', uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                'SELECT attempt, stage FROM dispatch_stage_procs WHERE run_id = ? ORDER BY id ASC',
                (rep_chk['run_id'],),
            ).fetchall()
            self.assertEqual([r['attempt'] for r in rows if r['stage'] == 'worker'], [1, 2])
            self.assertEqual([r['attempt'] for r in rows if r['stage'] == 'check:verify-allowed'], [1, 2])
            self.assertEqual([r['attempt'] for r in rows if r['stage'] == 'review'], [2])

        i_same = self._create_issue('Same finding limit stops early')
        same_review = (
            'import json, os\n'
            'with open(os.environ["DISPATCH_INPUT"], encoding="utf-8") as f:\n'
            '    inp = json.load(f)\n'
            'print(json.dumps({\n'
            '    "issue_id": inp["issue_id"], "run_id": inp["run_id"], "attempt": inp["attempt"],\n'
            '    "candidate_sha": inp["candidate_sha"], "verdict": "changes_requested",\n'
            '    "findings": ["IDENTICAL_FINDING"], "evidence_refs": ["check:verify-allowed"]\n'
            '}))\n'
        )
        p_same = self._write_policy('same_finding.json', issue_allowlist=[i_same], max_attempts=3, review_script=same_review)
        r_same = self._run_dispatch('tick', '--policy', str(p_same), '--json')
        self.assertNotEqual(r_same.returncode, 0)
        rep_same = json.loads(r_same.stdout)
        self.assertEqual(rep_same['outcome'], 'blocked')
        self.assertEqual(rep_same['reason'], 'same_finding_limit')
        self.assertEqual(rep_same['attempt'], 2)
        with closing(sqlite3.connect(f'{db_path.resolve().as_uri()}?mode=ro', uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            w_rows = conn.execute(
                "SELECT attempt FROM dispatch_stage_procs WHERE run_id = ? AND stage = 'worker' ORDER BY id ASC",
                (rep_same['run_id'],),
            ).fetchall()
            self.assertEqual([r['attempt'] for r in w_rows], [1, 2])

        mod = _load_dispatch_module()
        state_dir = self.xdg_state / 'pi-team-dispatch'
        mod.ensure_dispatch_dirs(state_dir)

        i_rec = self._create_issue('Recovered commit resume')
        rec_review = (
            'import json, os\n'
            'with open(os.environ["DISPATCH_INPUT"], encoding="utf-8") as f:\n'
            '    inp = json.load(f)\n'
            'assert inp["changed_paths"] == ["allowed.txt"], f"unexpected changed_paths: {inp[\'changed_paths\']}"\n'
            'print(json.dumps({\n'
            '    "issue_id": inp["issue_id"], "run_id": inp["run_id"], "attempt": inp["attempt"],\n'
            '    "candidate_sha": inp["candidate_sha"], "verdict": "pass",\n'
            '    "findings": [], "evidence_refs": ["check:verify-allowed"]\n'
            '}))\n'
        )
        p_rec = self._write_policy('rec_commit.json', issue_allowlist=[i_rec], max_attempts=2, review_script=rec_review)
        pol_rec, pol_rec_digest, pol_rec_real = mod.load_and_validate_policy(
            str(p_rec), db_path=db_path, dispatch_state_dir=state_dir,
        )
        tracker_rec = mod._validate_local_beads_tracker(self.repo)
        rec_run = 'disp-rec-commit-01'
        rec_actor = f'disp-test:{rec_run}'
        self._bd(self.repo, '--sandbox', '--actor', rec_actor, 'update', i_rec, '--claim', '--json')
        rec_issue = self._show_issue(i_rec)
        rec_fp = mod._issue_spec_fingerprint(rec_issue, pol_rec_digest, self.base_sha)
        store_dir = mod._sync_base_to_store(state_dir, pol_rec['repo_key'], Path(pol_rec['repo_root']), self.base_sha)
        with tempfile.TemporaryDirectory(dir=state_dir / 'scratch', prefix='rec-seed-') as seed_tmp:
            seed_dir = Path(seed_tmp)
            mat_ws = seed_dir / 'ws'
            mod._materialize_commit(store_dir, self.base_sha, mat_ws)
            (mat_ws / 'allowed.txt').write_text('updated\n', encoding='utf-8')
            cand_sha, _ = mod._validate_and_commit_candidate(
                store_dir=store_dir,
                scratch_dir=seed_dir,
                run_id=rec_run,
                attempt=1,
                base_sha=self.base_sha,
                worker_dir=mat_ws,
                allowed_paths=pol_rec['allowed_paths'],
                allowed_ops=pol_rec['allowed_ops'],
            )
        now_iso = mod.format_utc(mod.utc_now())
        with mod.open_dispatch_tx(db_path) as conn:
            conn.execute(
                "INSERT INTO runs (run_id, repo_key, status, current_stage, wait_generation, commit_only, no_ci, with_deploy, with_honcho, with_wiki, created_at, updated_at) VALUES (?, ?, 'active', 'admit', 0, 1, 0, 0, 0, 0, ?, ?)",
                (rec_run, pol_rec['repo_key'], now_iso, now_iso),
            )
            conn.execute(
                "INSERT INTO dispatch_runs (run_id, repo_key, repo_root, beads_dir, beads_db_path, beads_dir_dev, beads_dir_ino, beads_db_dev, beads_db_ino, git_common_dir_dev, git_common_dir_ino, issue_id, actor, policy_path, policy_digest, base_sha, candidate_sha, fingerprint, dispatch_state, attempt, max_attempts, spend_usd, max_spend_usd, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'reviewing', 1, 2, 0.0, 0.0, ?, ?)",
                (rec_run, pol_rec['repo_key'], pol_rec['repo_root'], tracker_rec['beads_dir'], tracker_rec['beads_db_path'], tracker_rec['beads_dir_dev'], tracker_rec['beads_dir_ino'], tracker_rec['beads_db_dev'], tracker_rec['beads_db_ino'], *self._seed_git_pin(pol_rec['repo_key']), i_rec, rec_actor, str(pol_rec_real), pol_rec_digest, self.base_sha, cand_sha, rec_fp, now_iso, now_iso),
            )
        r_rec = self._run_dispatch('tick', '--policy', str(p_rec), '--json')
        self.assertEqual(r_rec.returncode, 0, msg=r_rec.stderr + r_rec.stdout)
        rep_rec = json.loads(r_rec.stdout)
        self.assertEqual(rep_rec['outcome'], 'candidate_ready')
        self.assertEqual(rep_rec['attempt'], 1)
        self.assertEqual(rep_rec['candidate_sha'], cand_sha)
        with closing(sqlite3.connect(f'{db_path.resolve().as_uri()}?mode=ro', uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            rec_rows = conn.execute(
                'SELECT attempt, stage FROM dispatch_stage_procs WHERE run_id = ? ORDER BY id ASC',
                (rec_run,),
            ).fetchall()
            self.assertEqual([r['attempt'] for r in rec_rows if r['stage'] == 'plan'], [])
            self.assertEqual([r['attempt'] for r in rec_rows if r['stage'] == 'worker'], [])
            self.assertEqual([r['attempt'] for r in rec_rows if r['stage'] == 'check:verify-allowed'], [1])
            self.assertEqual([r['attempt'] for r in rec_rows if r['stage'] == 'review'], [1])

        i_rec2 = self._create_issue('Recovered commit repair loop')
        rec2_review = (
            'import json, os\n'
            'with open(os.environ["DISPATCH_INPUT"], encoding="utf-8") as f:\n'
            '    inp = json.load(f)\n'
            'if inp["attempt"] == 1:\n'
            '    print(json.dumps({\n'
            '        "issue_id": inp["issue_id"], "run_id": inp["run_id"], "attempt": 1,\n'
            '        "candidate_sha": inp["candidate_sha"], "verdict": "changes_requested",\n'
            '        "findings": ["repair-needed-1"], "evidence_refs": ["check:verify-allowed"]\n'
            '    }))\n'
            'else:\n'
            '    print(json.dumps({\n'
            '        "issue_id": inp["issue_id"], "run_id": inp["run_id"], "attempt": inp["attempt"],\n'
            '        "candidate_sha": inp["candidate_sha"], "verdict": "pass",\n'
            '        "findings": [], "evidence_refs": ["check:verify-allowed"]\n'
            '    }))\n'
        )
        p_rec2 = self._write_policy('rec_repair.json', issue_allowlist=[i_rec2], max_attempts=2, review_script=rec2_review)
        pol_rec2, pol_rec2_digest, pol_rec2_real = mod.load_and_validate_policy(
            str(p_rec2), db_path=db_path, dispatch_state_dir=state_dir,
        )
        rec2_run = 'disp-rec-repair-01'
        rec2_actor = f'disp-test:{rec2_run}'
        self._bd(self.repo, '--sandbox', '--actor', rec2_actor, 'update', i_rec2, '--claim', '--json')
        rec2_issue = self._show_issue(i_rec2)
        rec2_fp = mod._issue_spec_fingerprint(rec2_issue, pol_rec2_digest, self.base_sha)
        with tempfile.TemporaryDirectory(dir=state_dir / 'scratch', prefix='rec2-seed-') as seed_tmp:
            seed_dir = Path(seed_tmp)
            mat_ws = seed_dir / 'ws'
            mod._materialize_commit(store_dir, self.base_sha, mat_ws)
            (mat_ws / 'allowed.txt').write_text('updated\n', encoding='utf-8')
            cand_sha2, _ = mod._validate_and_commit_candidate(
                store_dir=store_dir,
                scratch_dir=seed_dir,
                run_id=rec2_run,
                attempt=1,
                base_sha=self.base_sha,
                worker_dir=mat_ws,
                allowed_paths=pol_rec2['allowed_paths'],
                allowed_ops=pol_rec2['allowed_ops'],
            )
        with mod.open_dispatch_tx(db_path) as conn:
            conn.execute(
                "INSERT INTO runs (run_id, repo_key, status, current_stage, wait_generation, commit_only, no_ci, with_deploy, with_honcho, with_wiki, created_at, updated_at) VALUES (?, ?, 'active', 'admit', 0, 1, 0, 0, 0, 0, ?, ?)",
                (rec2_run, pol_rec2['repo_key'], now_iso, now_iso),
            )
            conn.execute(
                "INSERT INTO dispatch_runs (run_id, repo_key, repo_root, beads_dir, beads_db_path, beads_dir_dev, beads_dir_ino, beads_db_dev, beads_db_ino, git_common_dir_dev, git_common_dir_ino, issue_id, actor, policy_path, policy_digest, base_sha, candidate_sha, fingerprint, dispatch_state, attempt, max_attempts, spend_usd, max_spend_usd, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'checking', 1, 2, 0.0, 0.0, ?, ?)",
                (rec2_run, pol_rec2['repo_key'], pol_rec2['repo_root'], tracker_rec['beads_dir'], tracker_rec['beads_db_path'], tracker_rec['beads_dir_dev'], tracker_rec['beads_dir_ino'], tracker_rec['beads_db_dev'], tracker_rec['beads_db_ino'], *self._seed_git_pin(pol_rec2['repo_key']), i_rec2, rec2_actor, str(pol_rec2_real), pol_rec2_digest, self.base_sha, cand_sha2, rec2_fp, now_iso, now_iso),
            )
        r_rec2 = self._run_dispatch('tick', '--policy', str(p_rec2), '--json')
        self.assertEqual(r_rec2.returncode, 0, msg=r_rec2.stderr + r_rec2.stdout)
        rep_rec2 = json.loads(r_rec2.stdout)
        self.assertEqual(rep_rec2['outcome'], 'candidate_ready')
        self.assertEqual(rep_rec2['attempt'], 2)
        self.assertNotEqual(rep_rec2['candidate_sha'], cand_sha2)
        with closing(sqlite3.connect(f'{db_path.resolve().as_uri()}?mode=ro', uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            rec2_rows = conn.execute(
                'SELECT attempt, stage FROM dispatch_stage_procs WHERE run_id = ? ORDER BY id ASC',
                (rec2_run,),
            ).fetchall()
            self.assertEqual([r['attempt'] for r in rec2_rows if r['stage'] == 'worker'], [2])
            self.assertEqual([r['attempt'] for r in rec2_rows if r['stage'] == 'check:verify-allowed'], [1, 2])
            self.assertEqual([r['attempt'] for r in rec2_rows if r['stage'] == 'review'], [1, 2])

    def test_whole_run_deadline_does_not_reset_on_restart_and_spec_drift_blocks(self) -> None:
        i1 = self._create_issue('Deadline no reset')
        p1 = self._write_policy('deadline.json', issue_allowlist=[i1], run_sec=30)
        mod = _load_dispatch_module()
        db_path = self.xdg_state / 'pi-team-run' / 'state.db'
        state_dir = self.xdg_state / 'pi-team-dispatch'
        pol, pol_digest, pol_real = mod.load_and_validate_policy(str(p1), db_path=db_path, dispatch_state_dir=state_dir)
        tracker = mod._validate_local_beads_tracker(self.repo)
        run_id = 'disp-expired-01'
        actor = f'disp-test:{run_id}'
        self._bd(self.repo, '--sandbox', '--actor', actor, 'update', i1, '--claim', '--json')
        issue_data = self._show_issue(i1)
        spec_fp = mod._issue_spec_fingerprint(issue_data, pol_digest, self.base_sha)
        past_iso = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat().replace('+00:00', 'Z')
        now_iso = mod.format_utc(mod.utc_now())
        with mod.open_dispatch_tx(db_path) as conn:
            conn.execute(
                "INSERT INTO runs (run_id, repo_key, status, current_stage, wait_generation, commit_only, no_ci, with_deploy, with_honcho, with_wiki, created_at, updated_at) VALUES (?, ?, 'active', 'admit', 0, 1, 0, 0, 0, 0, ?, ?)",
                (run_id, pol['repo_key'], now_iso, now_iso),
            )
            conn.execute(
                "INSERT INTO dispatch_runs (run_id, repo_key, repo_root, beads_dir, beads_db_path, beads_dir_dev, beads_dir_ino, beads_db_dev, beads_db_ino, git_common_dir_dev, git_common_dir_ino, issue_id, actor, policy_path, policy_digest, base_sha, fingerprint, dispatch_state, attempt, max_attempts, spend_usd, max_spend_usd, deadline_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'claimed', 0, 2, 0.0, 0.0, ?, ?, ?)",
                (run_id, pol['repo_key'], pol['repo_root'], tracker['beads_dir'], tracker['beads_db_path'], tracker['beads_dir_dev'], tracker['beads_dir_ino'], tracker['beads_db_dev'], tracker['beads_db_ino'], *self._seed_git_pin(pol['repo_key']), i1, actor, str(pol_real), pol_digest, self.base_sha, spec_fp, past_iso, now_iso, now_iso),
            )
        res = self._run_dispatch('tick', '--policy', str(p1), '--json')
        self.assertNotEqual(res.returncode, 0)
        self.assertEqual(json.loads(res.stdout)['reason'], 'run_timeout_exceeded')

        i2 = self._create_issue('Spec drift on recovery')
        p2 = self._write_policy('drift.json', issue_allowlist=[i2])
        self._bd(self.repo, '--sandbox', '--actor', 'disp-test:disp-drift-01', 'update', i2, '--claim', '--json')
        issue2 = self._show_issue(i2)
        fp2 = mod._issue_spec_fingerprint(issue2, pol_digest, self.base_sha)
        self._bd(self.repo, '--sandbox', 'update', i2, '--acceptance', 'changed mid-run')
        _, pol2_digest, pol2_real = mod.load_and_validate_policy(str(p2), db_path=db_path, dispatch_state_dir=state_dir)
        with mod.open_dispatch_tx(db_path) as conn:
            conn.execute(
                "INSERT INTO runs (run_id, repo_key, status, current_stage, wait_generation, commit_only, no_ci, with_deploy, with_honcho, with_wiki, created_at, updated_at) VALUES ('disp-drift-01', ?, 'active', 'admit', 0, 1, 0, 0, 0, 0, ?, ?)",
                (pol['repo_key'], now_iso, now_iso),
            )
            conn.execute(
                "INSERT INTO dispatch_runs (run_id, repo_key, repo_root, beads_dir, beads_db_path, beads_dir_dev, beads_dir_ino, beads_db_dev, beads_db_ino, git_common_dir_dev, git_common_dir_ino, issue_id, actor, policy_path, policy_digest, base_sha, fingerprint, dispatch_state, attempt, max_attempts, spend_usd, max_spend_usd, created_at, updated_at) VALUES ('disp-drift-01', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'disp-test:disp-drift-01', ?, ?, ?, ?, 'claimed', 0, 2, 0.0, 0.0, ?, ?)",
                (pol['repo_key'], pol['repo_root'], tracker['beads_dir'], tracker['beads_db_path'], tracker['beads_dir_dev'], tracker['beads_dir_ino'], tracker['beads_db_dev'], tracker['beads_db_ino'], *self._seed_git_pin(pol['repo_key']), i2, str(pol2_real), pol2_digest, self.base_sha, fp2, now_iso, now_iso),
            )
        res2 = self._run_dispatch('tick', '--policy', str(p2), '--json')
        self.assertNotEqual(res2.returncode, 0)
        rep2 = json.loads(res2.stdout)
        self.assertEqual(rep2['reason'], 'spec_fingerprint_changed')
        self.assertIs(rep2['claim_retained'], True)

    def test_sandbox_blocks_host_repo_tracker_network_and_fds(self) -> None:
        issue_id = self._create_issue('Isolation verification')
        worker_script = (
            'import ctypes, errno, os, socket, subprocess\n'
            'from pathlib import Path\n'
            f'assert not Path({str(self.repo)!r}).exists()\n'
            f'assert not Path({str(self.repo / ".beads")!r}).exists()\n'
            f'assert not Path({str(self.policy_dir)!r}).exists()\n'
            f'assert not Path({str(self.xdg_state)!r}).exists()\n'
            'assert not Path("/workspace/.git").exists()\n'
            'open_fds = sorted(int(x) for x in os.listdir("/proc/self/fd"))\n'
            'assert all(fd <= 4 for fd in open_fds), f"unexpected fds: {open_fds}"\n'
            'for fam in (socket.AF_INET, socket.AF_UNIX):\n'
            '    try:\n'
            '        s = socket.socket(fam, socket.SOCK_STREAM)\n'
            '        s.close()\n'
            '        raise AssertionError(f"socket unexpectedly succeeded for {fam}")\n'
            '    except PermissionError:\n'
            '        pass\n'
            'try:\n'
            '    a, b = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)\n'
            '    a.close(); b.close()\n'
            '    raise AssertionError("socketpair unexpectedly succeeded")\n'
            'except PermissionError:\n'
            '    pass\n'
            'libc = ctypes.CDLL("libc.so.6", use_errno=True)\n'
            'rc = libc.syscall(425, 1, 0)\n'
            'assert rc == -1 and ctypes.get_errno() == errno.EPERM, f"io_uring_setup rc={rc} errno={ctypes.get_errno()}"\n'
            'if os.uname().machine == "x86_64":\n'
            '    p = subprocess.run(["/usr/bin/python3", "-I", "-c", "import ctypes; libc = ctypes.CDLL(\'libc.so.6\'); libc.syscall(0x40000027)"])\n'
            '    assert p.returncode < 0, f"x32 syscall was not killed: rc={p.returncode}"\n'
            'Path("/workspace/allowed.txt").write_text("updated\\n", encoding="utf-8")\n'
        )
        pol = self._write_policy('iso.json', issue_allowlist=[issue_id], worker_script=worker_script)
        res = self._run_dispatch('tick', '--policy', str(pol), '--json')
        self.assertEqual(res.returncode, 0, msg=res.stderr + res.stdout)
        self.assertEqual(json.loads(res.stdout)['outcome'], 'candidate_ready')

    def test_nonstarving_park_and_unpark_on_change(self) -> None:
        parked_id = self._create_issue('Ambiguous issue', priority=0, acceptance='TBD')
        good_id = self._create_issue('Ready issue', priority=1, acceptance='allowed.txt updated cleanly')
        pol = self._write_policy('park.json', issue_allowlist=[parked_id, good_id])

        r1 = self._run_dispatch('tick', '--policy', str(pol), '--json')
        self.assertEqual(r1.returncode, 0, msg=r1.stderr + r1.stdout)
        rep1 = json.loads(r1.stdout)
        self.assertEqual(rep1['outcome'], 'candidate_ready')
        self.assertEqual(rep1['issue_id'], good_id)

        r2 = self._run_dispatch('tick', '--policy', str(pol), '--json')
        self.assertEqual(r2.returncode, 0, msg=r2.stderr + r2.stdout)
        rep2 = json.loads(r2.stdout)
        self.assertEqual(rep2['outcome'], 'no_work')
        self.assertIn(parked_id, rep2['skipped_unchanged'])

        upd = self._bd(self.repo, '--sandbox', 'update', parked_id, '--acceptance', 'allowed.txt updated cleanly')
        self.assertEqual(upd.returncode, 0, msg=upd.stderr)

        dry = self._run_dispatch('dry-run', '--policy', str(pol), '--json')
        self.assertEqual(dry.returncode, 0, msg=dry.stderr + dry.stdout)
        self.assertEqual(json.loads(dry.stdout)['issue_id'], parked_id)

    def test_beads_tracker_pinning_and_external_override_rejected(self) -> None:
        ext_repo = self.base / 'ext-repo'
        ext_repo.mkdir()
        self._git(ext_repo, 'init', '-b', 'main')
        ext_init = self._bd(ext_repo, 'init', '--sandbox', '--stealth', '--skip-agents', '--skip-hooks', '--prefix', 'ext')
        self.assertEqual(ext_init.returncode, 0, msg=ext_init.stderr + ext_init.stdout)
        ext_before = self._bd(ext_repo, '--readonly', '--sandbox', 'list', '--json').stdout

        issue_id = self._create_issue('Pin embedded tracker')
        pol = self._write_policy('pin.json', issue_allowlist=[issue_id])

        meta_path = self.repo / '.beads' / 'metadata.json'
        orig_meta = meta_path.read_bytes()
        try:
            meta_obj = json.loads(orig_meta.decode('utf-8'))
            meta_obj['dolt_data_dir'] = str(ext_repo / '.beads' / 'embeddeddolt')
            meta_path.write_text(json.dumps(meta_obj), encoding='utf-8')
            bad_override = self._run_dispatch('dry-run', '--policy', str(pol), '--json')
            self.assertNotEqual(bad_override.returncode, 0)
        finally:
            meta_path.write_bytes(orig_meta)

        emb_path = self.repo / '.beads' / 'embeddeddolt'
        emb_bak = self.repo / '.beads' / 'embeddeddolt.bak'
        emb_path.rename(emb_bak)
        try:
            emb_path.symlink_to(ext_repo / '.beads' / 'embeddeddolt')
            bad_sym = self._run_dispatch('dry-run', '--policy', str(pol), '--json')
            self.assertNotEqual(bad_sym.returncode, 0)
        finally:
            if emb_path.is_symlink():
                emb_path.unlink()
            emb_bak.rename(emb_path)

        mod = _load_dispatch_module()
        with patch.object(mod, '_run_bd', return_value=json.dumps({'beads_dir': str(self.repo / '.beads')})):
            with self.assertRaisesRegex(mod.DispatchError, 'database_path'):
                mod._validate_local_beads_tracker(self.repo)
        with patch.object(
            mod,
            '_run_bd',
            return_value=json.dumps({
                'beads_dir': str(self.repo / '.beads'),
                'database_path': str(ext_repo / '.beads' / 'embeddeddolt'),
            }),
        ):
            with self.assertRaisesRegex(mod.DispatchError, 'database_path'):
                mod._validate_local_beads_tracker(self.repo)

        self.assertEqual(self._bd(ext_repo, '--readonly', '--sandbox', 'list', '--json').stdout, ext_before)

        crash_before_claim = (
            'import importlib.machinery, importlib.util, os, sys\n'
            'loader = importlib.machinery.SourceFileLoader("pi_team_dispatch_cli", sys.argv[1])\n'
            'spec = importlib.util.spec_from_loader("pi_team_dispatch_cli", loader)\n'
            'mod = importlib.util.module_from_spec(spec)\n'
            'spec.loader.exec_module(mod)\n'
            'def wrapped(**kwargs):\n'
            '    os._exit(98)\n'
            'mod._run_bound_bd_claim = wrapped\n'
            'sys.exit(mod.main(["tick", "--policy", sys.argv[2], "--json"]))\n'
        )
        c_proc = subprocess.run(
            [sys.executable, '-c', crash_before_claim, str(DISPATCH_BIN), str(pol)],
            env=self.env, capture_output=True, text=True, timeout=30, check=False,
        )
        self.assertEqual(c_proc.returncode, 98, msg=c_proc.stderr + c_proc.stdout)

        db_path = self.xdg_state / 'pi-team-run' / 'state.db'
        with closing(sqlite3.connect(f'{db_path.resolve().as_uri()}?mode=ro', uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            drow = conn.execute('SELECT * FROM dispatch_runs').fetchone()
            self.assertEqual(drow['beads_db_path'], str(emb_path.resolve()))
            self.assertIsNotNone(drow['beads_db_ino'])

        emb_copy = self.repo / '.beads' / 'embeddeddolt.copy'
        shutil.copytree(emb_path, emb_copy)
        emb_path.rename(emb_bak)
        emb_copy.rename(emb_path)
        try:
            rec = self._run_dispatch('tick', '--policy', str(pol), '--json')
            self.assertNotEqual(rec.returncode, 0)
            rec_rep = json.loads(rec.stdout)
            self.assertEqual(rec_rep['outcome'], 'quarantined')
            self.assertEqual(rec_rep['reason'], 'tracker_identity_mismatch_on_claim')
            self.assertEqual(rec_rep['claim_retained'], 'unknown')
        finally:
            shutil.rmtree(emb_path, ignore_errors=True)
            emb_bak.rename(emb_path)

    def test_interrupted_claiming_fencing_on_deadline_stop_and_lock_busy(self) -> None:
        mod = _load_dispatch_module()
        db_path = self.xdg_state / 'pi-team-run' / 'state.db'
        state_dir = self.xdg_state / 'pi-team-dispatch'
        mod.ensure_dispatch_dirs(state_dir)
        past_iso = (datetime.now(timezone.utc) - timedelta(seconds=15)).isoformat().replace('+00:00', 'Z')

        def seed_claiming(run_id: str, issue_id: str, pol: dict, pol_digest: str, pol_real: Path, *, claim_in_bd: bool) -> None:
            actor = f'disp-test:{run_id}'
            if claim_in_bd:
                res = self._bd(self.repo, '--sandbox', '--actor', actor, 'update', issue_id, '--claim', '--json')
                self.assertEqual(res.returncode, 0, msg=res.stderr)
            tracker = mod._validate_local_beads_tracker(self.repo)
            issue_data = self._show_issue(issue_id)
            spec_fp = mod._issue_spec_fingerprint(issue_data, pol_digest, self.base_sha)
            now_iso = mod.format_utc(mod.utc_now())
            with mod.open_dispatch_tx(db_path) as conn:
                conn.execute('DELETE FROM dispatch_stage_procs')
                conn.execute('DELETE FROM dispatch_runs')
                conn.execute('DELETE FROM runs')
                conn.execute(
                    "INSERT INTO runs (run_id, repo_key, status, current_stage, wait_generation, commit_only, no_ci, with_deploy, with_honcho, with_wiki, created_at, updated_at) VALUES (?, ?, 'active', 'admit', 0, 1, 0, 0, 0, 0, ?, ?)",
                    (run_id, pol['repo_key'], now_iso, now_iso),
                )
                conn.execute(
                    "INSERT INTO dispatch_runs (run_id, repo_key, repo_root, beads_dir, beads_db_path, beads_dir_dev, beads_dir_ino, beads_db_dev, beads_db_ino, git_common_dir_dev, git_common_dir_ino, issue_id, actor, policy_path, policy_digest, base_sha, fingerprint, dispatch_state, attempt, max_attempts, spend_usd, max_spend_usd, deadline_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'claiming', 0, 2, 0.0, 0.0, ?, ?, ?)",
                    (
                        run_id, pol['repo_key'], pol['repo_root'],
                        tracker['beads_dir'], tracker['beads_db_path'],
                        tracker['beads_dir_dev'], tracker['beads_dir_ino'],
                        tracker['beads_db_dev'], tracker['beads_db_ino'],
                        *self._seed_git_pin(pol['repo_key']),
                        issue_id, actor, str(pol_real), pol_digest, self.base_sha, spec_fp, past_iso, now_iso, now_iso,
                    ),
                )

        # Case A: expired deadline on claiming row that ALREADY committed in bd -> reconciles to claimed without re-claim.
        i1 = self._create_issue('Expired claiming already claimed')
        p1 = self._write_policy('fence_a.json', issue_allowlist=[i1])
        pol1, d1, r1 = mod.load_and_validate_policy(str(p1), db_path=db_path, dispatch_state_dir=state_dir)
        seed_claiming('disp-fence-a', i1, pol1, d1, r1, claim_in_bd=True)
        j_a = self.base / 'fence_a.jsonl'
        log_wrapper = (
            'import importlib.machinery, importlib.util, json, sys\n'
            'loader = importlib.machinery.SourceFileLoader("pi_team_dispatch_cli", sys.argv[1])\n'
            'spec = importlib.util.spec_from_loader("pi_team_dispatch_cli", loader)\n'
            'mod = importlib.util.module_from_spec(spec)\n'
            'spec.loader.exec_module(mod)\n'
            'orig_run_bd = mod._run_bd\n'
            'orig_bound_readonly = mod._run_bound_bd_readonly\n'
            'orig_bound_claim = mod._run_bound_bd_claim\n'
            'jpath = sys.argv[3]\n'
            'def wrapped_run_bd(repo_root, args, **kwargs):\n'
            '    with open(jpath, "a", encoding="utf-8") as jf:\n'
            '        jf.write(json.dumps(["host_bd", list(args)]) + "\\n")\n'
            '    return orig_run_bd(repo_root, args, **kwargs)\n'
            'def wrapped_bound_readonly(**kwargs):\n'
            '    with open(jpath, "a", encoding="utf-8") as jf:\n'
            '        jf.write(json.dumps(["bound_readonly", kwargs.get("subcommand"), kwargs.get("issue_id")]) + "\\n")\n'
            '    return orig_bound_readonly(**kwargs)\n'
            'def wrapped_bound_claim(**kwargs):\n'
            '    with open(jpath, "a", encoding="utf-8") as jf:\n'
            '        jf.write(json.dumps(["bound_claim", kwargs.get("issue_id")]) + "\\n")\n'
            '    return orig_bound_claim(**kwargs)\n'
            'mod._run_bd = wrapped_run_bd\n'
            'mod._run_bound_bd_readonly = wrapped_bound_readonly\n'
            'mod._run_bound_bd_claim = wrapped_bound_claim\n'
            'sys.exit(mod.main(["tick", "--policy", sys.argv[2], "--json"]))\n'
        )
        res_a = subprocess.run(
            [sys.executable, '-c', log_wrapper, str(DISPATCH_BIN), str(p1), str(j_a)],
            env=self.env, capture_output=True, text=True, timeout=30, check=False,
        )
        self.assertNotEqual(res_a.returncode, 0)
        rep_a = json.loads(res_a.stdout)
        self.assertEqual(rep_a['reason'], 'run_timeout_exceeded')
        self.assertIs(rep_a['claim_retained'], True)
        calls_a = [json.loads(ln) for ln in j_a.read_text(encoding='utf-8').splitlines() if ln.strip()]
        self.assertTrue(any(c == ['bound_readonly', 'show', i1] for c in calls_a), msg=calls_a)
        self.assertFalse(any(c[0] == 'bound_claim' for c in calls_a), msg=calls_a)
        self.assertFalse(any(c[0] == 'host_bd' and '--claim' in c[1] for c in calls_a), msg=calls_a)

        # Case B: expired deadline on claiming + tracker show failure -> quarantine retaining reservation, unknown ownership.
        i2 = self._create_issue('Expired claiming read failure')
        p2 = self._write_policy('fence_b.json', issue_allowlist=[i2])
        pol2, d2, r2 = mod.load_and_validate_policy(str(p2), db_path=db_path, dispatch_state_dir=state_dir)
        seed_claiming('disp-fence-b', i2, pol2, d2, r2, claim_in_bd=True)
        j_b = self.base / 'fence_b.jsonl'
        fail_show_wrapper = (
            'import importlib.machinery, importlib.util, json, sys\n'
            'loader = importlib.machinery.SourceFileLoader("pi_team_dispatch_cli", sys.argv[1])\n'
            'spec = importlib.util.spec_from_loader("pi_team_dispatch_cli", loader)\n'
            'mod = importlib.util.module_from_spec(spec)\n'
            'spec.loader.exec_module(mod)\n'
            'orig_run_bd = mod._run_bd\n'
            'orig_bound_readonly = mod._run_bound_bd_readonly\n'
            'orig_bound_claim = mod._run_bound_bd_claim\n'
            'jpath = sys.argv[3]\n'
            'def wrapped_run_bd(repo_root, args, **kwargs):\n'
            '    with open(jpath, "a", encoding="utf-8") as jf:\n'
            '        jf.write(json.dumps(["host_bd", list(args)]) + "\\n")\n'
            '    return orig_run_bd(repo_root, args, **kwargs)\n'
            'def wrapped_bound_readonly(**kwargs):\n'
            '    with open(jpath, "a", encoding="utf-8") as jf:\n'
            '        jf.write(json.dumps(["bound_readonly", kwargs.get("subcommand"), kwargs.get("issue_id")]) + "\\n")\n'
            '    if kwargs.get("subcommand") == "show":\n'
            '        raise mod.DispatchError("bd show unavailable")\n'
            '    return orig_bound_readonly(**kwargs)\n'
            'def wrapped_bound_claim(**kwargs):\n'
            '    with open(jpath, "a", encoding="utf-8") as jf:\n'
            '        jf.write(json.dumps(["bound_claim", kwargs.get("issue_id")]) + "\\n")\n'
            '    return orig_bound_claim(**kwargs)\n'
            'mod._run_bd = wrapped_run_bd\n'
            'mod._run_bound_bd_readonly = wrapped_bound_readonly\n'
            'mod._run_bound_bd_claim = wrapped_bound_claim\n'
            'sys.exit(mod.main(["tick", "--policy", sys.argv[2], "--json"]))\n'
        )
        res_b = subprocess.run(
            [sys.executable, '-c', fail_show_wrapper, str(DISPATCH_BIN), str(p2), str(j_b)],
            env=self.env, capture_output=True, text=True, timeout=30, check=False,
        )
        self.assertNotEqual(res_b.returncode, 0)
        rep_b = json.loads(res_b.stdout)
        self.assertEqual(rep_b['outcome'], 'quarantined')
        self.assertEqual(rep_b['reason'], 'tracker_unavailable_on_claim')
        self.assertEqual(rep_b['claim_retained'], 'unknown')
        calls_b = [json.loads(ln) for ln in j_b.read_text(encoding='utf-8').splitlines() if ln.strip()]
        self.assertTrue(any(c == ['bound_readonly', 'show', i2] for c in calls_b), msg=calls_b)
        self.assertFalse(any(c[0] == 'bound_claim' for c in calls_b), msg=calls_b)
        self.assertNotEqual(self._run_ledger('start', str(self.repo)).returncode, 0)

        # Case C: policy digest drift on claiming + bd show fails -> quarantine, unknown ownership, reservation retained.
        i3 = self._create_issue('Policy drift on claiming')
        p3 = self._write_policy('fence_c.json', issue_allowlist=[i3])
        pol3, d3, r3 = mod.load_and_validate_policy(str(p3), db_path=db_path, dispatch_state_dir=state_dir)
        seed_claiming('disp-fence-c', i3, pol3, d3, r3, claim_in_bd=True)
        p3_changed = self._write_policy('fence_c.json', issue_allowlist=[i3], run_sec=90)
        j_c = self.base / 'fence_c.jsonl'
        res_c = subprocess.run(
            [sys.executable, '-c', fail_show_wrapper, str(DISPATCH_BIN), str(p3_changed), str(j_c)],
            env=self.env, capture_output=True, text=True, timeout=30, check=False,
        )
        self.assertNotEqual(res_c.returncode, 0)
        rep_c = json.loads(res_c.stdout)
        self.assertEqual(rep_c['outcome'], 'quarantined')
        self.assertEqual(rep_c['reason'], 'policy_digest_changed_on_recovery')
        self.assertEqual(rep_c['claim_retained'], 'unknown')
        calls_c = [json.loads(ln) for ln in j_c.read_text(encoding='utf-8').splitlines() if ln.strip()]
        self.assertTrue(any(c == ['bound_readonly', 'show', i3] for c in calls_c), msg=calls_c)
        self.assertFalse(any(c[0] == 'bound_claim' for c in calls_c), msg=calls_c)
        self.assertNotEqual(self._run_ledger('start', str(self.repo)).returncode, 0)

        # Case D: bd.lock busy during claiming recovery -> quarantine retaining reservation, unknown ownership.
        i4 = self._create_issue('Lock busy on claiming')
        p4 = self._write_policy('fence_d.json', issue_allowlist=[i4])
        pol4, d4, r4 = mod.load_and_validate_policy(str(p4), db_path=db_path, dispatch_state_dir=state_dir)
        seed_claiming('disp-fence-d', i4, pol4, d4, r4, claim_in_bd=False)
        j_d = self.base / 'fence_d.jsonl'
        lock_busy_wrapper = (
            'import importlib.machinery, importlib.util, json, sys\n'
            'loader = importlib.machinery.SourceFileLoader("pi_team_dispatch_cli", sys.argv[1])\n'
            'spec = importlib.util.spec_from_loader("pi_team_dispatch_cli", loader)\n'
            'mod = importlib.util.module_from_spec(spec)\n'
            'spec.loader.exec_module(mod)\n'
            'orig_bound_readonly = mod._run_bound_bd_readonly\n'
            'orig_bound_claim = mod._run_bound_bd_claim\n'
            'jpath = sys.argv[3]\n'
            'def wrapped_bound_readonly(**kwargs):\n'
            '    with open(jpath, "a", encoding="utf-8") as jf:\n'
            '        jf.write(json.dumps(["bound_readonly", kwargs.get("subcommand"), kwargs.get("issue_id")]) + "\\n")\n'
            '    return orig_bound_readonly(**kwargs)\n'
            'def wrapped_bound_claim(**kwargs):\n'
            '    with open(jpath, "a", encoding="utf-8") as jf:\n'
            '        jf.write(json.dumps(["bound_claim", kwargs.get("issue_id")]) + "\\n")\n'
            '    return orig_bound_claim(**kwargs)\n'
            'mod._run_bound_bd_readonly = wrapped_bound_readonly\n'
            'mod._run_bound_bd_claim = wrapped_bound_claim\n'
            'mod._flock_with_timeout = lambda fd, timeout_sec: False\n'
            'sys.exit(mod.main(["tick", "--policy", sys.argv[2], "--json"]))\n'
        )
        res_d = subprocess.run(
            [sys.executable, '-c', lock_busy_wrapper, str(DISPATCH_BIN), str(p4), str(j_d)],
            env=self.env, capture_output=True, text=True, timeout=30, check=False,
        )
        self.assertNotEqual(res_d.returncode, 0)
        rep_d = json.loads(res_d.stdout)
        self.assertEqual(rep_d['outcome'], 'quarantined')
        self.assertEqual(rep_d['reason'], 'claim_bd_lock_busy')
        self.assertEqual(rep_d['claim_retained'], 'unknown')
        calls_d = [json.loads(ln) for ln in (j_d.read_text(encoding='utf-8') if j_d.exists() else '').splitlines() if ln.strip()]
        self.assertFalse(any(c[0] == 'bound_claim' for c in calls_d), msg=calls_d)
        self.assertNotEqual(self._run_ledger('start', str(self.repo)).returncode, 0)

        # Case E: cmd_stop on claiming when bd show fails -> quarantine retaining reservation, unknown ownership.
        i5 = self._create_issue('Stop reconcile failure on claiming')
        p5 = self._write_policy('fence_e.json', issue_allowlist=[i5])
        pol5, d5, r5 = mod.load_and_validate_policy(str(p5), db_path=db_path, dispatch_state_dir=state_dir)
        seed_claiming('disp-fence-e', i5, pol5, d5, r5, claim_in_bd=True)
        j_e = self.base / 'fence_e.jsonl'
        stop_fail_wrapper = (
            'import importlib.machinery, importlib.util, json, sys\n'
            'loader = importlib.machinery.SourceFileLoader("pi_team_dispatch_cli", sys.argv[1])\n'
            'spec = importlib.util.spec_from_loader("pi_team_dispatch_cli", loader)\n'
            'mod = importlib.util.module_from_spec(spec)\n'
            'spec.loader.exec_module(mod)\n'
            'orig_run_bd = mod._run_bd\n'
            'orig_bound_readonly = mod._run_bound_bd_readonly\n'
            'orig_bound_claim = mod._run_bound_bd_claim\n'
            'jpath = sys.argv[2]\n'
            'def wrapped_run_bd(repo_root, args, **kwargs):\n'
            '    with open(jpath, "a", encoding="utf-8") as jf:\n'
            '        jf.write(json.dumps(["host_bd", list(args)]) + "\\n")\n'
            '    return orig_run_bd(repo_root, args, **kwargs)\n'
            'def wrapped_bound_readonly(**kwargs):\n'
            '    with open(jpath, "a", encoding="utf-8") as jf:\n'
            '        jf.write(json.dumps(["bound_readonly", kwargs.get("subcommand"), kwargs.get("issue_id")]) + "\\n")\n'
            '    if kwargs.get("subcommand") == "show":\n'
            '        raise mod.DispatchError("bd show unavailable")\n'
            '    return orig_bound_readonly(**kwargs)\n'
            'def wrapped_bound_claim(**kwargs):\n'
            '    with open(jpath, "a", encoding="utf-8") as jf:\n'
            '        jf.write(json.dumps(["bound_claim", kwargs.get("issue_id")]) + "\\n")\n'
            '    return orig_bound_claim(**kwargs)\n'
            'mod._run_bd = wrapped_run_bd\n'
            'mod._run_bound_bd_readonly = wrapped_bound_readonly\n'
            'mod._run_bound_bd_claim = wrapped_bound_claim\n'
            'sys.exit(mod.main(["stop", "--run-id", "disp-fence-e", "--json"]))\n'
        )
        res_e = subprocess.run(
            [sys.executable, '-c', stop_fail_wrapper, str(DISPATCH_BIN), str(j_e)],
            env=self.env, capture_output=True, text=True, timeout=30, check=False,
        )
        self.assertNotEqual(res_e.returncode, 0)
        rep_e = json.loads(res_e.stdout)
        self.assertEqual(rep_e['outcome'], 'quarantined')
        self.assertEqual(rep_e['reason'], 'tracker_revalidation_failed')
        self.assertEqual(rep_e['claim_retained'], 'unknown')
        calls_e = [json.loads(ln) for ln in j_e.read_text(encoding='utf-8').splitlines() if ln.strip()]
        self.assertTrue(any(c == ['bound_readonly', 'show', i5] for c in calls_e), msg=calls_e)
        self.assertFalse(any(c[0] == 'bound_claim' for c in calls_e), msg=calls_e)
        self.assertNotEqual(self._run_ledger('start', str(self.repo)).returncode, 0)

    def test_sandbox_enforces_ro_workspace_prebound_bounds_and_fallocate(self) -> None:
        issue_id = self._create_issue('Real sandbox write bounds')
        worker_script = (
            'import ctypes, errno, os, signal\n'
            'from pathlib import Path\n'
            'for fn in (\n'
            '    lambda: Path("/workspace/other.txt").write_text("bad"),\n'
            '    lambda: Path("/workspace/new.txt").write_text("bad"),\n'
            '    lambda: os.unlink("/workspace/allowed.txt"),\n'
            '    lambda: os.rename("/workspace/allowed.txt", "/workspace/moved.txt"),\n'
            '    lambda: os.symlink("/etc/hosts", "/workspace/slink"),\n'
            '    lambda: os.link("/workspace/allowed.txt", "/workspace/hlink"),\n'
            '    lambda: Path("/root_denied").write_text("bad"),\n'
            '    lambda: Path("/dev/newfile").write_text("bad"),\n'
            '):\n'
            '    try:\n'
            '        fn()\n'
            '        raise AssertionError("expected EROFS")\n'
            '    except OSError as exc:\n'
            '        assert exc.errno == errno.EROFS, f"unexpected errno: {exc}"\n'
            'with open("/dev/null", "wb") as dn:\n'
            '    dn.write(b"ok")\n'
            'with open("/dev/null", "rb") as dnr:\n'
            '    assert dnr.read() == b""\n'
            'with open("/dev/zero", "rb") as dz:\n'
            '    assert len(dz.read(16)) == 16\n'
            'with open("/dev/urandom", "rb") as du:\n'
            '    assert len(du.read(16)) == 16\n'
            'libc = ctypes.CDLL("libc.so.6", use_errno=True)\n'
            'nr_falloc = 285 if os.uname().machine == "x86_64" else 47\n'
            'fd = os.open("/workspace/allowed.txt", os.O_RDWR)\n'
            'try:\n'
            '    rc = libc.syscall(nr_falloc, fd, 0, 0, 1024)\n'
            '    assert rc == -1 and ctypes.get_errno() == errno.EPERM, f"fallocate rc={rc} errno={ctypes.get_errno()}"\n'
            'finally:\n'
            '    os.close(fd)\n'
            'signal.signal(signal.SIGXFSZ, signal.SIG_IGN)\n'
            'with open("/workspace/allowed.txt", "wb", buffering=0) as f:\n'
            '    f.write(b"x" * 1_048_576)\n'
            '    try:\n'
            '        f.write(b"overflow")\n'
            '        raise AssertionError("expected EFBIG on oversized write")\n'
            '    except OSError as exc:\n'
            '        assert exc.errno == errno.EFBIG, f"unexpected write errno: {exc}"\n'
            'assert os.path.getsize("/workspace/allowed.txt") <= 1_048_576\n'
            'for tmp_dir in ("/tmp", "/scratch"):\n'
            '    created = []\n'
            '    try:\n'
            '        for idx in range(10):\n'
            '            p = f"{tmp_dir}/chunk_{idx}"\n'
            '            created.append(p)\n'
            '            with open(p, "wb", buffering=0) as tf:\n'
            '                tf.write(b"z" * 1_000_000)\n'
            '        raise AssertionError(f"expected aggregate tmpfs ENOSPC on {tmp_dir}")\n'
            '    except OSError as exc:\n'
            '        assert exc.errno == errno.ENOSPC, f"unexpected aggregate tmpfs errno on {tmp_dir}: {exc}"\n'
            '    finally:\n'
            '        for p in created:\n'
            '            try:\n'
            '                os.unlink(p)\n'
            '            except OSError:\n'
            '                pass\n'
            'Path("/workspace/allowed.txt").write_text("initial\\n", encoding="utf-8")\n'
        )
        pol = self._write_policy('bounds.json', issue_allowlist=[issue_id], worker_script=worker_script)
        res = self._run_dispatch('tick', '--policy', str(pol), '--json')
        self.assertNotEqual(res.returncode, 0, msg=res.stderr + res.stdout)
        rep = json.loads(res.stdout)
        self.assertEqual(rep['outcome'], 'blocked')
        self.assertEqual(rep['reason'], 'candidate_rejected:empty_candidate')
        self.assertIsNone(rep.get('candidate_sha'))
        store_dir = (
            self.xdg_state
            / 'pi-team-dispatch'
            / 'git-store'
            / f'{sha256(str((self.repo / ".git").resolve()).encode()).hexdigest()[:16]}.git'
        )
        refs = subprocess.run(
            ['git', '-C', str(store_dir), 'for-each-ref', f'refs/dispatch/candidates/{rep["run_id"]}'],
            env=self.env, capture_output=True, text=True, check=True, timeout=15,
        ).stdout.strip()
        self.assertEqual(refs, '')

    def test_review_and_plan_reject_truncated_and_multi_object_stdout(self) -> None:
        pass_obj_code = (
            'import json, os\n'
            'with open(os.environ["DISPATCH_INPUT"], encoding="utf-8") as f:\n'
            '    inp = json.load(f)\n'
            'payload = json.dumps({"issue_id": inp["issue_id"], "run_id": inp["run_id"], "attempt": inp["attempt"], '
            '"candidate_sha": inp["candidate_sha"], "verdict": "pass", "findings": [], "evidence_refs": ["check:verify-allowed"]})\n'
        )
        cases = [
            ('second_obj', pass_obj_code + 'print(payload)\nprint(payload)\n', None, 'missing_review_evidence'),
            ('truncated_stdout', pass_obj_code + 'import sys; sys.stdout.write(payload + (" " * 300000))\n', None, 'missing_review_evidence'),
            (
                'dup_key',
                'import json, os\n'
                'inp = json.load(open(os.environ["DISPATCH_INPUT"], encoding="utf-8"))\n'
                'base = json.dumps({"issue_id": inp["issue_id"], "run_id": inp["run_id"], "attempt": inp["attempt"], '
                '"candidate_sha": inp["candidate_sha"], "verdict": "pass", "findings": [], "evidence_refs": ["check:verify-allowed"]})\n'
                'print(\'{"verdict":"changes_requested",\' + base[1:])\n',
                None,
                'missing_review_evidence',
            ),
            (
                'plan_second_obj',
                None,
                'import json, os\n'
                'inp = json.load(open(os.environ["DISPATCH_INPUT"], encoding="utf-8"))\n'
                'p = json.dumps({"issue_id": inp["issue_id"], "run_id": inp["run_id"], "attempt": inp["attempt"], '
                '"base_sha": inp["base_sha"], "status": "ok", "steps": ["a"]})\n'
                'print(p)\nprint(p)\n',
                'plan_blocked',
            ),
        ]
        for label, rev_s, plan_s, expected_reason in cases:
            iid = self._create_issue(f'JSON strict {label}')
            pol = self._write_policy(
                f'json_{label}.json',
                issue_allowlist=[iid],
                max_attempts=1,
                plan_script=plan_s,
                review_script=rev_s,
            )
            res = self._run_dispatch('tick', '--policy', str(pol), '--json')
            self.assertNotEqual(res.returncode, 0, msg=f'{label} unexpectedly promoted')
            rep = json.loads(res.stdout)
            self.assertEqual(rep['outcome'], 'blocked', msg=label)
            self.assertEqual(rep['reason'], expected_reason, msg=label)

    def test_inline_acceptance_criteria_consistent_across_eligibility_and_stages(self) -> None:
        proc = self._bd(
            self.repo,
            '--sandbox',
            'create',
            'Inline criteria task',
            '-d',
            'Update allowed.txt\nAcceptance Criteria: inline exact criteria\n',
            '-p',
            '1',
            '-l',
            'low-risk',
            '--json',
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr + proc.stdout)
        data = json.loads(proc.stdout)
        inline_id = (data[0] if isinstance(data, list) else data)['id']

        check_ac = 'assert inp["acceptance_criteria"] == "inline exact criteria", repr(inp["acceptance_criteria"])\n'
        plan_s = (
            'import json, os\n'
            'inp = json.load(open(os.environ["DISPATCH_INPUT"], encoding="utf-8"))\n'
            + check_ac
            + 'print(json.dumps({"issue_id": inp["issue_id"], "run_id": inp["run_id"], '
            '"attempt": inp["attempt"], "base_sha": inp["base_sha"], "status": "ok", "steps": ["implement"]}))\n'
        )
        worker_s = (
            'import json, os\n'
            'from pathlib import Path\n'
            'inp = json.load(open(os.environ["DISPATCH_INPUT"], encoding="utf-8"))\n'
            + check_ac
            + 'Path("/workspace/allowed.txt").write_text("updated\\n", encoding="utf-8")\n'
        )
        review_s = (
            'import json, os\n'
            'inp = json.load(open(os.environ["DISPATCH_INPUT"], encoding="utf-8"))\n'
            + check_ac
            + 'print(json.dumps({"issue_id": inp["issue_id"], "run_id": inp["run_id"], "attempt": inp["attempt"], '
            '"candidate_sha": inp["candidate_sha"], "verdict": "pass", "findings": [], "evidence_refs": ["check:verify-allowed"]}))\n'
        )
        pol = self._write_policy(
            'inline_ac.json',
            issue_allowlist=[inline_id],
            plan_script=plan_s,
            worker_script=worker_s,
            review_script=review_s,
        )
        res = self._run_dispatch('tick', '--policy', str(pol), '--json')
        self.assertEqual(res.returncode, 0, msg=res.stderr + res.stdout)
        self.assertEqual(json.loads(res.stdout)['outcome'], 'candidate_ready')

        tbd_proc = self._bd(
            self.repo,
            '--sandbox',
            'create',
            'Inline TBD task',
            '-d',
            'Update allowed.txt\nAcceptance Criteria: TBD\n',
            '-p',
            '1',
            '-l',
            'low-risk',
            '--json',
        )
        self.assertEqual(tbd_proc.returncode, 0, msg=tbd_proc.stderr + tbd_proc.stdout)
        tbd_data = json.loads(tbd_proc.stdout)
        tbd_id = (tbd_data[0] if isinstance(tbd_data, list) else tbd_data)['id']
        pol_tbd = self._write_policy('inline_tbd.json', issue_allowlist=[tbd_id])
        dry = self._run_dispatch('dry-run', '--policy', str(pol_tbd), '--json')
        self.assertEqual(dry.returncode, 0, msg=dry.stderr + dry.stdout)
        dry_rep = json.loads(dry.stdout)
        self.assertEqual(dry_rep['outcome'], 'no_work')
        self.assertEqual(dry_rep['parked'][0]['reason'], 'ambiguous_acceptance_criteria')

        ml_proc = self._bd(
            self.repo,
            '--sandbox',
            'create',
            'Inline multiline two-bullet task',
            '-d',
            'Update allowed.txt\nAcceptance Criteria:\n- Criterion alpha\n- Criterion beta\n\n## Notes\nTrailing section\n',
            '-p',
            '1',
            '-l',
            'low-risk',
            '--json',
        )
        self.assertEqual(ml_proc.returncode, 0, msg=ml_proc.stderr + ml_proc.stdout)
        ml_data = json.loads(ml_proc.stdout)
        ml_id = (ml_data[0] if isinstance(ml_data, list) else ml_data)['id']
        expected_ml = '- Criterion alpha\n- Criterion beta'
        check_ml = f'assert inp["acceptance_criteria"] == {expected_ml!r}, repr(inp["acceptance_criteria"])\n'
        pol_ml = self._write_policy(
            'inline_ml.json',
            issue_allowlist=[ml_id],
            plan_script=(
                'import json, os\n'
                'inp = json.load(open(os.environ["DISPATCH_INPUT"], encoding="utf-8"))\n'
                + check_ml
                + 'print(json.dumps({"issue_id": inp["issue_id"], "run_id": inp["run_id"], '
                '"attempt": inp["attempt"], "base_sha": inp["base_sha"], "status": "ok", "steps": ["implement"]}))\n'
            ),
            worker_script=(
                'import json, os\n'
                'from pathlib import Path\n'
                'inp = json.load(open(os.environ["DISPATCH_INPUT"], encoding="utf-8"))\n'
                + check_ml
                + 'Path("/workspace/allowed.txt").write_text("updated\\n", encoding="utf-8")\n'
            ),
            review_script=(
                'import json, os\n'
                'inp = json.load(open(os.environ["DISPATCH_INPUT"], encoding="utf-8"))\n'
                + check_ml
                + 'print(json.dumps({"issue_id": inp["issue_id"], "run_id": inp["run_id"], "attempt": inp["attempt"], '
                '"candidate_sha": inp["candidate_sha"], "verdict": "pass", "findings": [], "evidence_refs": ["check:verify-allowed"]}))\n'
            ),
        )
        ml_res = self._run_dispatch('tick', '--policy', str(pol_ml), '--json')
        self.assertEqual(ml_res.returncode, 0, msg=ml_res.stderr + ml_res.stdout)
        self.assertEqual(json.loads(ml_res.stdout)['outcome'], 'candidate_ready')
        self.assertNotIn('Criterion alpha', ml_res.stdout)
        self.assertNotIn('Criterion beta', ml_res.stdout)

        empty_hdr_proc = self._bd(
            self.repo,
            '--sandbox',
            'create',
            'Inline empty header before heading',
            '-d',
            'Update allowed.txt\nAcceptance Criteria:   \n## Notes\nShould not be captured\n',
            '-p',
            '1',
            '-l',
            'low-risk',
            '--json',
        )
        self.assertEqual(empty_hdr_proc.returncode, 0, msg=empty_hdr_proc.stderr + empty_hdr_proc.stdout)
        eh_data = json.loads(empty_hdr_proc.stdout)
        eh_id = (eh_data[0] if isinstance(eh_data, list) else eh_data)['id']
        pol_eh = self._write_policy('inline_empty_hdr.json', issue_allowlist=[eh_id])
        eh_tick = self._run_dispatch('tick', '--policy', str(pol_eh), '--json')
        self.assertEqual(eh_tick.returncode, 0, msg=eh_tick.stderr + eh_tick.stdout)
        eh_rep = json.loads(eh_tick.stdout)
        self.assertEqual(eh_rep['outcome'], 'no_work')
        self.assertEqual(eh_rep['parked'][0]['reason'], 'missing_acceptance_criteria')
        self.assertEqual(self._show_issue(eh_id)['status'], 'open')

    def test_allowlist_selection_not_starved_past_default_ready_limit(self) -> None:
        parked_p0 = self._create_issue('Parked P0', priority=0, acceptance='TBD')
        unrelated_p1_ids = [self._create_issue(f'Unrelated P1 #{idx}', priority=1) for idx in range(12)]
        eligible_p2 = self._create_issue('Eligible P2', priority=2)
        eligible_p3 = self._create_issue('Eligible P3', priority=3)
        pol = self._write_policy('allowlist_order.json', issue_allowlist=[parked_p0, eligible_p3, eligible_p2])

        dry = self._run_dispatch('dry-run', '--policy', str(pol), '--json')
        self.assertEqual(dry.returncode, 0, msg=dry.stderr + dry.stdout)
        dry_rep = json.loads(dry.stdout)
        self.assertEqual(dry_rep['outcome'], 'selected')
        self.assertEqual(dry_rep['issue_id'], eligible_p2)
        self.assertEqual(dry_rep['parked'][0]['issue_id'], parked_p0)
        self.assertNotIn(dry_rep['issue_id'], unrelated_p1_ids)

        expected_ready_args = [
            '--readonly', '--sandbox', 'ready', '--limit', '0', '--max-rows', '10000', '--brief', '--json',
        ]
        wrapper = (
            'import importlib.machinery, importlib.util, json, sys\n'
            'loader = importlib.machinery.SourceFileLoader("pi_team_dispatch_cli", sys.argv[1])\n'
            'spec = importlib.util.spec_from_loader("pi_team_dispatch_cli", loader)\n'
            'mod = importlib.util.module_from_spec(spec)\n'
            'spec.loader.exec_module(mod)\n'
            'orig_run_bd = mod._run_bd\n'
            'orig_bound_op = mod._run_bound_bd_op\n'
            f'expected_ready = {expected_ready_args!r}\n'
            'host_ready_calls = 0\n'
            'bound_ready_calls = 0\n'
            'def guarded_run_bd(repo_root, args, **kwargs):\n'
            '    global host_ready_calls\n'
            '    assert "list" not in args[:4], f"unexpected bd list call: {args}"\n'
            '    if "ready" in args[:4]:\n'
            '        assert list(args) == expected_ready, f"unexpected bd ready call: {args}"\n'
            '        host_ready_calls += 1\n'
            '    return orig_run_bd(repo_root, args, **kwargs)\n'
            'def guarded_bound_op(**kwargs):\n'
            '    global bound_ready_calls\n'
            '    bd_args = list(kwargs.get("bd_args") or [])\n'
            '    assert "list" not in bd_args[:4], f"unexpected bound bd list call: {bd_args}"\n'
            '    if "ready" in bd_args[:4]:\n'
            '        assert bd_args == expected_ready, f"unexpected bound bd ready call: {bd_args}"\n'
            '        bound_ready_calls += 1\n'
            '    return orig_bound_op(**kwargs)\n'
            'mod._run_bd = guarded_run_bd\n'
            'mod._run_bound_bd_op = guarded_bound_op\n'
            'rc = mod.main(["tick", "--policy", sys.argv[2], "--json"])\n'
            'assert host_ready_calls == 1, f"expected 1 host advisory ready call, got {host_ready_calls}"\n'
            'assert bound_ready_calls == 1, f"expected 1 bound readiness call, got {bound_ready_calls}"\n'
            'sys.exit(rc)\n'
        )
        res = subprocess.run(
            [sys.executable, '-c', wrapper, str(DISPATCH_BIN), str(pol)],
            env=self.env, capture_output=True, text=True, timeout=45, check=False,
        )
        self.assertEqual(res.returncode, 0, msg=res.stderr + res.stdout)
        self.assertEqual(json.loads(res.stdout)['issue_id'], eligible_p2)

    def test_unrelated_ledger_write_proceeds_during_slow_tracker_selection(self) -> None:
        init_run = json.loads(self._run_ledger('start', 'init-seed', '--json').stdout)
        self.assertEqual(self._run_ledger('cancel', init_run['run_id'], 'admit', '--json').returncode, 0)

        issue_id = self._create_issue('Slow selection concurrency')
        pol = self._write_policy('slow_sel.json', issue_allowlist=[issue_id])
        sel_started = self.base / 'sel_started'
        ledger_done = self.base / 'ledger_done'

        slow_wrapper = (
            'import importlib.machinery, importlib.util, pathlib, sys, time\n'
            'loader = importlib.machinery.SourceFileLoader("pi_team_dispatch_cli", sys.argv[1])\n'
            'spec = importlib.util.spec_from_loader("pi_team_dispatch_cli", loader)\n'
            'mod = importlib.util.module_from_spec(spec)\n'
            'spec.loader.exec_module(mod)\n'
            'orig_run_bd = mod._run_bd\n'
            'started_flag = pathlib.Path(sys.argv[3])\n'
            'done_flag = pathlib.Path(sys.argv[4])\n'
            'slowed = False\n'
            'def slow_run_bd(repo_root, args, **kwargs):\n'
            '    global slowed\n'
            '    if not slowed and "ready" in args:\n'
            '        slowed = True\n'
            '        started_flag.write_text("1", encoding="utf-8")\n'
            '        deadline = time.monotonic() + 8.0\n'
            '        while not done_flag.exists() and time.monotonic() < deadline:\n'
            '            time.sleep(0.02)\n'
            '    return orig_run_bd(repo_root, args, **kwargs)\n'
            'mod._run_bd = slow_run_bd\n'
            'sys.exit(mod.main(["tick", "--policy", sys.argv[2], "--json"]))\n'
        )
        tick_proc = subprocess.Popen(
            [sys.executable, '-c', slow_wrapper, str(DISPATCH_BIN), str(pol), str(sel_started), str(ledger_done)],
            env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        try:
            deadline = time.monotonic() + 10.0
            while not sel_started.exists() and time.monotonic() < deadline:
                self.assertIsNone(tick_proc.poll())
                time.sleep(0.02)
            self.assertTrue(sel_started.exists(), 'dispatcher did not enter tracker selection')
            self.assertIsNone(tick_proc.poll())

            other = self._run_ledger('start', 'unrelated-repo-key', '--json')
            self.assertEqual(other.returncode, 0, msg=other.stderr + other.stdout)
            self.assertIsNone(tick_proc.poll())

            ledger_done.write_text('1', encoding='utf-8')
            out, err = tick_proc.communicate(timeout=30)
            self.assertEqual(tick_proc.returncode, 0, msg=err + out)
            self.assertEqual(json.loads(out)['outcome'], 'candidate_ready')
        finally:
            if tick_proc.poll() is None:
                tick_proc.kill()
                tick_proc.communicate(timeout=5)
            if tick_proc.stdout:
                tick_proc.stdout.close()
            if tick_proc.stderr:
                tick_proc.stderr.close()

    def test_bound_bd_claim_prevents_cross_path_swap_and_quarantines(self) -> None:
        issue_id = self._create_issue('Bound claim cross-path swap')
        pol = self._write_policy('bound_swap.json', issue_allowlist=[issue_id])
        beads_path = self.repo / '.beads'
        other_repo = self.base / 'other-repo'
        other_repo.mkdir()
        self._git(other_repo, 'init', '-b', 'main')
        other_beads = other_repo / '.beads'
        orig_bak = self.base / 'orig_beads_bak'
        shutil.copytree(beads_path, other_beads)

        swap_wrapper = (
            'import importlib.machinery, importlib.util, pathlib, sys\n'
            'loader = importlib.machinery.SourceFileLoader("pi_team_dispatch_cli", sys.argv[1])\n'
            'spec = importlib.util.spec_from_loader("pi_team_dispatch_cli", loader)\n'
            'mod = importlib.util.module_from_spec(spec)\n'
            'spec.loader.exec_module(mod)\n'
            'orig_bound_claim = mod._run_bound_bd_claim\n'
            'beads_p = pathlib.Path(sys.argv[3])\n'
            'other_p = pathlib.Path(sys.argv[4])\n'
            'bak_p = pathlib.Path(sys.argv[5])\n'
            'def swap_hook(**kwargs):\n'
            '    beads_p.rename(bak_p)\n'
            '    other_p.rename(beads_p)\n'
            '    return orig_bound_claim(**kwargs)\n'
            'mod._run_bound_bd_claim = swap_hook\n'
            'sys.exit(mod.main(["tick", "--policy", sys.argv[2], "--json"]))\n'
        )
        try:
            res = subprocess.run(
                [sys.executable, '-c', swap_wrapper, str(DISPATCH_BIN), str(pol), str(beads_path), str(other_beads), str(orig_bak)],
                env=self.env, capture_output=True, text=True, timeout=45, check=False,
            )
            self.assertNotEqual(res.returncode, 0)
            rep = json.loads(res.stdout)
            self.assertEqual(rep['outcome'], 'quarantined')
            self.assertEqual(rep['reason'], 'tracker_identity_mismatch_on_claim')
            self.assertEqual(rep['claim_retained'], 'unknown')

            db_path = self.xdg_state / 'pi-team-run' / 'state.db'
            with closing(sqlite3.connect(f'{db_path.resolve().as_uri()}?mode=ro', uri=True)) as conn:
                stage_count = conn.execute('SELECT count(*) FROM dispatch_stage_procs').fetchone()[0]
                self.assertEqual(stage_count, 0)
            self.assertNotEqual(self._run_ledger('start', str(self.repo)).returncode, 0)
        finally:
            if orig_bak.exists():
                if beads_path.exists():
                    beads_path.rename(other_beads)
                orig_bak.rename(beads_path)

        orig_issue = self._show_issue(issue_id)
        self.assertEqual(orig_issue['status'], 'in_progress')
        self.assertEqual(orig_issue['assignee'], rep['actor'])

        other_show = self._bd(other_repo, '--readonly', '--sandbox', 'show', issue_id, '--json')
        self.assertEqual(other_show.returncode, 0, msg=other_show.stderr)
        other_data = json.loads(other_show.stdout)
        other_issue = other_data[0] if isinstance(other_data, list) else other_data
        self.assertEqual(other_issue['status'], 'open')
        self.assertEqual((other_issue.get('assignee') or '').strip(), '')

    def test_ready_pin_loss_quarantines_even_on_ready_failure(self) -> None:
        mod = _load_dispatch_module()
        db_path = self.xdg_state / 'pi-team-run' / 'state.db'
        beads_path = self.repo / '.beads'
        for fail_ready in (False, True):
            iid = self._create_issue(f'Pin loss at ready fail={fail_ready}')
            pol = self._write_policy(f'pin_loss_ready_{int(fail_ready)}.json', issue_allowlist=[iid])
            with patch.dict(os.environ, self.env, clear=True):
                orig_ready = mod._bound_bd_ready_allowlist
                lost_bak = self.base / f'ready_loss_bak_{int(fail_ready)}'

                def ready_and_lose_pin(**kwargs):
                    res = orig_ready(**kwargs)
                    if beads_path.exists():
                        beads_path.rename(lost_bak)
                    if fail_ready:
                        raise mod.DispatchError('simulated ready failure after pin loss')
                    return res

                try:
                    with patch.object(mod, '_bound_bd_ready_allowlist', side_effect=ready_and_lose_pin):
                        rc, rep = mod.cmd_tick(SimpleNamespace(policy=str(pol), policy_sha256=None))
                finally:
                    if lost_bak.exists() and not beads_path.exists():
                        lost_bak.rename(beads_path)
                self.assertEqual((rc, rep['outcome'], rep['reason'], rep['claim_retained']), (1, 'quarantined', 'tracker_identity_mismatch_on_claim', 'unknown'))
                self.assertNotEqual(self._run_ledger('start', str(self.repo)).returncode, 0)
                with mod.open_dispatch_tx(db_path) as conn:
                    for tbl in ('dispatch_stage_procs', 'dispatch_runs', 'runs'):
                        conn.execute(f'DELETE FROM {tbl}')

    def test_unpinned_historical_active_row_quarantines_and_stays_reserved(self) -> None:
        issue_id = self._create_issue('Historical unpinned active row')
        pol_path = self._write_policy('unpinned_hist.json', issue_allowlist=[issue_id])
        mod = _load_dispatch_module()
        db_path = self.xdg_state / 'pi-team-run' / 'state.db'
        state_dir = self.xdg_state / 'pi-team-dispatch'
        mod.ensure_dispatch_dirs(state_dir)
        pol, pol_digest, pol_real = mod.load_and_validate_policy(str(pol_path), db_path=db_path, dispatch_state_dir=state_dir)
        run_id = 'disp-unpinned-01'
        actor = f'disp-test:{run_id}'
        self._bd(self.repo, '--sandbox', '--actor', actor, 'update', issue_id, '--claim', '--json')
        issue_data = self._show_issue(issue_id)
        spec_fp = mod._issue_spec_fingerprint(issue_data, pol_digest, self.base_sha)
        now_iso = mod.format_utc(mod.utc_now())
        with mod.open_dispatch_tx(db_path) as conn:
            conn.execute(
                "INSERT INTO runs (run_id, repo_key, status, current_stage, wait_generation, commit_only, no_ci, with_deploy, with_honcho, with_wiki, created_at, updated_at) VALUES (?, ?, 'active', 'admit', 0, 1, 0, 0, 0, 0, ?, ?)",
                (run_id, pol['repo_key'], now_iso, now_iso),
            )
            conn.execute(
                "INSERT INTO dispatch_runs (run_id, repo_key, repo_root, beads_dir, issue_id, actor, policy_path, policy_digest, base_sha, fingerprint, dispatch_state, attempt, max_attempts, spend_usd, max_spend_usd, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'claimed', 0, 2, 0.0, 0.0, ?, ?)",
                (run_id, pol['repo_key'], pol['repo_root'], str(self.repo / '.beads'), issue_id, actor, str(pol_real), pol_digest, self.base_sha, spec_fp, now_iso, now_iso),
            )

        res = self._run_dispatch('tick', '--policy', str(pol_path), '--json')
        self.assertNotEqual(res.returncode, 0)
        rep = json.loads(res.stdout)
        self.assertEqual(rep['outcome'], 'quarantined')
        self.assertEqual(rep['reason'], 'git_checkout_layout_mismatch')
        self.assertEqual(rep['claim_retained'], 'unknown')

        with closing(sqlite3.connect(f'{db_path.resolve().as_uri()}?mode=ro', uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute('SELECT * FROM dispatch_runs WHERE run_id = ?', (run_id,)).fetchone()
            self.assertIsNone(row['beads_db_path'])
            self.assertIsNone(row['beads_dir_ino'])
            self.assertIsNone(row['beads_db_ino'])
            self.assertIsNone(row['git_common_dir_dev'])
            self.assertIsNone(row['git_common_dir_ino'])
        self.assertNotEqual(self._run_ledger('start', str(self.repo)).returncode, 0)

    def test_second_stop_preserves_unresolved_quarantine_and_reservation(self) -> None:
        issue_id = self._create_issue('Second stop quarantine preservation')
        pol_path = self._write_policy('second_stop.json', issue_allowlist=[issue_id])
        mod = _load_dispatch_module()
        db_path = self.xdg_state / 'pi-team-run' / 'state.db'
        state_dir = self.xdg_state / 'pi-team-dispatch'
        mod.ensure_dispatch_dirs(state_dir)
        pol, pol_digest, pol_real = mod.load_and_validate_policy(str(pol_path), db_path=db_path, dispatch_state_dir=state_dir)
        tracker = mod._validate_local_beads_tracker(self.repo)
        run_id = 'disp-second-stop-01'
        actor = f'disp-test:{run_id}'
        self._bd(self.repo, '--sandbox', '--actor', actor, 'update', issue_id, '--claim', '--json')
        issue_data = self._show_issue(issue_id)
        spec_fp = mod._issue_spec_fingerprint(issue_data, pol_digest, self.base_sha)
        now_iso = mod.format_utc(mod.utc_now())
        with mod.open_dispatch_tx(db_path) as conn:
            conn.execute(
                "INSERT INTO runs (run_id, repo_key, status, current_stage, wait_generation, commit_only, no_ci, with_deploy, with_honcho, with_wiki, created_at, updated_at) VALUES (?, ?, 'active', 'admit', 0, 1, 0, 0, 0, 0, ?, ?)",
                (run_id, pol['repo_key'], now_iso, now_iso),
            )
            conn.execute(
                "INSERT INTO dispatch_runs (run_id, repo_key, repo_root, beads_dir, beads_db_path, beads_dir_dev, beads_dir_ino, beads_db_dev, beads_db_ino, git_common_dir_dev, git_common_dir_ino, issue_id, actor, policy_path, policy_digest, base_sha, fingerprint, dispatch_state, attempt, max_attempts, spend_usd, max_spend_usd, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'claiming', 0, 2, 0.0, 0.0, ?, ?)",
                (run_id, pol['repo_key'], pol['repo_root'], tracker['beads_dir'], tracker['beads_db_path'], tracker['beads_dir_dev'], tracker['beads_dir_ino'], tracker['beads_db_dev'], tracker['beads_db_ino'], *self._seed_git_pin(pol['repo_key']), issue_id, actor, str(pol_real), pol_digest, self.base_sha, spec_fp, now_iso, now_iso),
            )

        stop_fail_wrapper = (
            'import importlib.machinery, importlib.util, sys\n'
            'loader = importlib.machinery.SourceFileLoader("pi_team_dispatch_cli", sys.argv[1])\n'
            'spec = importlib.util.spec_from_loader("pi_team_dispatch_cli", loader)\n'
            'mod = importlib.util.module_from_spec(spec)\n'
            'spec.loader.exec_module(mod)\n'
            'orig_bound_readonly = mod._run_bound_bd_readonly\n'
            'def wrapped(**kwargs):\n'
            '    if kwargs.get("subcommand") == "show":\n'
            '        raise mod.DispatchError("bd show unavailable")\n'
            '    return orig_bound_readonly(**kwargs)\n'
            'mod._run_bound_bd_readonly = wrapped\n'
            'sys.exit(mod.main(["stop", "--run-id", sys.argv[2], "--json"]))\n'
        )
        r1 = subprocess.run(
            [sys.executable, '-c', stop_fail_wrapper, str(DISPATCH_BIN), run_id],
            env=self.env, capture_output=True, text=True, timeout=30, check=False,
        )
        self.assertNotEqual(r1.returncode, 0)
        rep1 = json.loads(r1.stdout)
        self.assertEqual(rep1['outcome'], 'quarantined')
        self.assertEqual(rep1['reason'], 'tracker_revalidation_failed')
        self.assertEqual(rep1['claim_retained'], 'unknown')

        r2 = subprocess.run(
            [sys.executable, '-c', stop_fail_wrapper, str(DISPATCH_BIN), run_id],
            env=self.env, capture_output=True, text=True, timeout=30, check=False,
        )
        self.assertNotEqual(r2.returncode, 0)
        rep2 = json.loads(r2.stdout)
        self.assertEqual(rep2['outcome'], 'quarantined')
        self.assertEqual(rep2['reason'], 'tracker_revalidation_failed')
        self.assertEqual(rep2['claim_retained'], 'unknown')
        self.assertTrue(mod._run_stop_path(state_dir, run_id).exists())
        self.assertNotEqual(self._run_ledger('start', str(self.repo)).returncode, 0)

        with mod.open_dispatch_tx(db_path) as conn:
            conn.execute(
                'UPDATE dispatch_runs SET report_json = ? WHERE run_id = ?',
                (json.dumps({'claim_retained': True}), run_id),
            )
        with patch.dict(os.environ, self.env, clear=True):
            rc_stale, rep_stale = mod.cmd_stop(SimpleNamespace(run_id=run_id, repo=None, policy=None, policy_sha256=None, reason='stale stop'))
        self.assertEqual((rc_stale, rep_stale['outcome'], rep_stale['claim_retained']), (1, 'quarantined', 'unknown'))
        self.assertNotEqual(self._run_ledger('start', str(self.repo)).returncode, 0)

        with mod.open_dispatch_tx(db_path) as conn:
            conn.execute("UPDATE dispatch_runs SET dispatch_state = 'working', outcome = NULL, reason = NULL WHERE run_id = ?", (run_id,))
            conn.execute(
                "INSERT INTO dispatch_stage_procs (run_id, attempt, stage, launch_token, status, created_at, updated_at) VALUES (?, 1, 'worker', 'tok', 'launching', ?, ?)",
                (run_id, now_iso, now_iso),
            )
        with patch.dict(os.environ, self.env, clear=True):
            rc_proc, rep_proc = mod.cmd_stop(SimpleNamespace(run_id=run_id, repo=None, policy=None, policy_sha256=None, reason='unproven proc'))
        self.assertEqual((rc_proc, rep_proc['outcome'], rep_proc['claim_retained']), (1, 'quarantined', 'unknown'))
        self.assertNotEqual(self._run_ledger('start', str(self.repo)).returncode, 0)

    def test_authority_checks_quarantine_on_tracker_drift_or_unreadable_across_stages(self) -> None:
        mod = _load_dispatch_module()
        db_path = self.xdg_state / 'pi-team-run' / 'state.db'
        state_dir = self.xdg_state / 'pi-team-dispatch'
        mod.ensure_dispatch_dirs(state_dir)

        plan_ok = (
            'import json, os\n'
            'inp = json.load(open(os.environ["DISPATCH_INPUT"], encoding="utf-8"))\n'
            'print(json.dumps({"issue_id": inp["issue_id"], "run_id": inp["run_id"], '
            '"attempt": inp["attempt"], "base_sha": inp["base_sha"], "status": "ok", "steps": ["implement"]}))\n'
        )
        for trigger_after, label in (
            ('claim_reval', 'before_planner'),
            ('plan', 'before_worker'),
            ('worker', 'before_checks'),
            ('check:verify-allowed', 'before_review'),
            ('review', 'before_finalization'),
        ):
            issue_id = self._create_issue(f'Authority failure {label}')
            pol = self._write_policy(f'auth_{label}.json', issue_allowlist=[issue_id], plan_script=plan_ok)
            wrapper = (
                'import importlib.machinery, importlib.util, sys\n'
                'loader = importlib.machinery.SourceFileLoader("pi_team_dispatch_cli", sys.argv[1])\n'
                'spec = importlib.util.spec_from_loader("pi_team_dispatch_cli", loader)\n'
                'mod = importlib.util.module_from_spec(spec)\n'
                'spec.loader.exec_module(mod)\n'
                'orig_bound_readonly = mod._run_bound_bd_readonly\n'
                'orig_run_stage = mod.BwrapRunner.run_stage\n'
                'orig_reval = mod._revalidate_active_authority\n'
                'trigger_after = sys.argv[3]\n'
                'armed = False\n'
                'def wrapped_bound_readonly(**kwargs):\n'
                '    if armed and kwargs.get("subcommand") == "show":\n'
                '        raise mod.DispatchError("unreadable tracker during authority check")\n'
                '    return orig_bound_readonly(**kwargs)\n'
                'def wrapped_reval(**kwargs):\n'
                '    global armed\n'
                '    res = orig_reval(**kwargs)\n'
                '    if trigger_after == "claim_reval":\n'
                '        armed = True\n'
                '    return res\n'
                'def wrapped_stage(self, **kwargs):\n'
                '    global armed\n'
                '    out = orig_run_stage(self, **kwargs)\n'
                '    if kwargs.get("stage") == trigger_after:\n'
                '        armed = True\n'
                '    return out\n'
                'mod._run_bound_bd_readonly = wrapped_bound_readonly\n'
                'mod._revalidate_active_authority = wrapped_reval\n'
                'mod.BwrapRunner.run_stage = wrapped_stage\n'
                'sys.exit(mod.main(["tick", "--policy", sys.argv[2], "--json"]))\n'
            )
            res = subprocess.run(
                [sys.executable, '-c', wrapper, str(DISPATCH_BIN), str(pol), trigger_after],
                env=self.env, capture_output=True, text=True, timeout=45, check=False,
            )
            self.assertNotEqual(res.returncode, 0, msg=f'{label}: {res.stdout}')
            rep = json.loads(res.stdout)
            self.assertEqual(rep['outcome'], 'quarantined', msg=f'{label}: {rep}')
            self.assertEqual(rep['reason'], 'tracker_revalidation_failed', msg=f'{label}: {rep}')
            self.assertEqual(rep['claim_retained'], 'unknown', msg=f'{label}: {rep}')
            self.assertNotEqual(self._run_ledger('start', str(self.repo)).returncode, 0, msg=label)
            with mod.open_dispatch_tx(db_path) as conn:
                conn.execute('DELETE FROM dispatch_stage_procs')
                conn.execute('DELETE FROM dispatch_runs')
                conn.execute('DELETE FROM runs')

        drift_issue = self._create_issue('Tracker inode drift after check stage')
        pol_drift = self._write_policy('auth_drift.json', issue_allowlist=[drift_issue], plan_script=plan_ok)
        emb_path = self.repo / '.beads' / 'embeddeddolt'
        emb_bak = self.base / 'emb_drift_bak'
        drift_wrapper = (
            'import importlib.machinery, importlib.util, pathlib, shutil, sys\n'
            'loader = importlib.machinery.SourceFileLoader("pi_team_dispatch_cli", sys.argv[1])\n'
            'spec = importlib.util.spec_from_loader("pi_team_dispatch_cli", loader)\n'
            'mod = importlib.util.module_from_spec(spec)\n'
            'spec.loader.exec_module(mod)\n'
            'orig_run_stage = mod.BwrapRunner.run_stage\n'
            'emb_p = pathlib.Path(sys.argv[3])\n'
            'bak_p = pathlib.Path(sys.argv[4])\n'
            'def wrapped_stage(self, **kwargs):\n'
            '    out = orig_run_stage(self, **kwargs)\n'
            '    if kwargs.get("stage") == "check:verify-allowed":\n'
            '        copy_p = emb_p.parent / "embeddeddolt.drift"\n'
            '        shutil.copytree(emb_p, copy_p)\n'
            '        emb_p.rename(bak_p)\n'
            '        copy_p.rename(emb_p)\n'
            '    return out\n'
            'mod.BwrapRunner.run_stage = wrapped_stage\n'
            'sys.exit(mod.main(["tick", "--policy", sys.argv[2], "--json"]))\n'
        )
        try:
            d_res = subprocess.run(
                [sys.executable, '-c', drift_wrapper, str(DISPATCH_BIN), str(pol_drift), str(emb_path), str(emb_bak)],
                env=self.env, capture_output=True, text=True, timeout=45, check=False,
            )
            self.assertNotEqual(d_res.returncode, 0)
            d_rep = json.loads(d_res.stdout)
            self.assertEqual(d_rep['outcome'], 'quarantined')
            self.assertEqual(d_rep['reason'], 'tracker_identity_mismatch')
            self.assertEqual(d_rep['claim_retained'], 'unknown')
            self.assertNotEqual(self._run_ledger('start', str(self.repo)).returncode, 0)
        finally:
            if emb_bak.exists():
                shutil.rmtree(emb_path, ignore_errors=True)
                emb_bak.rename(emb_path)

    def test_alternate_repo_sharing_base_commit_cannot_claim_other_tracker_while_worktree_works(self) -> None:
        issue_id = self._create_issue('Alternate repo vs supported worktree')
        alt_repo = self.base / 'alt-repo'
        self._git(self.base, 'clone', str(self.repo), str(alt_repo))
        self.assertEqual(self._git(alt_repo, 'rev-parse', 'HEAD').stdout.strip(), self.base_sha)

        pol_alt = self._write_policy('alt_repo.json', repo=alt_repo, issue_allowlist=[issue_id])
        alt_res = self._run_dispatch('tick', '--policy', str(pol_alt), '--json')
        self.assertNotEqual(alt_res.returncode, 0)
        self.assertEqual(self._show_issue(issue_id)['status'], 'open')

        init_alt = self._bd(alt_repo, 'init', '--sandbox', '--stealth', '--skip-agents', '--skip-hooks', '--prefix', 'alt')
        self.assertEqual(init_alt.returncode, 0, msg=init_alt.stderr + init_alt.stdout)
        alt_res2 = self._run_dispatch('tick', '--policy', str(pol_alt), '--json')
        self.assertEqual(alt_res2.returncode, 0, msg=alt_res2.stderr + alt_res2.stdout)
        self.assertEqual(json.loads(alt_res2.stdout)['outcome'], 'no_work')
        self.assertEqual(self._show_issue(issue_id)['status'], 'open')

        pol_wt = self._write_policy('supported_wt.json', repo=self.worktree, issue_allowlist=[issue_id])
        wt_res = self._run_dispatch('tick', '--policy', str(pol_wt), '--json')
        self.assertEqual(wt_res.returncode, 0, msg=wt_res.stderr + wt_res.stdout)
        wt_rep = json.loads(wt_res.stdout)
        self.assertEqual(wt_rep['outcome'], 'candidate_ready')
        self.assertEqual(wt_rep['issue_id'], issue_id)
        self.assertEqual(self._show_issue(issue_id)['status'], 'in_progress')

    def test_pre_go_stop_marker_denies_claim_without_late_write(self) -> None:
        db_path = self.xdg_state / 'pi-team-run' / 'state.db'
        state_dir = self.xdg_state / 'pi-team-dispatch'
        store_dir = (
            state_dir
            / 'git-store'
            / f'{sha256(str((self.repo / ".git").resolve()).encode()).hexdigest()[:16]}.git'
        )
        wrapper = (
            'from contextlib import closing\n'
            'import importlib.machinery, importlib.util, json, pathlib, sqlite3, subprocess, sys, time\n'
            'dispatch_bin, policy_path, selector_mode, repo_path, journal_file = sys.argv[1:6]\n'
            'loader = importlib.machinery.SourceFileLoader("pi_team_dispatch_cli", dispatch_bin)\n'
            'spec = importlib.util.spec_from_loader("pi_team_dispatch_cli", loader)\n'
            'mod = importlib.util.module_from_spec(spec)\n'
            'spec.loader.exec_module(mod)\n'
            'orig_verify = mod._verify_bwrap_pid1_identity\n'
            'orig_run_stage = mod.BwrapRunner.run_stage\n'
            'orig_bound_claim = mod._run_bound_bd_claim\n'
            'orig_run_bd = mod._run_bd\n'
            'events = []\n'
            'stop_proc = None\n'
            'hook_fired = False\n'
            'def wrapped_run_bd(repo_root, args, **kwargs):\n'
            '    events.append(["host_bd", list(args)])\n'
            '    return orig_run_bd(repo_root, args, **kwargs)\n'
            'def wrapped_run_stage(self, **kwargs):\n'
            '    events.append(["run_stage", kwargs.get("stage")])\n'
            '    return orig_run_stage(self, **kwargs)\n'
            'def wrapped_bound_claim(**kwargs):\n'
            '    events.append(["bound_claim", kwargs.get("run_id"), kwargs.get("issue_id")])\n'
            '    return orig_bound_claim(**kwargs)\n'
            'def wrapped_verify(proc, info_obj, *, label, **kwargs):\n'
            '    global stop_proc, hook_fired\n'
            '    verified = orig_verify(proc, info_obj, label=label, **kwargs)\n'
            '    if label == "bound bd claim" and not hook_fired:\n'
            '        hook_fired = True\n'
            '        db_p = mod.resolve_state_db_path()\n'
            '        state_d = mod.resolve_dispatch_state_dir()\n'
            '        with closing(sqlite3.connect(f"{db_p.resolve().as_uri()}?mode=ro", uri=True)) as conn:\n'
            '            conn.row_factory = sqlite3.Row\n'
            '            row = conn.execute(\n'
            '                "SELECT run_id, repo_key FROM dispatch_runs WHERE dispatch_state = \'claiming\' ORDER BY created_at DESC LIMIT 1"\n'
            '            ).fetchone()\n'
            '        assert row is not None, "missing claiming dispatch_runs row at bound bd claim boundary"\n'
            '        run_id = row["run_id"]\n'
            '        repo_key = row["repo_key"]\n'
            '        run_marker = mod._run_stop_path(state_d, run_id)\n'
            '        repo_marker = mod._repo_stop_path(state_d, repo_key)\n'
            '        expected_marker = run_marker if selector_mode == "run_id" else repo_marker\n'
            '        stop_args = ["--run-id", run_id] if selector_mode == "run_id" else ["--repo", repo_path]\n'
            '        stop_proc = subprocess.Popen(\n'
            '            [sys.executable, dispatch_bin, "stop", *stop_args, "--reason", f"pre-go-{selector_mode}-stop", "--json"],\n'
            '            stdin=subprocess.DEVNULL,\n'
            '            stdout=subprocess.PIPE,\n'
            '            stderr=subprocess.PIPE,\n'
            '            text=True,\n'
            '        )\n'
            '        wait_deadline = time.monotonic() + 10.0\n'
            '        while time.monotonic() < wait_deadline:\n'
            '            markers_ready = run_marker.exists() and (selector_mode != "repo" or repo_marker.exists())\n'
            '            stop_persisted = False\n'
            '            if markers_ready:\n'
            '                try:\n'
            '                    with closing(sqlite3.connect(f"{db_p.resolve().as_uri()}?mode=ro", uri=True, timeout=0.5)) as conn:\n'
            '                        conn.execute("PRAGMA busy_timeout = 500")\n'
            '                        srow = conn.execute("SELECT stop_requested FROM dispatch_runs WHERE run_id = ?", (run_id,)).fetchone()\n'
            '                        stop_persisted = bool(srow and srow[0])\n'
            '                except sqlite3.OperationalError:\n'
            '                    stop_persisted = False\n'
            '            if markers_ready and (stop_persisted or stop_proc.poll() is not None):\n'
            '                break\n'
            '            if stop_proc.poll() is not None:\n'
            '                out, err = stop_proc.communicate(timeout=5)\n'
            '                raise AssertionError(f"stop exited early ({stop_proc.returncode}) before marker persisted: {err or out}")\n'
            '            time.sleep(0.02)\n'
            '        assert expected_marker.exists(), f"stop marker missing before hook return: {expected_marker}"\n'
            '        assert run_marker.exists(), f"run stop marker missing before hook return: {run_marker}"\n'
            '        events.append(["hook_bound_bd_claim", run_id, verified[0], str(expected_marker), expected_marker.exists(), run_marker.exists()])\n'
            '    return verified\n'
            'mod._run_bd = wrapped_run_bd\n'
            'mod.BwrapRunner.run_stage = wrapped_run_stage\n'
            'mod._run_bound_bd_claim = wrapped_bound_claim\n'
            'mod._verify_bwrap_pid1_identity = wrapped_verify\n'
            'rc = 1\n'
            'try:\n'
            '    rc = mod.main(["tick", "--policy", policy_path, "--json"])\n'
            'finally:\n'
            '    if stop_proc is not None:\n'
            '        try:\n'
            '            stop_out, stop_err = stop_proc.communicate(timeout=15)\n'
            '            events.append(["stop_proc", stop_proc.returncode, stop_out.strip(), stop_err.strip()])\n'
            '        except Exception as exc:\n'
            '            if stop_proc.poll() is None:\n'
            '                stop_proc.kill()\n'
            '                stop_proc.communicate(timeout=5)\n'
            '            events.append(["stop_proc_err", repr(exc)])\n'
            '    pathlib.Path(journal_file).write_text(json.dumps(events), encoding="utf-8")\n'
            'sys.exit(rc)\n'
        )
        for selector_mode, title, pol_name in (
            ('run_id', 'Pre-GO run-id stop denies claim', 'stop_pre_go_run.json'),
            ('repo', 'Pre-GO repo stop denies claim', 'stop_pre_go_repo.json'),
        ):
            issue_id = self._create_issue(title)
            pol = self._write_policy(pol_name, issue_allowlist=[issue_id])
            journal = self.base / f'pre_go_stop_{selector_mode}.json'
            res = subprocess.run(
                [sys.executable, '-c', wrapper, str(DISPATCH_BIN), str(pol), selector_mode, str(self.repo), str(journal)],
                env=self.env, capture_output=True, text=True, timeout=45, check=False,
            )
            self.assertEqual(res.returncode, 1, msg=f'{selector_mode}: {res.stderr}\n{res.stdout}')
            rep = json.loads(res.stdout)
            run_id = rep['run_id']
            self.assertEqual(rep['outcome'], 'cancelled', msg=rep)
            self.assertEqual(rep['reason'], 'stop_requested', msg=rep)
            self.assertIs(rep['claim_retained'], False, msg=rep)
            self.assertIsNone(rep.get('candidate_sha'), msg=rep)
            self.assertEqual(rep.get('attempt'), 0, msg=rep)

            events = json.loads(journal.read_text(encoding='utf-8'))
            hook_events = [e for e in events if e[0] == 'hook_bound_bd_claim']
            self.assertEqual(len(hook_events), 1, msg=events)
            self.assertEqual(hook_events[0][1], run_id, msg=events)
            self.assertGreater(hook_events[0][2], 1, msg=events)
            self.assertTrue(hook_events[0][4], msg=events)
            self.assertTrue(hook_events[0][5], msg=events)
            self.assertEqual(sum(1 for e in events if e[0] == 'bound_claim'), 1, msg=events)
            self.assertEqual([e for e in events if e[0] == 'run_stage'], [], msg=events)
            self.assertFalse(any(e[0] == 'host_bd' and '--claim' in e[1] for e in events), msg=events)
            stop_events = [e for e in events if e[0] == 'stop_proc']
            self.assertEqual(len(stop_events), 1, msg=events)
            self.assertEqual(stop_events[0][1], 0, msg=events)
            stop_rep = json.loads(stop_events[0][2])
            self.assertIn(stop_rep['outcome'], ('cancelled', 'stop_requested'), msg=stop_rep)

            with closing(sqlite3.connect(f'{db_path.resolve().as_uri()}?mode=ro', uri=True)) as conn:
                conn.row_factory = sqlite3.Row
                drows = conn.execute('SELECT * FROM dispatch_runs WHERE issue_id = ?', (issue_id,)).fetchall()
                self.assertEqual(len(drows), 1)
                drow = drows[0]
                self.assertEqual(drow['run_id'], run_id)
                self.assertEqual(drow['dispatch_state'], 'cancelled')
                self.assertEqual(drow['outcome'], 'cancelled')
                self.assertEqual(drow['reason'], 'stop_requested')
                self.assertEqual(drow['stop_requested'], 1)
                self.assertEqual(drow['attempt'], 0)
                self.assertIsNone(drow['candidate_sha'])
                self.assertIsNone(drow['checks_json'])
                self.assertIsNone(drow['review_json'])
                stage_count = conn.execute('SELECT count(*) FROM dispatch_stage_procs WHERE run_id = ?', (run_id,)).fetchone()[0]
                self.assertEqual(stage_count, 0)

            if store_dir.exists():
                refs = subprocess.run(
                    ['git', '-C', str(store_dir), 'for-each-ref', f'refs/dispatch/candidates/{run_id}'],
                    env=self.env, capture_output=True, text=True, check=True, timeout=15,
                ).stdout.strip()
                self.assertEqual(refs, '')

            issue_after_tick = self._show_issue(issue_id)
            self.assertEqual(issue_after_tick['status'], 'open')
            self.assertEqual((issue_after_tick.get('assignee') or '').strip(), '')

            rec_res = self._run_dispatch('tick', '--policy', str(pol), '--json')
            expected_rec_rc = 0 if selector_mode == 'run_id' else 1
            self.assertEqual(rec_res.returncode, expected_rec_rc, msg=rec_res.stderr + rec_res.stdout)
            rec_rep = json.loads(rec_res.stdout)
            if selector_mode == 'run_id':
                self.assertEqual(rec_rep['outcome'], 'no_work', msg=rec_rep)
                self.assertIn(issue_id, rec_rep['skipped_unchanged'], msg=rec_rep)
            else:
                self.assertEqual(rec_rep['outcome'], 'cancelled', msg=rec_rep)
                self.assertEqual(rec_rep['reason'], 'repo_stop_marker_active', msg=rec_rep)

            with closing(sqlite3.connect(f'{db_path.resolve().as_uri()}?mode=ro', uri=True)) as conn:
                self.assertEqual(conn.execute('SELECT count(*) FROM dispatch_runs WHERE issue_id = ?', (issue_id,)).fetchone()[0], 1)
                self.assertEqual(conn.execute('SELECT count(*) FROM dispatch_stage_procs WHERE run_id = ?', (run_id,)).fetchone()[0], 0)

            issue_after_rec = self._show_issue(issue_id)
            self.assertEqual(issue_after_rec['status'], 'open')
            self.assertEqual((issue_after_rec.get('assignee') or '').strip(), '')
            self.assertEqual(self._git(self.repo, 'status', '--porcelain').stdout.strip(), '')
            self.assertEqual((self.repo / 'allowed.txt').read_text(encoding='utf-8'), 'initial\n')

    def test_pre_go_absolute_deadline_denies_claim_without_reset_or_late_write(self) -> None:
        db_path = self.xdg_state / 'pi-team-run' / 'state.db'
        state_dir = self.xdg_state / 'pi-team-dispatch'
        store_dir = (
            state_dir
            / 'git-store'
            / f'{sha256(str((self.repo / ".git").resolve()).encode()).hexdigest()[:16]}.git'
        )
        issue_id = self._create_issue('Pre-GO absolute deadline denies claim')
        pol = self._write_policy('pre_go_deadline.json', issue_allowlist=[issue_id], run_sec=30)
        journal = self.base / 'pre_go_deadline.json'
        wrapper = (
            'from contextlib import closing\n'
            'from datetime import timedelta\n'
            'import importlib.machinery, importlib.util, json, pathlib, sqlite3, sys\n'
            'dispatch_bin, policy_path, journal_file = sys.argv[1:4]\n'
            'loader = importlib.machinery.SourceFileLoader("pi_team_dispatch_cli", dispatch_bin)\n'
            'spec = importlib.util.spec_from_loader("pi_team_dispatch_cli", loader)\n'
            'mod = importlib.util.module_from_spec(spec)\n'
            'spec.loader.exec_module(mod)\n'
            'orig_utc_now = mod.utc_now\n'
            'clock = [orig_utc_now()]\n'
            'def deterministic_now():\n'
            '    return clock[0]\n'
            'mod.utc_now = deterministic_now\n'
            'mod.PTR.utc_now = deterministic_now\n'
            'orig_verify = mod._verify_bwrap_pid1_identity\n'
            'orig_run_stage = mod.BwrapRunner.run_stage\n'
            'orig_bound_claim = mod._run_bound_bd_claim\n'
            'orig_run_bd = mod._run_bd\n'
            'events = []\n'
            'hook_fired = False\n'
            'def wrapped_run_bd(repo_root, args, **kwargs):\n'
            '    events.append(["host_bd", list(args)])\n'
            '    return orig_run_bd(repo_root, args, **kwargs)\n'
            'def wrapped_run_stage(self, **kwargs):\n'
            '    events.append(["run_stage", kwargs.get("stage")])\n'
            '    return orig_run_stage(self, **kwargs)\n'
            'def wrapped_bound_claim(**kwargs):\n'
            '    events.append(["bound_claim", kwargs.get("run_id"), kwargs.get("issue_id")])\n'
            '    return orig_bound_claim(**kwargs)\n'
            'def wrapped_verify(proc, info_obj, *, label, **kwargs):\n'
            '    global hook_fired\n'
            '    verified = orig_verify(proc, info_obj, label=label, **kwargs)\n'
            '    if label == "bound bd claim" and not hook_fired:\n'
            '        hook_fired = True\n'
            '        db_p = mod.resolve_state_db_path()\n'
            '        with closing(sqlite3.connect(f"{db_p.resolve().as_uri()}?mode=ro", uri=True)) as conn:\n'
            '            conn.row_factory = sqlite3.Row\n'
            '            row = conn.execute(\n'
            '                "SELECT run_id, deadline_at FROM dispatch_runs WHERE dispatch_state = \'claiming\' ORDER BY created_at DESC LIMIT 1"\n'
            '            ).fetchone()\n'
            '        assert row is not None and row["deadline_at"], "missing stored deadline_at at bound bd claim boundary"\n'
            '        stored_deadline_dt = mod.PTR.parse_iso_utc(row["deadline_at"])\n'
            '        assert stored_deadline_dt > clock[0], f"expected future stored deadline, got {row[\'deadline_at\']} vs {clock[0]}"\n'
            '        clock[0] = stored_deadline_dt + timedelta(seconds=5)\n'
            '        events.append(["hook_bound_bd_claim", row["run_id"], verified[0], row["deadline_at"], mod.format_utc(clock[0])])\n'
            '    return verified\n'
            'mod._run_bd = wrapped_run_bd\n'
            'mod.BwrapRunner.run_stage = wrapped_run_stage\n'
            'mod._run_bound_bd_claim = wrapped_bound_claim\n'
            'mod._verify_bwrap_pid1_identity = wrapped_verify\n'
            'rc = 1\n'
            'try:\n'
            '    rc = mod.main(["tick", "--policy", policy_path, "--json"])\n'
            'finally:\n'
            '    pathlib.Path(journal_file).write_text(json.dumps(events), encoding="utf-8")\n'
            'sys.exit(rc)\n'
        )
        res = subprocess.run(
            [sys.executable, '-c', wrapper, str(DISPATCH_BIN), str(pol), str(journal)],
            env=self.env, capture_output=True, text=True, timeout=45, check=False,
        )
        self.assertEqual(res.returncode, 1, msg=res.stderr + res.stdout)
        rep = json.loads(res.stdout)
        run_id = rep['run_id']
        self.assertEqual(rep['outcome'], 'blocked', msg=rep)
        self.assertEqual(rep['reason'], 'run_timeout_exceeded', msg=rep)
        self.assertIs(rep['claim_retained'], False, msg=rep)
        self.assertIsNone(rep.get('candidate_sha'), msg=rep)
        self.assertEqual(rep.get('attempt'), 0, msg=rep)

        events = json.loads(journal.read_text(encoding='utf-8'))
        hook_events = [e for e in events if e[0] == 'hook_bound_bd_claim']
        self.assertEqual(len(hook_events), 1, msg=events)
        self.assertEqual(hook_events[0][1], run_id, msg=events)
        self.assertGreater(hook_events[0][2], 1, msg=events)
        original_deadline = hook_events[0][3]
        self.assertEqual(sum(1 for e in events if e[0] == 'bound_claim'), 1, msg=events)
        self.assertEqual([e for e in events if e[0] == 'run_stage'], [], msg=events)
        self.assertFalse(any(e[0] == 'host_bd' and '--claim' in e[1] for e in events), msg=events)

        with closing(sqlite3.connect(f'{db_path.resolve().as_uri()}?mode=ro', uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            drows = conn.execute('SELECT * FROM dispatch_runs WHERE issue_id = ?', (issue_id,)).fetchall()
            self.assertEqual(len(drows), 1)
            drow = drows[0]
            self.assertEqual(drow['run_id'], run_id)
            self.assertEqual(drow['dispatch_state'], 'blocked')
            self.assertEqual(drow['outcome'], 'blocked')
            self.assertEqual(drow['reason'], 'run_timeout_exceeded')
            self.assertEqual(drow['deadline_at'], original_deadline)
            self.assertEqual(drow['attempt'], 0)
            self.assertIsNone(drow['candidate_sha'])
            self.assertIsNone(drow['checks_json'])
            self.assertIsNone(drow['review_json'])
            stage_count = conn.execute('SELECT count(*) FROM dispatch_stage_procs WHERE run_id = ?', (run_id,)).fetchone()[0]
            self.assertEqual(stage_count, 0)

        if store_dir.exists():
            refs = subprocess.run(
                ['git', '-C', str(store_dir), 'for-each-ref', f'refs/dispatch/candidates/{run_id}'],
                env=self.env, capture_output=True, text=True, check=True, timeout=15,
            ).stdout.strip()
            self.assertEqual(refs, '')

        issue_after_tick = self._show_issue(issue_id)
        self.assertEqual(issue_after_tick['status'], 'open')
        self.assertEqual((issue_after_tick.get('assignee') or '').strip(), '')

        rec_res = self._run_dispatch('tick', '--policy', str(pol), '--json')
        self.assertEqual(rec_res.returncode, 0, msg=rec_res.stderr + rec_res.stdout)
        rec_rep = json.loads(rec_res.stdout)
        self.assertEqual(rec_rep['outcome'], 'no_work', msg=rec_rep)
        self.assertIn(issue_id, rec_rep['skipped_unchanged'], msg=rec_rep)

        with closing(sqlite3.connect(f'{db_path.resolve().as_uri()}?mode=ro', uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            drows_rec = conn.execute('SELECT * FROM dispatch_runs WHERE issue_id = ?', (issue_id,)).fetchall()
            self.assertEqual(len(drows_rec), 1)
            self.assertEqual(drows_rec[0]['deadline_at'], original_deadline)
            self.assertEqual(conn.execute('SELECT count(*) FROM dispatch_stage_procs WHERE run_id = ?', (run_id,)).fetchone()[0], 0)

        issue_after_rec = self._show_issue(issue_id)
        self.assertEqual(issue_after_rec['status'], 'open')
        self.assertEqual((issue_after_rec.get('assignee') or '').strip(), '')
        self.assertEqual(self._git(self.repo, 'status', '--porcelain').stdout.strip(), '')
        self.assertEqual((self.repo / 'allowed.txt').read_text(encoding='utf-8'), 'initial\n')

    def test_post_claim_active_retention_and_quarantine_cases(self) -> None:
        mod = _load_dispatch_module()
        db_path = self.xdg_state / 'pi-team-run' / 'state.db'
        state_dir = self.xdg_state / 'pi-team-dispatch'
        orig_bound_show, orig_bound_ro = mod._bound_bd_show, mod._run_bound_bd_readonly

        def seed_active(run_id: str, issue_id: str, pol_path: Path, state: str, *, expired: bool, incomplete_pin: bool) -> tuple[dict, str, str]:
            pol, pol_digest, pol_real = mod.load_and_validate_policy(str(pol_path), db_path=db_path, dispatch_state_dir=state_dir)
            tracker = mod._validate_local_beads_tracker(self.repo)
            actor = f'disp-test:{run_id}'
            claim = self._bd(self.repo, '--sandbox', '--actor', actor, 'update', issue_id, '--claim', '--json')
            self.assertEqual(claim.returncode, 0, msg=claim.stderr + claim.stdout)
            spec_fp = mod._issue_spec_fingerprint(self._show_issue(issue_id), pol_digest, self.base_sha)
            store_dir = mod._sync_base_to_store(state_dir, pol['repo_key'], Path(pol['repo_root']), self.base_sha)
            with tempfile.TemporaryDirectory(dir=state_dir / 'scratch', prefix=f'{run_id}-seed-') as seed_tmp:
                mat_ws = Path(seed_tmp) / 'ws'
                mod._materialize_commit(store_dir, self.base_sha, mat_ws)
                (mat_ws / 'allowed.txt').write_text('updated\n', encoding='utf-8')
                cand_sha, _ = mod._validate_and_commit_candidate(
                    store_dir=store_dir, scratch_dir=Path(seed_tmp), run_id=run_id, attempt=1, base_sha=self.base_sha, worker_dir=mat_ws, allowed_paths=pol['allowed_paths'], allowed_ops=pol['allowed_ops'],
                )
            now_dt = mod.utc_now()
            now_iso, deadline_iso = mod.format_utc(now_dt), mod.format_utc(now_dt + timedelta(seconds=-10 if expired else 60))
            with mod.open_dispatch_tx(db_path) as conn:
                for tbl in ('dispatch_stage_procs', 'dispatch_runs', 'runs'):
                    conn.execute(f'DELETE FROM {tbl}')
                conn.execute(
                    "INSERT INTO runs (run_id, repo_key, status, current_stage, wait_generation, commit_only, no_ci, with_deploy, with_honcho, with_wiki, created_at, updated_at) VALUES (?, ?, 'active', 'admit', 0, 1, 0, 0, 0, 0, ?, ?)",
                    (run_id, pol['repo_key'], now_iso, now_iso),
                )
                conn.execute(
                    "INSERT INTO dispatch_runs (run_id, repo_key, repo_root, beads_dir, beads_db_path, beads_dir_dev, beads_dir_ino, beads_db_dev, beads_db_ino, git_common_dir_dev, git_common_dir_ino, issue_id, actor, policy_path, policy_digest, base_sha, candidate_sha, fingerprint, dispatch_state, attempt, max_attempts, spend_usd, max_spend_usd, deadline_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 2, 0.0, 0.0, ?, ?, ?)",
                    (run_id, pol['repo_key'], pol['repo_root'], tracker['beads_dir'], None if incomplete_pin else tracker['beads_db_path'], tracker['beads_dir_dev'], None if incomplete_pin else tracker['beads_dir_ino'], tracker['beads_db_dev'], None if incomplete_pin else tracker['beads_db_ino'], *self._seed_git_pin(pol['repo_key']), issue_id, actor, str(pol_real), pol_digest, self.base_sha, cand_sha, spec_fp, state, deadline_iso, now_iso, now_iso),
                )
            return pol, actor, cand_sha

        cases = [
            ('stop_checking', 'checking', False, False, False, False, 'stop', 0, 'cancelled', 'stopped:halt active', True, 'cancelled', 'cancelled'),
            ('expired_reviewing', 'reviewing', True, False, False, False, 'tick', 1, 'blocked', 'run_timeout_exceeded', True, 'blocked', 'cancelled'),
            ('incomplete_pin_checking', 'checking', False, True, False, False, 'tick', 1, 'quarantined', 'tracker_identity_mismatch', 'unknown', 'quarantined', 'active'),
            ('incomplete_pin_stop', 'reviewing', False, True, False, False, 'stop', 1, 'quarantined', 'tracker_identity_mismatch', 'unknown', 'quarantined', 'active'),
            ('unavail_tracker_reviewing', 'reviewing', False, False, True, False, 'tick', 1, 'quarantined', 'tracker_revalidation_failed', 'unknown', 'quarantined', 'active'),
            ('missing_tracker_reviewing', 'reviewing', False, False, False, True, 'tick', 1, 'quarantined', 'tracker_identity_mismatch', 'unknown', 'quarantined', 'active'),
        ]
        with patch.dict(os.environ, self.env, clear=True):
            mod.ensure_dispatch_dirs(state_dir)
            for name, state, expired, incomplete_pin, unavail_tracker, missing_tracker, op, exp_rc, exp_out, exp_reason, exp_ret, exp_dstate, exp_rstat in cases:
                issue_id = self._create_issue(f'Post-claim {name}')
                pol_path = self._write_policy(f'{name}.json', issue_allowlist=[issue_id])
                run_id = f'disp-post-{name}'
                pol, actor, cand_sha = seed_active(run_id, issue_id, pol_path, state, expired=expired, incomplete_pin=incomplete_pin)
                beads_path = self.repo / '.beads'
                missing_bak = self.base / f'{name}_beads_bak'
                try:
                    def maybe_fail_ro(**kwargs):
                        if unavail_tracker and kwargs.get('subcommand') == 'show':
                            raise mod.DispatchError('bd show unavailable')
                        return orig_bound_ro(**kwargs)

                    with (
                        patch.object(mod, '_validate_local_beads_tracker') as m_validate_tracker,
                        patch.object(mod, '_preselect_candidate') as m_presel,
                        patch.object(mod, '_bd_show') as m_host_show,
                        patch.object(mod, '_run_bound_bd_claim') as m_claim,
                        patch.object(mod, '_bound_bd_ready_allowlist') as m_ready,
                        patch.object(mod.BwrapRunner, 'run_stage') as m_stage,
                        patch.object(mod, '_bound_bd_show', wraps=orig_bound_show) as m_bshow,
                        patch.object(mod, '_run_bound_bd_readonly', side_effect=maybe_fail_ro),
                    ):
                        if missing_tracker:
                            beads_path.rename(missing_bak)
                        try:
                            if op == 'stop':
                                rc, rep = mod.cmd_stop(SimpleNamespace(run_id=run_id, repo=None, policy=None, policy_sha256=None, reason='halt active'))
                            else:
                                rc, rep = mod.cmd_tick(SimpleNamespace(policy=str(pol_path), policy_sha256=None))
                        finally:
                            if missing_tracker and missing_bak.exists() and not beads_path.exists():
                                missing_bak.rename(beads_path)

                    self.assertEqual((rc, rep['outcome'], rep['reason']), (exp_rc, exp_out, exp_reason), msg=f'{name}: {rep}')
                    self.assertIs(rep['claim_retained'], exp_ret, msg=name) if isinstance(exp_ret, bool) else self.assertEqual(rep['claim_retained'], exp_ret, msg=name)
                    self.assertEqual(
                        (m_validate_tracker.call_count, m_presel.call_count, m_host_show.call_count, m_claim.call_count, m_ready.call_count, m_stage.call_count),
                        (0, 0, 0, 0, 0, 0),
                        msg=name,
                    )
                    if not incomplete_pin and not missing_tracker:
                        self.assertGreaterEqual(m_bshow.call_count, 1, msg=name)
                    elif missing_tracker:
                        self.assertEqual(m_bshow.call_count, 0, msg=name)
                    with closing(sqlite3.connect(f'{db_path.resolve().as_uri()}?mode=ro', uri=True)) as conn:
                        conn.row_factory = sqlite3.Row
                        drow = conn.execute('SELECT dispatch_state, outcome, reason, candidate_sha FROM dispatch_runs WHERE run_id = ?', (run_id,)).fetchone()
                        self.assertEqual((drow['dispatch_state'], drow['outcome'], drow['reason'], drow['candidate_sha']), (exp_dstate, exp_out, exp_reason, cand_sha), msg=name)
                        self.assertEqual(conn.execute('SELECT status FROM runs WHERE run_id = ?', (run_id,)).fetchone()[0], exp_rstat, msg=name)
                        self.assertEqual(conn.execute('SELECT count(*) FROM dispatch_stage_procs WHERE run_id = ?', (run_id,)).fetchone()[0], 0, msg=name)
                    bd_issue = self._show_issue(issue_id)
                    self.assertEqual((bd_issue['status'], bd_issue['assignee']), ('in_progress', actor), msg=name)
                    with patch.object(mod, '_validate_local_beads_tracker') as m_vt2, patch.object(mod, '_preselect_candidate') as m_p2, patch.object(mod, '_run_bound_bd_claim') as m_c2:
                        if exp_rstat == 'active':
                            self.assertNotEqual(self._run_ledger('start', str(self.repo)).returncode, 0, msg=name)
                            rc2, rep2 = mod.cmd_tick(SimpleNamespace(policy=str(pol_path), policy_sha256=None))
                            self.assertEqual((rc2, rep2['outcome'], m_vt2.call_count, m_p2.call_count, m_c2.call_count), (1, 'quarantined', 0, 0, 0), msg=name)
                        else:
                            rc2, rep2 = mod.cmd_tick(SimpleNamespace(policy=str(pol_path), policy_sha256=None))
                            self.assertEqual((rc2, rep2['outcome'], m_c2.call_count), (0, 'no_work', 0), msg=name)
                finally:
                    mod._run_stop_path(state_dir, run_id).unlink(missing_ok=True)
                    mod._repo_stop_path(state_dir, pol['repo_key']).unlink(missing_ok=True)

            for cname, st, op, bad_payload in (
                ('contra_reval_tick', 'reviewing', 'tick', lambda iid, act: {'id': iid, 'status': 'open', 'assignee': act}),
                ('malformed_reval_tick', 'reviewing', 'tick', lambda iid, act: {'id': iid, 'status': 'in_progress', 'assignee': 123}),
                ('ws_trail_reval_tick', 'reviewing', 'tick', lambda iid, act: {'id': iid, 'status': 'in_progress', 'assignee': f'{act} '}),
                ('ws_lead_reval_tick', 'reviewing', 'tick', lambda iid, act: {'id': iid, 'status': 'in_progress', 'assignee': f' {act}'}),
                ('ws_blank_reval_tick', 'reviewing', 'tick', lambda iid, act: {'id': iid, 'status': 'in_progress', 'assignee': '   '}),
                ('ws_other_reval_tick', 'reviewing', 'tick', lambda iid, act: {'id': iid, 'status': 'in_progress', 'assignee': ' alice '}),
                ('contra_obs_stop', 'checking', 'stop', lambda iid, act: {'id': iid, 'status': 'open', 'assignee': act}),
                ('malformed_obs_stop', 'checking', 'stop', lambda iid, act: {'id': iid, 'status': '', 'assignee': act}),
                ('ws_trail_obs_stop', 'checking', 'stop', lambda iid, act: {'id': iid, 'status': 'in_progress', 'assignee': f'{act} '}),
                ('ws_blank_obs_stop', 'checking', 'stop', lambda iid, act: {'id': iid, 'status': 'in_progress', 'assignee': '  '}),
            ):
                iid = self._create_issue(f'Unknown ownership {cname}')
                pp = self._write_policy(f'{cname}.json', issue_allowlist=[iid])
                rid = f'disp-{cname}'
                pol_c, act_c, _ = seed_active(rid, iid, pp, st, expired=False, incomplete_pin=False)
                with patch.object(mod, '_bound_bd_show', return_value=bad_payload(iid, act_c)):
                    if op == 'stop':
                        rc_c, rep_c = mod.cmd_stop(SimpleNamespace(run_id=rid, repo=None, policy=None, policy_sha256=None, reason='contra'))
                    else:
                        rc_c, rep_c = mod.cmd_tick(SimpleNamespace(policy=str(pp), policy_sha256=None))
                    if cname in ('contra_obs_stop', 'ws_trail_obs_stop'):
                        with mod.open_dispatch_tx(db_path) as conn:
                            drow_c = conn.execute('SELECT * FROM dispatch_runs WHERE run_id = ?', (rid,)).fetchone()
                        runner_c = mod.BwrapRunner()
                        runner_c.probe_capabilities()
                        rec_st, _ = mod._reconcile_claiming_read_only(
                            db_path, state_dir / 'locks', pol_c['repo_key'], self.repo, drow_c, runner=runner_c,
                        )
                        self.assertEqual(rec_st, 'unknown', msg=cname)
                mod._run_stop_path(state_dir, rid).unlink(missing_ok=True)
                mod._repo_stop_path(state_dir, pol_c['repo_key']).unlink(missing_ok=True)
                self.assertEqual((rc_c, rep_c['outcome'], rep_c['reason'], rep_c['claim_retained']), (1, 'quarantined', 'tracker_revalidation_failed', 'unknown'), msg=cname)
                self.assertNotEqual(self._run_ledger('start', str(self.repo)).returncode, 0, msg=cname)

            for hname, st, op, exp_rc, exp_out, exp_reason in (
                ('human_reval_tick', 'reviewing', 'tick', 1, 'blocked', 'ownership_revalidation_failed'),
                ('human_obs_stop', 'checking', 'stop', 0, 'cancelled', 'stopped:human'),
            ):
                iid_h = self._create_issue(f'Human owner preserved {hname}')
                pp_h = self._write_policy(f'{hname}.json', issue_allowlist=[iid_h])
                rid_h = f'disp-{hname}'
                pol_h, _, _ = seed_active(rid_h, iid_h, pp_h, st, expired=False, incomplete_pin=False)
                try:
                    with patch.object(mod, '_bound_bd_show', return_value={'id': iid_h, 'status': 'in_progress', 'assignee': 'Alice Smith'}):
                        if op == 'stop':
                            rc_h, rep_h = mod.cmd_stop(SimpleNamespace(run_id=rid_h, repo=None, policy=None, policy_sha256=None, reason='human'))
                        else:
                            rc_h, rep_h = mod.cmd_tick(SimpleNamespace(policy=str(pp_h), policy_sha256=None))
                    self.assertEqual((rc_h, rep_h['outcome'], rep_h['reason']), (exp_rc, exp_out, exp_reason), msg=f'{hname}: {rep_h}')
                    self.assertIs(rep_h['claim_retained'], False, msg=hname)
                finally:
                    mod._run_stop_path(state_dir, rid_h).unlink(missing_ok=True)
                    mod._repo_stop_path(state_dir, pol_h['repo_key']).unlink(missing_ok=True)

            iid_git = self._create_issue('Post-claim replaced dotgit')
            pp_git = self._write_policy('replaced_dotgit.json', issue_allowlist=[iid_git])
            rid_git = 'disp-post-replaced-dotgit'
            pol_git, _, _ = seed_active(rid_git, iid_git, pp_git, 'reviewing', expired=False, incomplete_pin=False)
            git_dir = self.repo / '.git'
            git_copy = self.base / 'replaced_dotgit_copy'
            git_bak = self.base / 'replaced_dotgit_bak'
            shutil.copytree(git_dir, git_copy)
            git_dir.rename(git_bak)
            git_copy.rename(git_dir)
            try:
                rc_g, rep_g = mod.cmd_stop(SimpleNamespace(run_id=rid_git, repo=None, policy=None, policy_sha256=None, reason='halt replaced git'))
                self.assertEqual((rc_g, rep_g['outcome'], rep_g['reason'], rep_g['claim_retained']), (1, 'quarantined', 'git_checkout_layout_mismatch', 'unknown'))
                with closing(sqlite3.connect(f'{db_path.resolve().as_uri()}?mode=ro', uri=True)) as conn:
                    conn.row_factory = sqlite3.Row
                    drow_g = conn.execute('SELECT dispatch_state, outcome, reason FROM dispatch_runs WHERE run_id = ?', (rid_git,)).fetchone()
                    self.assertEqual((drow_g['dispatch_state'], drow_g['outcome'], drow_g['reason']), ('quarantined', 'quarantined', 'git_checkout_layout_mismatch'))
                    self.assertEqual(conn.execute('SELECT status FROM runs WHERE run_id = ?', (rid_git,)).fetchone()[0], 'active')
                self.assertNotEqual(self._run_ledger('start', str(self.repo)).returncode, 0)
            finally:
                if git_bak.exists():
                    shutil.rmtree(git_dir, ignore_errors=True)
                    git_bak.rename(git_dir)
                mod._run_stop_path(state_dir, rid_git).unlink(missing_ok=True)
                mod._repo_stop_path(state_dir, pol_git['repo_key']).unlink(missing_ok=True)

    def test_base_ref_advance_recovers_active_run_and_blocks_fresh_admission(self) -> None:
        mod = _load_dispatch_module()
        db_path = self.xdg_state / 'pi-team-run' / 'state.db'
        state_dir = self.xdg_state / 'pi-team-dispatch'
        orig_reconcile = mod._reconcile_stage_procs
        dead_proc = subprocess.Popen(
            ['/usr/bin/python3', '-I', '-c', 'pass'],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        dead_proc.wait(timeout=5)

        def seed_post_claim(run_id: str, issue_id: str, pol_path: Path, *, expired: bool) -> tuple[dict, str, str]:
            pol, pol_digest, pol_real = mod.load_and_validate_policy(
                str(pol_path), db_path=db_path, dispatch_state_dir=state_dir,
            )
            tracker = mod._validate_local_beads_tracker(self.repo)
            actor = f'disp-test:{run_id}'
            claim = self._bd(self.repo, '--sandbox', '--actor', actor, 'update', issue_id, '--claim', '--json')
            self.assertEqual(claim.returncode, 0, msg=claim.stderr + claim.stdout)
            spec_fp = mod._issue_spec_fingerprint(self._show_issue(issue_id), pol_digest, self.base_sha)
            store_dir = mod._sync_base_to_store(state_dir, pol['repo_key'], Path(pol['repo_root']), self.base_sha)
            with tempfile.TemporaryDirectory(dir=state_dir / 'scratch', prefix=f'{run_id}-seed-') as seed_tmp:
                mat_ws = Path(seed_tmp) / 'ws'
                mod._materialize_commit(store_dir, self.base_sha, mat_ws)
                (mat_ws / 'allowed.txt').write_text('updated\n', encoding='utf-8')
                cand_sha, _ = mod._validate_and_commit_candidate(
                    store_dir=store_dir, scratch_dir=Path(seed_tmp), run_id=run_id, attempt=1,
                    base_sha=self.base_sha, worker_dir=mat_ws,
                    allowed_paths=pol['allowed_paths'], allowed_ops=pol['allowed_ops'],
                )
            now_dt = mod.utc_now()
            now_iso = mod.format_utc(now_dt)
            deadline_iso = mod.format_utc(now_dt + timedelta(seconds=-15 if expired else 60))
            with mod.open_dispatch_tx(db_path) as conn:
                for tbl in ('dispatch_stage_procs', 'dispatch_runs', 'runs'):
                    conn.execute(f'DELETE FROM {tbl}')
                conn.execute(
                    "INSERT INTO runs (run_id, repo_key, status, current_stage, wait_generation, commit_only, no_ci, with_deploy, with_honcho, with_wiki, created_at, updated_at) VALUES (?, ?, 'active', 'admit', 0, 1, 0, 0, 0, 0, ?, ?)",
                    (run_id, pol['repo_key'], now_iso, now_iso),
                )
                conn.execute(
                    "INSERT INTO dispatch_runs (run_id, repo_key, repo_root, beads_dir, beads_db_path, beads_dir_dev, beads_dir_ino, beads_db_dev, beads_db_ino, git_common_dir_dev, git_common_dir_ino, issue_id, actor, policy_path, policy_digest, base_sha, candidate_sha, fingerprint, dispatch_state, attempt, max_attempts, spend_usd, max_spend_usd, deadline_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'reviewing', 1, 2, 0.0, 0.0, ?, ?, ?)",
                    (run_id, pol['repo_key'], pol['repo_root'], tracker['beads_dir'], tracker['beads_db_path'], tracker['beads_dir_dev'], tracker['beads_dir_ino'], tracker['beads_db_dev'], tracker['beads_db_ino'], *self._seed_git_pin(pol['repo_key']), issue_id, actor, str(pol_real), pol_digest, self.base_sha, cand_sha, spec_fp, deadline_iso, now_iso, now_iso),
                )
                conn.execute(
                    "INSERT INTO dispatch_stage_procs (run_id, attempt, stage, launch_token, status, pid1, boot_id, starttime, ns_pid, created_at, updated_at) VALUES (?, 1, 'worker', 'tok-r5', 'running', ?, ?, '0', 'pid:[0]', ?, ?)",
                    (run_id, dead_proc.pid, mod._read_boot_id(), now_iso, now_iso),
                )
            return pol, actor, cand_sha

        with patch.dict(os.environ, self.env, clear=True):
            mod.ensure_dispatch_dirs(state_dir)

            i_exp = self._create_issue('R5 active expired across base_ref advance')
            pol_exp = self._write_policy('r5_exp.json', issue_allowlist=[i_exp])
            run_exp = 'disp-r5-exp-01'
            _, actor_exp, cand_exp = seed_post_claim(run_exp, i_exp, pol_exp, expired=True)

            i_live = self._create_issue('R5 active non-expired base_ref drift')
            pol_live = self._write_policy('r5_live.json', issue_allowlist=[i_live])

            (self.repo / 'other.txt').write_text('advanced tip\n', encoding='utf-8')
            self._git(self.repo, 'add', 'other.txt')
            self._git(self.repo, 'commit', '-m', 'advance main past pinned base_sha')
            advanced_sha = self._git(self.repo, 'rev-parse', 'refs/heads/main').stdout.strip()
            self.assertNotEqual(advanced_sha, self.base_sha)

            with (
                patch.object(mod, '_validate_local_beads_tracker') as m_vt,
                patch.object(mod, '_preselect_candidate') as m_presel,
            ):
                dry_rc, dry_rep = mod.cmd_dry_run(SimpleNamespace(policy=str(pol_exp), policy_sha256=None))
            self.assertEqual((dry_rc, dry_rep['outcome'], dry_rep['run_id']), (0, 'recover_pending', run_exp))
            self.assertEqual((m_vt.call_count, m_presel.call_count), (0, 0))

            with (
                patch.object(mod, '_reconcile_stage_procs', wraps=orig_reconcile) as m_rec,
                patch.object(mod, '_validate_local_beads_tracker') as m_vt,
                patch.object(mod, '_preselect_candidate') as m_presel,
                patch.object(mod, '_run_bound_bd_claim') as m_claim,
                patch.object(mod.BwrapRunner, 'run_stage') as m_stage,
            ):
                rc, rep = mod.cmd_tick(SimpleNamespace(policy=str(pol_exp), policy_sha256=None))

            self.assertEqual(m_rec.call_count, 1)
            self.assertEqual(m_rec.call_args.args, (db_path, run_exp))
            self.assertEqual((rc, rep['outcome'], rep['reason'], rep['candidate_sha']), (1, 'blocked', 'run_timeout_exceeded', cand_exp))
            self.assertIs(rep['claim_retained'], True)
            self.assertEqual((m_vt.call_count, m_presel.call_count, m_claim.call_count, m_stage.call_count), (0, 0, 0, 0))
            with closing(sqlite3.connect(f'{db_path.resolve().as_uri()}?mode=ro', uri=True)) as conn:
                conn.row_factory = sqlite3.Row
                drow = conn.execute('SELECT dispatch_state, outcome, reason FROM dispatch_runs WHERE run_id = ?', (run_exp,)).fetchone()
                self.assertEqual((drow['dispatch_state'], drow['outcome'], drow['reason']), ('blocked', 'blocked', 'run_timeout_exceeded'))
                self.assertEqual(conn.execute('SELECT status FROM runs WHERE run_id = ?', (run_exp,)).fetchone()[0], 'cancelled')
                self.assertEqual(conn.execute('SELECT status FROM dispatch_stage_procs WHERE run_id = ?', (run_exp,)).fetchone()[0], 'exited')
            bd_exp = self._show_issue(i_exp)
            self.assertEqual((bd_exp['status'], bd_exp['assignee']), ('in_progress', actor_exp))

            run_live = 'disp-r5-live-01'
            actor_live = f'disp-test:{run_live}'
            claim_live = self._bd(self.repo, '--sandbox', '--actor', actor_live, 'update', i_live, '--claim', '--json')
            self.assertEqual(claim_live.returncode, 0, msg=claim_live.stderr + claim_live.stdout)
            pol_live_cfg, pol_live_digest, pol_live_real = mod.load_and_validate_policy(
                str(pol_live), db_path=db_path, dispatch_state_dir=state_dir, check_base_ref=False,
            )
            tracker_live = mod._validate_local_beads_tracker(self.repo)
            fp_live = mod._issue_spec_fingerprint(self._show_issue(i_live), pol_live_digest, self.base_sha)
            now_dt2 = mod.utc_now()
            now_iso2 = mod.format_utc(now_dt2)
            future_iso2 = mod.format_utc(now_dt2 + timedelta(seconds=60))
            with mod.open_dispatch_tx(db_path) as conn:
                conn.execute(
                    "INSERT INTO runs (run_id, repo_key, status, current_stage, wait_generation, commit_only, no_ci, with_deploy, with_honcho, with_wiki, created_at, updated_at) VALUES (?, ?, 'active', 'admit', 0, 1, 0, 0, 0, 0, ?, ?)",
                    (run_live, pol_live_cfg['repo_key'], now_iso2, now_iso2),
                )
                conn.execute(
                    "INSERT INTO dispatch_runs (run_id, repo_key, repo_root, beads_dir, beads_db_path, beads_dir_dev, beads_dir_ino, beads_db_dev, beads_db_ino, git_common_dir_dev, git_common_dir_ino, issue_id, actor, policy_path, policy_digest, base_sha, candidate_sha, fingerprint, dispatch_state, attempt, max_attempts, spend_usd, max_spend_usd, deadline_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'reviewing', 1, 2, 0.0, 0.0, ?, ?, ?)",
                    (run_live, pol_live_cfg['repo_key'], pol_live_cfg['repo_root'], tracker_live['beads_dir'], tracker_live['beads_db_path'], tracker_live['beads_dir_dev'], tracker_live['beads_dir_ino'], tracker_live['beads_db_dev'], tracker_live['beads_db_ino'], *self._seed_git_pin(pol_live_cfg['repo_key']), i_live, actor_live, str(pol_live_real), pol_live_digest, self.base_sha, cand_exp, fp_live, future_iso2, now_iso2, now_iso2),
                )
                conn.execute(
                    "INSERT INTO dispatch_stage_procs (run_id, attempt, stage, launch_token, status, pid1, boot_id, starttime, ns_pid, created_at, updated_at) VALUES (?, 1, 'review', 'tok-r5-live', 'running', ?, ?, '0', 'pid:[0]', ?, ?)",
                    (run_live, dead_proc.pid, mod._read_boot_id(), now_iso2, now_iso2),
                )

            with (
                patch.object(mod, '_reconcile_stage_procs', wraps=orig_reconcile) as m_rec2,
                patch.object(mod, '_run_bound_bd_claim') as m_claim2,
                patch.object(mod.BwrapRunner, 'run_stage') as m_stage2,
            ):
                rc2, rep2 = mod.cmd_tick(SimpleNamespace(policy=str(pol_live), policy_sha256=None))
            self.assertEqual(m_rec2.call_count, 1)
            self.assertEqual(m_rec2.call_args.args, (db_path, run_live))
            self.assertEqual((rc2, rep2['outcome'], rep2['reason']), (1, 'blocked', 'base_ref_drifted'))
            self.assertIs(rep2['claim_retained'], True)
            self.assertEqual((m_claim2.call_count, m_stage2.call_count), (0, 0))
            with closing(sqlite3.connect(f'{db_path.resolve().as_uri()}?mode=ro', uri=True)) as conn:
                self.assertEqual(conn.execute('SELECT status FROM dispatch_stage_procs WHERE run_id = ?', (run_live,)).fetchone()[0], 'exited')

            i_fresh = self._create_issue('R5 fresh admission must reject drifted base_ref')
            pol_fresh = self._write_policy('r5_fresh.json', issue_allowlist=[i_fresh])
            with (
                patch.object(mod, '_validate_local_beads_tracker') as m_vt3,
                patch.object(mod, '_preselect_candidate') as m_presel3,
                patch.object(mod, '_run_bound_bd_claim') as m_claim3,
                patch.object(mod.BwrapRunner, 'run_stage') as m_stage3,
            ):
                with self.assertRaisesRegex(mod.DispatchError, 'base_ref.*does not match pinned base_sha'):
                    mod.cmd_tick(SimpleNamespace(policy=str(pol_fresh), policy_sha256=None))
                with self.assertRaisesRegex(mod.DispatchError, 'base_ref.*does not match pinned base_sha'):
                    mod.cmd_dry_run(SimpleNamespace(policy=str(pol_fresh), policy_sha256=None))
            self.assertEqual((m_vt3.call_count, m_presel3.call_count, m_claim3.call_count, m_stage3.call_count), (0, 0, 0, 0))
            bd_fresh = self._show_issue(i_fresh)
            self.assertEqual((bd_fresh['status'], (bd_fresh.get('assignee') or '').strip()), ('open', ''))
            with closing(sqlite3.connect(f'{db_path.resolve().as_uri()}?mode=ro', uri=True)) as conn:
                self.assertEqual(conn.execute("SELECT count(*) FROM runs WHERE status IN ('active', 'waiting')").fetchone()[0], 0)

    def test_ownership_loss_checks_review_and_fd_bound_read(self) -> None:
        mod = _load_dispatch_module()
        db_path = self.xdg_state / 'pi-team-run' / 'state.db'
        state_dir = self.xdg_state / 'pi-team-dispatch'
        checks = [
            {'name': 'chk1', 'argv': ['/usr/bin/python3', '-I', '-c', 'from pathlib import Path; assert Path("/workspace/allowed.txt").read_text() == "updated\\n"'], 'timeout_sec': 10},
            {'name': 'chk2', 'argv': ['/usr/bin/python3', '-I', '-c', 'import sys; sys.exit(0)'], 'timeout_sec': 10},
        ]
        orig_run_stage, orig_bd_show, orig_bound_claim = mod.BwrapRunner.run_stage, mod._bd_show, mod._run_bound_bd_claim
        orig_bound_show, orig_verify = mod._bound_bd_show, mod._verify_handles_match_host

        for trigger_stage, pol_name, exp_checks in (('check:chk1', 'own_loss_chk.json', ['chk1']), ('review', 'own_loss_rev.json', ['chk1', 'chk2'])):
            issue_id = self._create_issue(f'Ownership loss after {trigger_stage}')
            pol = self._write_policy(pol_name, issue_allowlist=[issue_id], checks=checks)
            stages_seen: list[str] = []

            def wrapped_stage(runner_self, **kwargs):
                st = kwargs['stage']
                stages_seen.append(st)
                out = orig_run_stage(runner_self, **kwargs)
                if st == trigger_stage:
                    cur_issue = self._show_issue(issue_id)
                    cur_assignee = (cur_issue.get('assignee') or '').strip()
                    self.assertEqual(cur_issue['status'], 'in_progress')
                    self.assertEqual(cur_assignee, f'disp-test:{kwargs["run_id"]}')
                    unauth = self._bd(self.repo, '--sandbox', 'update', issue_id, '--assignee', 'other-owner', '--json')
                    self.assertNotEqual(unauth.returncode, 0, msg='unauthenticated actor must not mutate live lease')
                    self.assertEqual((self._show_issue(issue_id).get('assignee') or '').strip(), cur_assignee)
                    upd = self._bd(
                        self.repo, '--sandbox', '--actor', cur_assignee,
                        'update', issue_id, '--if-assignee', cur_assignee, '--assignee', 'other-owner', '--json',
                    )
                    if upd.returncode != 0:
                        rel = self._bd(
                            self.repo, '--sandbox', '--actor', cur_assignee,
                            'update', issue_id, '--if-assignee', cur_assignee, '--assignee', '', '--status', 'open', '--json',
                        )
                        self.assertEqual(rel.returncode, 0, msg=rel.stderr + rel.stdout)
                        clm = self._bd(
                            self.repo, '--sandbox', '--actor', 'other-owner',
                            'update', issue_id, '--claim', '--json',
                        )
                        self.assertEqual(clm.returncode, 0, msg=clm.stderr + clm.stdout)
                    handed = self._show_issue(issue_id)
                    self.assertEqual(handed['assignee'], 'other-owner')
                    self.assertEqual(handed['status'], 'in_progress')
                return out

            with (
                patch.dict(os.environ, self.env, clear=True),
                patch.object(mod, '_bd_show', wraps=orig_bd_show) as m_host_show,
                patch.object(mod, '_run_bound_bd_claim', side_effect=lambda **kw: (m_host_show.reset_mock(), orig_bound_claim(**kw))[1]) as m_claim,
                patch.object(mod, '_bound_bd_show', wraps=orig_bound_show) as m_bshow,
                patch.object(mod, '_verify_handles_match_host', wraps=orig_verify) as m_verify,
                patch.object(mod.BwrapRunner, 'run_stage', new=wrapped_stage),
            ):
                rc, rep = mod.cmd_tick(SimpleNamespace(policy=str(pol), policy_sha256=None))

            self.assertEqual((rc, rep['outcome'], rep['reason']), (1, 'blocked', 'ownership_revalidation_failed'), msg=rep)
            self.assertIs(rep['claim_retained'], False, msg=rep)
            self.assertEqual([c['name'] for c in rep['checks']], exp_checks, msg=rep)
            self.assertTrue(all(c['passed'] for c in rep['checks']), msg=rep)
            self.assertEqual((m_claim.call_count, m_host_show.call_count), (1, 0), msg=rep)
            self.assertTrue(m_bshow.call_count >= 2 and m_verify.call_count >= 2)
            exp_post = ['check:chk1'] if trigger_stage == 'check:chk1' else ['check:chk1', 'check:chk2', 'review']
            self.assertEqual([s for s in stages_seen if s.startswith(('check:', 'review'))], exp_post)
            self.assertIsNone(rep.get('review')) if trigger_stage == 'check:chk1' else self.assertEqual(rep['review']['verdict'], 'pass')
            self.assertEqual(self._show_issue(issue_id)['assignee'], 'other-owner')
            with closing(sqlite3.connect(f'{db_path.resolve().as_uri()}?mode=ro', uri=True)) as conn:
                conn.row_factory = sqlite3.Row
                drow = conn.execute('SELECT outcome, dispatch_state, checks_json, review_json FROM dispatch_runs WHERE run_id = ?', (rep['run_id'],)).fetchone()
                self.assertEqual((drow['outcome'], drow['dispatch_state']), ('blocked', 'blocked'))
                self.assertEqual([c['name'] for c in json.loads(drow['checks_json'])], exp_checks)
                self.assertIsNone(drow['review_json']) if trigger_stage == 'check:chk1' else self.assertEqual(json.loads(drow['review_json'])['verdict'], 'pass')
                st_rows = [r[0] for r in conn.execute('SELECT stage FROM dispatch_stage_procs WHERE run_id = ? ORDER BY id ASC', (rep['run_id'],)).fetchall()]
                self.assertEqual([s for s in st_rows if s.startswith(('check:', 'review'))], exp_post)
                self.assertEqual(conn.execute('SELECT status FROM runs WHERE run_id = ?', (rep['run_id'],)).fetchone()[0], 'cancelled')

        with patch.dict(os.environ, self.env, clear=True):
            mod.ensure_dispatch_dirs(state_dir)
            runner = mod.BwrapRunner()
            runner.probe_capabilities()
            beads_path, beads_bak = self.repo / '.beads', self.base / 'beads_unavail_bak'
            with mod._open_pinned_beads_handles(self.repo) as handles, mod._acquire_bd_lock(state_dir / 'locks', str((self.repo / '.git').resolve())) as lock_fd:
                beads_path.rename(beads_bak)
                try:
                    shown = mod._bound_bd_show(handles=handles, bd_lock_fd=lock_fd, issue_id=issue_id, seccomp_bpf=runner.seccomp_bpf, bwrap_bin=runner.bwrap_bin)
                    self.assertEqual((shown['id'], shown['assignee']), (issue_id, 'other-owner'))
                    with self.assertRaises(mod.DispatchError):
                        mod._verify_handles_match_host(self.repo, handles, handles['identity'])
                finally:
                    beads_bak.rename(beads_path)
                mod._verify_handles_match_host(self.repo, handles, handles['identity'])

    def test_malformed_claim_response_reads_back_or_quarantines(self) -> None:
        mod = _load_dispatch_module()
        db_path = self.xdg_state / 'pi-team-run' / 'state.db'
        state_dir = self.xdg_state / 'pi-team-dispatch'
        orig_bound_claim = mod._run_bound_bd_claim
        orig_bound_show = mod._bound_bd_show

        with patch.dict(os.environ, self.env, clear=True):
            mod.ensure_dispatch_dirs(state_dir)

            for label, mutate_claim_out in (
                ('empty_out', lambda issue_id, actor: ''),
                ('non_str_owner', lambda issue_id, actor: json.dumps([{'id': issue_id, 'status': 'in_progress', 'assignee': {'bad': 1}}])),
                ('ws_actor', lambda issue_id, actor: json.dumps([{'id': issue_id, 'status': 'in_progress', 'assignee': f'{actor} '}])),
                ('wrong_id', lambda issue_id, actor: json.dumps([{'id': 'wrong-id', 'status': 'in_progress', 'assignee': actor}])),
                ('bad_status', lambda issue_id, actor: json.dumps([{'id': issue_id, 'status': 123, 'assignee': actor}])),
            ):
                iid = self._create_issue(f'Malformed claim readback {label}')
                pol = self._write_policy(f'mal_ok_{label}.json', issue_allowlist=[iid])
                with (
                    patch.object(mod, '_run_bound_bd_claim', side_effect=lambda **kw: (orig_bound_claim(**kw), mutate_claim_out(kw['issue_id'], kw['actor']))[1]),
                    patch.object(mod, '_bound_bd_show', wraps=orig_bound_show) as m_bshow,
                ):
                    rc, rep = mod.cmd_tick(SimpleNamespace(policy=str(pol), policy_sha256=None))
                self.assertEqual((rc, rep['outcome']), (0, 'candidate_ready'), msg=f'{label}: {rep}')
                self.assertGreaterEqual(m_bshow.call_count, 2, msg=label)
                with mod.open_dispatch_tx(db_path) as conn:
                    for tbl in ('dispatch_stage_procs', 'dispatch_runs', 'runs'):
                        conn.execute(f'DELETE FROM {tbl}')

            bad_readbacks = (
                ('mal_owner_readback', lambda issue_id, actor: {'id': issue_id, 'status': 'in_progress', 'assignee': 123}),
                ('ws_actor_readback', lambda issue_id, actor: {'id': issue_id, 'status': 'in_progress', 'assignee': f'{actor} '}),
                ('ws_blank_readback', lambda issue_id, actor: {'id': issue_id, 'status': 'in_progress', 'assignee': '   '}),
                ('empty_status_readback', lambda issue_id, actor: {'id': issue_id, 'status': '', 'assignee': actor}),
                ('wrong_id_readback', lambda issue_id, actor: {'id': 'wrong-id', 'status': 'in_progress', 'assignee': actor}),
                ('contradictory_open_owner', lambda issue_id, actor: {'id': issue_id, 'status': 'open', 'assignee': actor}),
            )
            for label, make_bad_show in bad_readbacks:
                iid = self._create_issue(f'Malformed readback quarantines {label}')
                pol = self._write_policy(f'mal_q_{label}.json', issue_allowlist=[iid])
                claimed_seen = {'hit': False, 'actor': ''}

                def fake_claim(**kw):
                    claimed_seen['hit'] = True
                    claimed_seen['actor'] = kw['actor']
                    return json.dumps([{'id': kw['issue_id'], 'status': 'in_progress', 'assignee': {'bad': 1}}])

                def fake_show(**kw):
                    if claimed_seen['hit']:
                        return make_bad_show(kw['issue_id'], claimed_seen['actor'])
                    return orig_bound_show(**kw)

                with (
                    patch.object(mod, '_run_bound_bd_claim', side_effect=fake_claim),
                    patch.object(mod, '_bound_bd_show', side_effect=fake_show),
                ):
                    rc, rep = mod.cmd_tick(SimpleNamespace(policy=str(pol), policy_sha256=None))
                self.assertEqual((rc, rep['outcome'], rep['reason']), (1, 'quarantined', 'claim_ambiguous_tracker_error'), msg=f'{label}: {rep}')
                self.assertEqual(rep['claim_retained'], 'unknown', msg=label)
                self.assertNotEqual(self._run_ledger('start', str(self.repo)).returncode, 0, msg=label)
                with mod.open_dispatch_tx(db_path) as conn:
                    for tbl in ('dispatch_stage_procs', 'dispatch_runs', 'runs'):
                        conn.execute(f'DELETE FROM {tbl}')

    def test_post_read_git_pin_loss_during_bound_read_quarantines(self) -> None:
        mod = _load_dispatch_module()
        db_path = self.xdg_state / 'pi-team-run' / 'state.db'
        state_dir = self.xdg_state / 'pi-team-dispatch'
        git_dir = self.repo / '.git'
        git_bak = self.base / 'bound_read_git_bak'
        orig_verify = mod._verify_bwrap_pid1_identity

        def seed_case(run_id: str, issue_id: str, pol_path: Path, state: str, *, handoff: bool, expired: bool) -> dict:
            pol, pol_digest, pol_real = mod.load_and_validate_policy(str(pol_path), db_path=db_path, dispatch_state_dir=state_dir)
            tracker = mod._validate_local_beads_tracker(self.repo)
            actor = f'disp-test:{run_id}'
            if handoff:
                claim = self._bd(self.repo, '--sandbox', '--actor', actor, 'update', issue_id, '--claim', '--json')
                self.assertEqual(claim.returncode, 0, msg=claim.stderr + claim.stdout)
                spec_fp = mod._issue_spec_fingerprint(self._show_issue(issue_id), pol_digest, self.base_sha)
                upd = self._bd(self.repo, '--sandbox', '--actor', actor, 'update', issue_id, '--if-assignee', actor, '--assignee', 'other-owner', '--json')
                if upd.returncode != 0:
                    rel = self._bd(self.repo, '--sandbox', '--actor', actor, 'update', issue_id, '--if-assignee', actor, '--assignee', '', '--status', 'open', '--json')
                    self.assertEqual(rel.returncode, 0, msg=rel.stderr + rel.stdout)
                    clm = self._bd(self.repo, '--sandbox', '--actor', 'other-owner', 'update', issue_id, '--claim', '--json')
                    self.assertEqual(clm.returncode, 0, msg=clm.stderr + clm.stdout)
            else:
                spec_fp = mod._issue_spec_fingerprint(self._show_issue(issue_id), pol_digest, self.base_sha)
            now_dt = mod.utc_now()
            now_iso = mod.format_utc(now_dt)
            deadline_iso = mod.format_utc(now_dt + timedelta(seconds=-10 if expired else 60))
            with mod.open_dispatch_tx(db_path) as conn:
                for tbl in ('dispatch_stage_procs', 'dispatch_runs', 'runs'):
                    conn.execute(f'DELETE FROM {tbl}')
                conn.execute(
                    "INSERT INTO runs (run_id, repo_key, status, current_stage, wait_generation, commit_only, no_ci, with_deploy, with_honcho, with_wiki, created_at, updated_at) VALUES (?, ?, 'active', 'admit', 0, 1, 0, 0, 0, 0, ?, ?)",
                    (run_id, pol['repo_key'], now_iso, now_iso),
                )
                conn.execute(
                    "INSERT INTO dispatch_runs (run_id, repo_key, repo_root, beads_dir, beads_db_path, beads_dir_dev, beads_dir_ino, beads_db_dev, beads_db_ino, git_common_dir_dev, git_common_dir_ino, issue_id, actor, policy_path, policy_digest, base_sha, fingerprint, dispatch_state, attempt, max_attempts, spend_usd, max_spend_usd, deadline_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 2, 0.0, 0.0, ?, ?, ?)",
                    (run_id, pol['repo_key'], pol['repo_root'], tracker['beads_dir'], tracker['beads_db_path'], tracker['beads_dir_dev'], tracker['beads_dir_ino'], tracker['beads_db_dev'], tracker['beads_db_ino'], *self._seed_git_pin(pol['repo_key']), issue_id, actor, str(pol_real), pol_digest, self.base_sha, spec_fp, state, deadline_iso, now_iso, now_iso),
                )
            return pol

        with patch.dict(os.environ, self.env, clear=True):
            mod.ensure_dispatch_dirs(state_dir)
            for cname, state, op, handoff, expired in (
                ('obs_stop', 'reviewing', 'stop', True, False),
                ('reval_tick', 'reviewing', 'tick', True, False),
                ('claiming_tick', 'claiming', 'tick', False, True),
            ):
                iid = self._create_issue(f'Bound read git pin loss {cname}')
                pol_path = self._write_policy(f'r4_{cname}.json', issue_allowlist=[iid])
                rid = f'disp-r4-{cname}'
                pol = seed_case(rid, iid, pol_path, state, handoff=handoff, expired=expired)
                armed = {'done': False}

                def verify_and_drop_git(proc, info_obj, *, label, **kwargs):
                    verified = orig_verify(proc, info_obj, label=label, **kwargs)
                    if label == 'bound bd show' and not armed['done']:
                        armed['done'] = True
                        git_dir.rename(git_bak)
                    return verified

                try:
                    with patch.object(mod, '_verify_bwrap_pid1_identity', side_effect=verify_and_drop_git):
                        if op == 'stop':
                            rc, rep = mod.cmd_stop(SimpleNamespace(run_id=rid, repo=None, policy=None, policy_sha256=None, reason='r4'))
                        else:
                            rc, rep = mod.cmd_tick(SimpleNamespace(policy=str(pol_path), policy_sha256=None))
                finally:
                    if git_bak.exists() and not git_dir.exists():
                        git_bak.rename(git_dir)
                    mod._run_stop_path(state_dir, rid).unlink(missing_ok=True)
                    mod._repo_stop_path(state_dir, pol['repo_key']).unlink(missing_ok=True)

                self.assertTrue(armed['done'], msg=cname)
                self.assertEqual((rc, rep['outcome'], rep['reason'], rep['claim_retained']), (1, 'quarantined', 'git_checkout_layout_mismatch', 'unknown'), msg=f'{cname}: {rep}')
                with closing(sqlite3.connect(f'{db_path.resolve().as_uri()}?mode=ro', uri=True)) as conn:
                    self.assertEqual(conn.execute('SELECT status FROM runs WHERE run_id = ?', (rid,)).fetchone()[0], 'active', msg=cname)
                self.assertNotEqual(self._run_ledger('start', str(self.repo)).returncode, 0, msg=cname)

    def test_stored_path_recovery_and_policy_revoke_regressions(self) -> None:
        mod = _load_dispatch_module()
        db_path = self.xdg_state / 'pi-team-run' / 'state.db'
        state_dir = self.xdg_state / 'pi-team-dispatch'
        orig_reconcile = mod._reconcile_stage_procs
        dead_proc = subprocess.Popen(
            ['/usr/bin/python3', '-I', '-c', 'pass'],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        dead_proc.wait(timeout=5)

        def seed_post_claim(run_id: str, issue_id: str, pol_path: Path, stage: str = 'worker') -> tuple[dict, str, str]:
            pol, pol_digest, pol_real = mod.load_and_validate_policy(
                str(pol_path), db_path=db_path, dispatch_state_dir=state_dir,
            )
            tracker = mod._validate_local_beads_tracker(self.repo)
            actor = f'disp-test:{run_id}'
            claim = self._bd(self.repo, '--sandbox', '--actor', actor, 'update', issue_id, '--claim', '--json')
            self.assertEqual(claim.returncode, 0, msg=claim.stderr + claim.stdout)
            spec_fp = mod._issue_spec_fingerprint(self._show_issue(issue_id), pol_digest, self.base_sha)
            store_dir = mod._sync_base_to_store(state_dir, pol['repo_key'], Path(pol['repo_root']), self.base_sha)
            with tempfile.TemporaryDirectory(dir=state_dir / 'scratch', prefix=f'{run_id}-seed-') as seed_tmp:
                mat_ws = Path(seed_tmp) / 'ws'
                mod._materialize_commit(store_dir, self.base_sha, mat_ws)
                (mat_ws / 'allowed.txt').write_text('updated\n', encoding='utf-8')
                cand_sha, _ = mod._validate_and_commit_candidate(
                    store_dir=store_dir, scratch_dir=Path(seed_tmp), run_id=run_id, attempt=1,
                    base_sha=self.base_sha, worker_dir=mat_ws,
                    allowed_paths=pol['allowed_paths'], allowed_ops=pol['allowed_ops'],
                )
            now_dt = mod.utc_now()
            now_iso = mod.format_utc(now_dt)
            deadline_iso = mod.format_utc(now_dt + timedelta(seconds=60))
            with mod.open_dispatch_tx(db_path) as conn:
                for tbl in ('dispatch_stage_procs', 'dispatch_runs', 'runs'):
                    conn.execute(f'DELETE FROM {tbl}')
                conn.execute(
                    "INSERT INTO runs (run_id, repo_key, status, current_stage, wait_generation, commit_only, no_ci, with_deploy, with_honcho, with_wiki, created_at, updated_at) VALUES (?, ?, 'active', 'admit', 0, 1, 0, 0, 0, 0, ?, ?)",
                    (run_id, pol['repo_key'], now_iso, now_iso),
                )
                conn.execute(
                    "INSERT INTO dispatch_runs (run_id, repo_key, repo_root, beads_dir, beads_db_path, beads_dir_dev, beads_dir_ino, beads_db_dev, beads_db_ino, git_common_dir_dev, git_common_dir_ino, issue_id, actor, policy_path, policy_digest, base_sha, candidate_sha, fingerprint, dispatch_state, attempt, max_attempts, spend_usd, max_spend_usd, deadline_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'reviewing', 1, 2, 0.0, 0.0, ?, ?, ?)",
                    (run_id, pol['repo_key'], pol['repo_root'], tracker['beads_dir'], tracker['beads_db_path'], tracker['beads_dir_dev'], tracker['beads_dir_ino'], tracker['beads_db_dev'], tracker['beads_db_ino'], *self._seed_git_pin(pol['repo_key']), issue_id, actor, str(pol_real), pol_digest, self.base_sha, cand_sha, spec_fp, deadline_iso, now_iso, now_iso),
                )
                conn.execute(
                    "INSERT INTO dispatch_stage_procs (run_id, attempt, stage, launch_token, status, pid1, boot_id, starttime, ns_pid, created_at, updated_at) VALUES (?, 1, ?, 'tok-r8', 'running', ?, ?, '0', 'pid:[0]', ?, ?)",
                    (run_id, stage, dead_proc.pid, mod._read_boot_id(), now_iso, now_iso),
                )
            return pol, pol_digest, cand_sha

        with patch.dict(os.environ, self.env, clear=True):
            mod.ensure_dispatch_dirs(state_dir)

            i_edit = self._create_issue('R8 policy edit with requested digest')
            pol_edit = self._write_policy('r8_edit.json', issue_allowlist=[i_edit])
            run_edit = 'disp-r8-edit-01'
            _, orig_digest_edit, cand_edit = seed_post_claim(run_edit, i_edit, pol_edit)
            self._write_policy('r8_edit.json', issue_allowlist=[i_edit], run_sec=120)

            with (
                patch.object(mod, '_validate_local_beads_tracker') as m_vt,
                patch.object(mod, '_preselect_candidate') as m_presel,
            ):
                dry_rc, dry_rep = mod.cmd_dry_run(SimpleNamespace(policy=str(pol_edit), policy_sha256=orig_digest_edit))
            self.assertEqual((dry_rc, dry_rep['outcome'], dry_rep['run_id'], dry_rep['policy_digest']), (0, 'recover_pending', run_edit, orig_digest_edit))
            self.assertEqual((m_vt.call_count, m_presel.call_count), (0, 0))

            with (
                patch.object(mod, '_reconcile_stage_procs', wraps=orig_reconcile) as m_rec,
                patch.object(mod, '_validate_local_beads_tracker') as m_vt,
                patch.object(mod, '_preselect_candidate') as m_presel,
                patch.object(mod, '_run_bound_bd_claim') as m_claim,
                patch.object(mod.BwrapRunner, 'run_stage') as m_stage,
            ):
                rc, rep = mod.cmd_tick(SimpleNamespace(policy=str(pol_edit), policy_sha256=orig_digest_edit))
            self.assertEqual(m_rec.call_count, 1)
            self.assertEqual((rc, rep['outcome'], rep['reason'], rep['candidate_sha']), (1, 'quarantined', 'policy_digest_changed_on_recovery', cand_edit))
            self.assertIs(rep['claim_retained'], True)
            self.assertEqual((m_vt.call_count, m_presel.call_count, m_claim.call_count, m_stage.call_count), (0, 0, 0, 0))
            with closing(sqlite3.connect(f'{db_path.resolve().as_uri()}?mode=ro', uri=True)) as conn:
                self.assertEqual(conn.execute('SELECT status FROM dispatch_stage_procs WHERE run_id = ?', (run_edit,)).fetchone()[0], 'exited')
                self.assertEqual(conn.execute('SELECT status FROM runs WHERE run_id = ?', (run_edit,)).fetchone()[0], 'active')
            dry_q_rc, dry_q_rep = mod.cmd_dry_run(SimpleNamespace(policy=str(pol_edit), policy_sha256=orig_digest_edit))
            self.assertEqual((dry_q_rc, dry_q_rep['outcome'], dry_q_rep['run_id']), (0, 'quarantined', run_edit))
            self.assertNotEqual(self._run_ledger('start', str(self.repo)).returncode, 0)

            i_unavail = self._create_issue('R8 checkout unavailable with requested digest')
            pol_unavail = self._write_policy('r8_unavail.json', issue_allowlist=[i_unavail])
            run_unavail = 'disp-r8-unavail-01'
            _, orig_digest_unavail, cand_unavail = seed_post_claim(run_unavail, i_unavail, pol_unavail)
            repo_bak = self.base / 'r8_repo_unavailable_bak'
            self.repo.rename(repo_bak)
            try:
                dry_u_rc, dry_u_rep = mod.cmd_dry_run(SimpleNamespace(policy=str(pol_unavail), policy_sha256=orig_digest_unavail))
                self.assertEqual((dry_u_rc, dry_u_rep['outcome'], dry_u_rep['run_id']), (0, 'recover_pending', run_unavail))

                with (
                    patch.object(mod, '_reconcile_stage_procs', wraps=orig_reconcile) as m_rec_u,
                    patch.object(mod, '_validate_local_beads_tracker') as m_vt_u,
                    patch.object(mod, '_preselect_candidate') as m_presel_u,
                    patch.object(mod, '_run_bound_bd_claim') as m_claim_u,
                    patch.object(mod.BwrapRunner, 'run_stage') as m_stage_u,
                ):
                    rc_u, rep_u = mod.cmd_tick(SimpleNamespace(policy=str(pol_unavail), policy_sha256=orig_digest_unavail))
                self.assertEqual(m_rec_u.call_count, 1)
                self.assertEqual((rc_u, rep_u['outcome'], rep_u['reason'], rep_u['candidate_sha']), (1, 'quarantined', 'git_checkout_layout_mismatch', cand_unavail))
                self.assertEqual(rep_u['claim_retained'], 'unknown')
                self.assertEqual((m_vt_u.call_count, m_presel_u.call_count, m_claim_u.call_count, m_stage_u.call_count), (0, 0, 0, 0))
                dry_uq_rc, dry_uq_rep = mod.cmd_dry_run(SimpleNamespace(policy=str(pol_unavail), policy_sha256=orig_digest_unavail))
                self.assertEqual((dry_uq_rc, dry_uq_rep['outcome'], dry_uq_rep['run_id']), (0, 'quarantined', run_unavail))
            finally:
                if repo_bak.exists() and not self.repo.exists():
                    repo_bak.rename(self.repo)
            with closing(sqlite3.connect(f'{db_path.resolve().as_uri()}?mode=ro', uri=True)) as conn:
                self.assertEqual(conn.execute('SELECT status FROM dispatch_stage_procs WHERE run_id = ?', (run_unavail,)).fetchone()[0], 'exited')
                self.assertEqual(conn.execute('SELECT status FROM runs WHERE run_id = ?', (run_unavail,)).fetchone()[0], 'active')
            self.assertNotEqual(self._run_ledger('start', str(self.repo)).returncode, 0)

            now_iso = mod.format_utc(mod.utc_now())
            with mod.open_dispatch_tx(db_path) as conn:
                conn.execute(
                    "INSERT INTO runs (run_id, repo_key, status, current_stage, wait_generation, commit_only, no_ci, with_deploy, with_honcho, with_wiki, created_at, updated_at) VALUES ('disp-ambig-2', '/tmp/other-repo/.git', 'active', 'admit', 0, 1, 0, 0, 0, 0, ?, ?)",
                    (now_iso, now_iso),
                )
                conn.execute(
                    "INSERT INTO dispatch_runs (run_id, repo_key, repo_root, beads_dir, issue_id, actor, policy_path, policy_digest, base_sha, fingerprint, dispatch_state, attempt, max_attempts, spend_usd, max_spend_usd, created_at, updated_at) VALUES ('disp-ambig-2', '/tmp/other-repo/.git', '/tmp/other-repo', '/tmp/other-repo/.beads', 'disp-x', 'disp-test:disp-ambig-2', ?, ?, ?, 'fp', 'working', 1, 2, 0.0, 0.0, ?, ?)",
                    (str(pol_unavail.resolve()), orig_digest_unavail, self.base_sha, now_iso, now_iso),
                )
            for fn in (
                lambda: mod.cmd_dry_run(SimpleNamespace(policy=str(pol_unavail), policy_sha256=orig_digest_unavail)),
                lambda: mod.cmd_tick(SimpleNamespace(policy=str(pol_unavail), policy_sha256=orig_digest_unavail)),
                lambda: mod.cmd_stop(SimpleNamespace(run_id=None, repo=None, policy=str(pol_unavail), policy_sha256=orig_digest_unavail, reason='ambig')),
            ):
                with self.assertRaisesRegex(mod.DispatchError, 'ambiguous'):
                    fn()

            with mod.open_dispatch_tx(db_path) as conn:
                for tbl in ('dispatch_stage_procs', 'dispatch_runs', 'runs'):
                    conn.execute(f'DELETE FROM {tbl}')

            i_fresh = self._create_issue('R8 fresh admission digest bound')
            pol_fresh = self._write_policy('r8_fresh.json', issue_allowlist=[i_fresh])
            wrong_digest = '0' * 64
            with self.assertRaisesRegex(mod.DispatchError, 'policy digest mismatch'):
                mod.cmd_dry_run(SimpleNamespace(policy=str(pol_fresh), policy_sha256=wrong_digest))
            with self.assertRaisesRegex(mod.DispatchError, 'policy digest mismatch'):
                mod.cmd_tick(SimpleNamespace(policy=str(pol_fresh), policy_sha256=wrong_digest))
            self.assertEqual(self._show_issue(i_fresh)['status'], 'open')

            i_unrel = self._create_issue('R8 unrelated run after race')
            pol_unrel = self._write_policy('r8_unrel.json', issue_allowlist=[i_unrel])
            run_unrel = 'disp-r8-unrel-01'
            pol_unrel_cfg, _, _ = seed_post_claim(run_unrel, i_unrel, pol_unrel)
            stale_located = {
                'run_id': 'disp-r8-gone-01',
                'repo_key': pol_unrel_cfg['repo_key'],
                'policy_path': str(pol_edit.resolve()),
                'policy_digest': orig_digest_edit,
                'dispatch_state': 'reviewing',
            }
            orig_locate = mod._locate_active_run_by_policy_path
            locate_calls = {'n': 0}

            def raced_locate(dbp, npp):
                locate_calls['n'] += 1
                if locate_calls['n'] == 1:
                    return stale_located
                return orig_locate(dbp, npp)

            with patch.object(mod, '_locate_active_run_by_policy_path', side_effect=raced_locate):
                with self.assertRaisesRegex(mod.DispatchError, 'policy digest mismatch'):
                    mod.cmd_tick(SimpleNamespace(policy=str(pol_edit), policy_sha256=orig_digest_edit))
            with closing(sqlite3.connect(f'{db_path.resolve().as_uri()}?mode=ro', uri=True)) as conn:
                conn.row_factory = sqlite3.Row
                unrel_row = conn.execute('SELECT dispatch_state, outcome FROM dispatch_runs WHERE run_id = ?', (run_unrel,)).fetchone()
                self.assertEqual((unrel_row['dispatch_state'], unrel_row['outcome']), ('reviewing', None))

            i_sym = self._create_issue('R8 symlinked parent policy directory recovery')
            disp_pol_dir = self.base / 'r8_disp_policies'
            disp_pol_dir.mkdir(mode=0o700)
            pol_sym_seed = self._write_policy('r8_sym_seed.json', issue_allowlist=[i_sym])
            pol_sym = disp_pol_dir / 'r8_sym.json'
            pol_sym.write_bytes(pol_sym_seed.read_bytes())
            os.chmod(pol_sym, 0o600)
            run_sym = 'disp-r8-sym-01'
            _, orig_digest_sym, cand_sym = seed_post_claim(run_sym, i_sym, pol_sym)

            disp_pol_moved = self.base / 'r8_disp_policies_moved'
            disp_pol_dir.rename(disp_pol_moved)
            disp_pol_dir.symlink_to(disp_pol_moved)
            moved_pol_sym = disp_pol_moved / 'r8_sym.json'
            moved_pol_data = json.loads(moved_pol_sym.read_text(encoding='utf-8'))
            moved_pol_data['timeouts']['run_sec'] = 120
            moved_pol_sym.write_text(json.dumps(moved_pol_data, indent=2), encoding='utf-8')
            os.chmod(moved_pol_sym, 0o600)

            with (
                patch.object(mod, '_validate_local_beads_tracker') as m_vt_s,
                patch.object(mod, '_preselect_candidate') as m_presel_s,
            ):
                dry_sym_rc, dry_sym_rep = mod.cmd_dry_run(SimpleNamespace(policy=str(pol_sym), policy_sha256=orig_digest_sym))
            self.assertEqual(
                (dry_sym_rc, dry_sym_rep['outcome'], dry_sym_rep['run_id'], dry_sym_rep['policy_digest']),
                (0, 'recover_pending', run_sym, orig_digest_sym),
            )
            self.assertEqual((m_vt_s.call_count, m_presel_s.call_count), (0, 0))

            with (
                patch.object(mod, '_reconcile_stage_procs', wraps=orig_reconcile) as m_rec_sym,
                patch.object(mod, '_validate_local_beads_tracker') as m_vt_sym,
                patch.object(mod, '_preselect_candidate') as m_presel_sym,
                patch.object(mod, '_run_bound_bd_claim') as m_claim_sym,
                patch.object(mod.BwrapRunner, 'run_stage') as m_stage_sym,
            ):
                rc_sym, rep_sym = mod.cmd_tick(SimpleNamespace(policy=str(pol_sym), policy_sha256=orig_digest_sym))
            self.assertEqual(m_rec_sym.call_count, 1)
            self.assertEqual(
                (rc_sym, rep_sym['outcome'], rep_sym['reason'], rep_sym['candidate_sha']),
                (1, 'quarantined', 'policy_digest_changed_on_recovery', cand_sym),
            )
            self.assertIs(rep_sym['claim_retained'], True)
            self.assertEqual((m_vt_sym.call_count, m_presel_sym.call_count, m_claim_sym.call_count, m_stage_sym.call_count), (0, 0, 0, 0))
            with closing(sqlite3.connect(f'{db_path.resolve().as_uri()}?mode=ro', uri=True)) as conn:
                self.assertEqual(conn.execute('SELECT status FROM dispatch_stage_procs WHERE run_id = ?', (run_sym,)).fetchone()[0], 'exited')
                self.assertEqual(conn.execute('SELECT status FROM runs WHERE run_id = ?', (run_sym,)).fetchone()[0], 'active')
            self.assertNotEqual(self._run_ledger('start', str(self.repo)).returncode, 0)

            now_iso_sym = mod.format_utc(mod.utc_now())
            with mod.open_dispatch_tx(db_path) as conn:
                conn.execute(
                    "INSERT INTO runs (run_id, repo_key, status, current_stage, wait_generation, commit_only, no_ci, with_deploy, with_honcho, with_wiki, created_at, updated_at) VALUES ('disp-r8-sym-ambig', '/tmp/other-sym/.git', 'active', 'admit', 0, 1, 0, 0, 0, 0, ?, ?)",
                    (now_iso_sym, now_iso_sym),
                )
                conn.execute(
                    "INSERT INTO dispatch_runs (run_id, repo_key, repo_root, beads_dir, issue_id, actor, policy_path, policy_digest, base_sha, fingerprint, dispatch_state, attempt, max_attempts, spend_usd, max_spend_usd, created_at, updated_at) VALUES ('disp-r8-sym-ambig', '/tmp/other-sym/.git', '/tmp/other-sym', '/tmp/other-sym/.beads', 'disp-sym-x', 'disp-test:disp-r8-sym-ambig', ?, ?, ?, 'fp', 'working', 1, 2, 0.0, 0.0, ?, ?)",
                    (str(moved_pol_sym.resolve()), orig_digest_sym, self.base_sha, now_iso_sym, now_iso_sym),
                )
            for fn in (
                lambda: mod.cmd_dry_run(SimpleNamespace(policy=str(pol_sym), policy_sha256=orig_digest_sym)),
                lambda: mod.cmd_tick(SimpleNamespace(policy=str(pol_sym), policy_sha256=orig_digest_sym)),
                lambda: mod.cmd_stop(SimpleNamespace(run_id=None, repo=None, policy=str(pol_sym), policy_sha256=orig_digest_sym, reason='sym ambig')),
            ):
                with self.assertRaisesRegex(mod.DispatchError, 'ambiguous'):
                    fn()

            i_repl = self._create_issue('R10 replacement run mismatch under stop gate')
            pol_repl_seed = self._write_policy('r10_repl_seed.json', issue_allowlist=[i_repl])
            run_repl = 'disp-r10-repl-01'
            pol_repl_cfg, _, _ = seed_post_claim(run_repl, i_repl, pol_repl_seed)
            pol_other_repo = self._write_policy('r10_other_repo.json', issue_allowlist=[i_repl], run_sec=90)
            other_digest_repo = sha256(pol_other_repo.read_bytes()).hexdigest()
            stale_stop_row = {
                'run_id': 'disp-r10-gone-01',
                'repo_key': pol_repl_cfg['repo_key'],
                'policy_path': str(pol_other_repo.resolve()),
                'policy_digest': other_digest_repo,
                'dispatch_state': 'reviewing',
            }
            stop_locate_calls = {'n': 0}

            def raced_stop_locate(dbp, npp):
                stop_locate_calls['n'] += 1
                if stop_locate_calls['n'] == 1:
                    return stale_stop_row
                return orig_locate(dbp, npp)

            try:
                with patch.object(mod, '_locate_active_run_by_policy_path', side_effect=raced_stop_locate):
                    with self.assertRaisesRegex(mod.DispatchError, 'policy digest mismatch'):
                        mod.cmd_stop(SimpleNamespace(
                            run_id=None, repo=None, policy=str(pol_other_repo), policy_sha256=other_digest_repo, reason='r10 repl',
                        ))
                self.assertFalse(mod._repo_stop_path(state_dir, pol_repl_cfg['repo_key']).exists())
                self.assertFalse(mod._run_stop_path(state_dir, run_repl).exists())
                self.assertFalse(mod._run_stop_path(state_dir, 'disp-r10-gone-01').exists())
                with closing(sqlite3.connect(f'{db_path.resolve().as_uri()}?mode=ro', uri=True)) as conn:
                    conn.row_factory = sqlite3.Row
                    repl_row = conn.execute(
                        'SELECT stop_requested, dispatch_state, outcome FROM dispatch_runs WHERE run_id = ?',
                        (run_repl,),
                    ).fetchone()
                    self.assertEqual((repl_row['stop_requested'], repl_row['dispatch_state'], repl_row['outcome']), (0, 'reviewing', None))
                    self.assertEqual(conn.execute('SELECT status FROM runs WHERE run_id = ?', (run_repl,)).fetchone()[0], 'active')
            finally:
                mod._run_stop_path(state_dir, run_repl).unlink(missing_ok=True)
                mod._repo_stop_path(state_dir, pol_repl_cfg['repo_key']).unlink(missing_ok=True)

            i_rev = self._create_issue('R5 policy revoke after branch advance')
            pol_rev = self._write_policy('r5_revoke.json', issue_allowlist=[i_rev])
            run_rev = 'disp-r5-revoke-01'
            pol_rev_cfg, orig_digest_rev, _ = seed_post_claim(run_rev, i_rev, pol_rev)

            (self.repo / 'other.txt').write_text('branch advanced\n', encoding='utf-8')
            self._git(self.repo, 'add', 'other.txt')
            self._git(self.repo, 'commit', '-m', 'advance main for policy revoke')
            adv_sha = self._git(self.repo, 'rev-parse', 'refs/heads/main').stdout.strip()
            self.assertNotEqual(adv_sha, self.base_sha)

            self._write_policy('r5_revoke.json', issue_allowlist=[i_rev], run_sec=120)
            edited_digest_rev = sha256(pol_rev.read_bytes()).hexdigest()
            self.assertNotEqual(edited_digest_rev, orig_digest_rev)
            self.assertNotEqual(other_digest_repo, orig_digest_rev)

            try:
                for bad_pol, bad_digest, bad_label in (
                    (pol_rev, edited_digest_rev, 'edited_digest'),
                    (pol_other_repo, other_digest_repo, 'fallback_repo_digest'),
                ):
                    with self.assertRaisesRegex(mod.DispatchError, 'policy digest mismatch'):
                        mod.cmd_stop(SimpleNamespace(
                            run_id=None, repo=None, policy=str(bad_pol), policy_sha256=bad_digest, reason=f'r10 {bad_label}',
                        ))
                    self.assertFalse(mod._repo_stop_path(state_dir, pol_rev_cfg['repo_key']).exists(), msg=bad_label)
                    self.assertFalse(mod._run_stop_path(state_dir, run_rev).exists(), msg=bad_label)
                    with closing(sqlite3.connect(f'{db_path.resolve().as_uri()}?mode=ro', uri=True)) as conn:
                        conn.row_factory = sqlite3.Row
                        r10_row = conn.execute(
                            'SELECT stop_requested, dispatch_state, outcome FROM dispatch_runs WHERE run_id = ?',
                            (run_rev,),
                        ).fetchone()
                        self.assertEqual((r10_row['stop_requested'], r10_row['dispatch_state'], r10_row['outcome']), (0, 'reviewing', None), msg=bad_label)
                        self.assertEqual(conn.execute('SELECT status FROM runs WHERE run_id = ?', (run_rev,)).fetchone()[0], 'active', msg=bad_label)

                with (
                    patch.object(mod, '_reconcile_stage_procs', wraps=orig_reconcile) as m_rec_s,
                    patch.object(mod, '_run_bound_bd_claim') as m_claim_s,
                ):
                    rc_s, rep_s = mod.cmd_stop(SimpleNamespace(
                        run_id=None, repo=None, policy=str(pol_rev), policy_sha256=orig_digest_rev, reason='r5 revoke',
                    ))
                self.assertEqual(m_rec_s.call_count, 1)
                self.assertEqual(m_claim_s.call_count, 0)
                self.assertEqual((rc_s, rep_s['outcome'], rep_s['reason']), (0, 'cancelled', 'stopped:r5 revoke'))
                self.assertIs(rep_s['claim_retained'], True)
                self.assertTrue(mod._repo_stop_path(state_dir, pol_rev_cfg['repo_key']).is_file())
                self.assertTrue(mod._run_stop_path(state_dir, run_rev).is_file())
                self.assertEqual(self._git(self.repo, 'rev-parse', 'refs/heads/main').stdout.strip(), adv_sha)
                self.assertEqual(self._git(self.repo, 'status', '--porcelain').stdout.strip(), '')
                with closing(sqlite3.connect(f'{db_path.resolve().as_uri()}?mode=ro', uri=True)) as conn:
                    self.assertEqual(conn.execute('SELECT status FROM runs WHERE run_id = ?', (run_rev,)).fetchone()[0], 'cancelled')
                    self.assertEqual(conn.execute('SELECT status FROM dispatch_stage_procs WHERE run_id = ?', (run_rev,)).fetchone()[0], 'exited')

                mod._repo_stop_path(state_dir, pol_rev_cfg['repo_key']).unlink(missing_ok=True)
                with mod.open_dispatch_tx(db_path) as conn:
                    for tbl in ('dispatch_stage_procs', 'dispatch_runs', 'runs'):
                        conn.execute(f'DELETE FROM {tbl}')
                rc_idle, rep_idle = mod.cmd_stop(SimpleNamespace(
                    run_id=None, repo=None, policy=str(pol_rev), policy_sha256=None, reason='r5 idle revoke',
                ))
                self.assertEqual((rc_idle, rep_idle['outcome'], rep_idle['repo_key']), (0, 'stop_requested', pol_rev_cfg['repo_key']))
                self.assertTrue(mod._repo_stop_path(state_dir, pol_rev_cfg['repo_key']).is_file())
                with self.assertRaisesRegex(mod.DispatchError, 'base_ref.*does not match pinned base_sha'):
                    mod.cmd_tick(SimpleNamespace(policy=str(pol_rev), policy_sha256=None))
            finally:
                mod._run_stop_path(state_dir, run_rev).unlink(missing_ok=True)
                mod._repo_stop_path(state_dir, pol_rev_cfg['repo_key']).unlink(missing_ok=True)

    def test_r8_parent_traversal_policy_selector_cannot_target_unrelated_reservation(self) -> None:
        mod = _load_dispatch_module()
        db_path = self.xdg_state / 'pi-team-run' / 'state.db'
        state_dir = self.xdg_state / 'pi-team-dispatch'
        issue_id = self._create_issue('R8 parent traversal cannot target unrelated row')
        pol_target = self._write_policy('r8_target.json', issue_allowlist=[issue_id])
        elsewhere = self.base / 'r8_elsewhere'
        elsewhere.mkdir(mode=0o700)
        other_pol = elsewhere / 'r8_target.json'
        other_pol.write_bytes(pol_target.read_bytes())
        os.chmod(other_pol, 0o600)
        trav_link = self.policy_dir / 'trav_link'
        trav_link.symlink_to(elsewhere)

        with patch.dict(os.environ, self.env, clear=True):
            mod.ensure_dispatch_dirs(state_dir)
            pol_cfg, pol_digest, pol_real = mod.load_and_validate_policy(
                str(pol_target), db_path=db_path, dispatch_state_dir=state_dir,
            )
            tracker = mod._validate_local_beads_tracker(self.repo)
            run_id = 'disp-r8-trav-01'
            actor = f'disp-test:{run_id}'
            claim = self._bd(self.repo, '--sandbox', '--actor', actor, 'update', issue_id, '--claim', '--json')
            self.assertEqual(claim.returncode, 0, msg=claim.stderr + claim.stdout)
            spec_fp = mod._issue_spec_fingerprint(self._show_issue(issue_id), pol_digest, self.base_sha)
            now_dt = mod.utc_now()
            now_iso = mod.format_utc(now_dt)
            deadline_iso = mod.format_utc(now_dt + timedelta(seconds=60))
            with mod.open_dispatch_tx(db_path) as conn:
                conn.execute(
                    "INSERT INTO runs (run_id, repo_key, status, current_stage, wait_generation, commit_only, no_ci, with_deploy, with_honcho, with_wiki, created_at, updated_at) VALUES (?, ?, 'active', 'admit', 0, 1, 0, 0, 0, 0, ?, ?)",
                    (run_id, pol_cfg['repo_key'], now_iso, now_iso),
                )
                conn.execute(
                    "INSERT INTO dispatch_runs (run_id, repo_key, repo_root, beads_dir, beads_db_path, beads_dir_dev, beads_dir_ino, beads_db_dev, beads_db_ino, git_common_dir_dev, git_common_dir_ino, issue_id, actor, policy_path, policy_digest, base_sha, fingerprint, dispatch_state, attempt, max_attempts, spend_usd, max_spend_usd, deadline_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'reviewing', 1, 2, 0.0, 0.0, ?, ?, ?)",
                    (run_id, pol_cfg['repo_key'], pol_cfg['repo_root'], tracker['beads_dir'], tracker['beads_db_path'], tracker['beads_dir_dev'], tracker['beads_dir_ino'], tracker['beads_db_dev'], tracker['beads_db_ino'], *self._seed_git_pin(pol_cfg['repo_key']), issue_id, actor, str(pol_real), pol_digest, self.base_sha, spec_fp, deadline_iso, now_iso, now_iso),
                )

            abs_trav = str(self.policy_dir / 'trav_link' / '..' / 'r8_target.json')
            cli_stop = self._run_dispatch('stop', '--policy', abs_trav, '--reason', 'trav stop', '--json')
            self.assertNotEqual(cli_stop.returncode, 0)
            self.assertIn('..', cli_stop.stderr)

            old_cwd = os.getcwd()
            try:
                os.chdir(self.policy_dir)
                for bad_spelling in (abs_trav, 'trav_link/../r8_target.json'):
                    for fn in (
                        lambda p=bad_spelling: mod.cmd_dry_run(SimpleNamespace(policy=p, policy_sha256=None)),
                        lambda p=bad_spelling: mod.cmd_tick(SimpleNamespace(policy=p, policy_sha256=None)),
                        lambda p=bad_spelling: mod.cmd_stop(SimpleNamespace(run_id=None, repo=None, policy=p, policy_sha256=None, reason='trav')),
                    ):
                        with self.assertRaisesRegex(mod.DispatchError, r'\.\.', msg=bad_spelling):
                            fn()

                self.assertFalse(mod._repo_stop_path(state_dir, pol_cfg['repo_key']).exists())
                self.assertFalse(mod._run_stop_path(state_dir, run_id).exists())
                with closing(sqlite3.connect(f'{db_path.resolve().as_uri()}?mode=ro', uri=True)) as conn:
                    conn.row_factory = sqlite3.Row
                    drow = conn.execute(
                        'SELECT stop_requested, dispatch_state, outcome FROM dispatch_runs WHERE run_id = ?',
                        (run_id,),
                    ).fetchone()
                    self.assertEqual((drow['stop_requested'], drow['dispatch_state'], drow['outcome']), (0, 'reviewing', None))
                    self.assertEqual(conn.execute('SELECT status FROM runs WHERE run_id = ?', (run_id,)).fetchone()[0], 'active')

                rel_rc, rel_rep = mod.cmd_dry_run(SimpleNamespace(policy='r8_target.json', policy_sha256=pol_digest))
                self.assertEqual((rel_rc, rel_rep['outcome'], rel_rep['run_id']), (0, 'recover_pending', run_id))
                dot_rc, dot_rep = mod.cmd_stop(SimpleNamespace(run_id=None, repo=None, policy='./r8_target.json', policy_sha256=pol_digest, reason='rel stop'))
                self.assertEqual((dot_rc, dot_rep['outcome'], dot_rep['run_id']), (0, 'cancelled', run_id))
            finally:
                os.chdir(old_cwd)
                mod._run_stop_path(state_dir, run_id).unlink(missing_ok=True)
                mod._repo_stop_path(state_dir, pol_cfg['repo_key']).unlink(missing_ok=True)

    def test_r10a_stop_rejects_mixed_selectors_with_terminal_and_active_runs(self) -> None:
        mod = _load_dispatch_module()
        db_path = self.xdg_state / 'pi-team-run' / 'state.db'
        state_dir = self.xdg_state / 'pi-team-dispatch'
        i_old = self._create_issue('R10a old terminal run')
        i_act = self._create_issue('R10a current active run')
        pol_old = self._write_policy('r10a_old.json', issue_allowlist=[i_old], run_sec=30)
        pol_act = self._write_policy('r10a_act.json', issue_allowlist=[i_act], run_sec=90)

        with patch.dict(os.environ, self.env, clear=True):
            mod.ensure_dispatch_dirs(state_dir)
            pol_old_cfg, old_digest, old_real = mod.load_and_validate_policy(
                str(pol_old), db_path=db_path, dispatch_state_dir=state_dir,
            )
            pol_act_cfg, act_digest, act_real = mod.load_and_validate_policy(
                str(pol_act), db_path=db_path, dispatch_state_dir=state_dir,
            )
            tracker = mod._validate_local_beads_tracker(self.repo)
            run_old = 'disp-r10a-old-01'
            run_act = 'disp-r10a-act-01'
            actor_act = f'disp-test:{run_act}'
            claim = self._bd(self.repo, '--sandbox', '--actor', actor_act, 'update', i_act, '--claim', '--json')
            self.assertEqual(claim.returncode, 0, msg=claim.stderr + claim.stdout)
            fp_old = mod._issue_spec_fingerprint(self._show_issue(i_old), old_digest, self.base_sha)
            fp_act = mod._issue_spec_fingerprint(self._show_issue(i_act), act_digest, self.base_sha)
            now_dt = mod.utc_now()
            now_iso = mod.format_utc(now_dt)
            deadline_iso = mod.format_utc(now_dt + timedelta(seconds=60))
            with mod.open_dispatch_tx(db_path) as conn:
                conn.execute(
                    "INSERT INTO runs (run_id, repo_key, status, current_stage, wait_generation, commit_only, no_ci, with_deploy, with_honcho, with_wiki, created_at, updated_at, completed_at) VALUES (?, ?, 'cancelled', NULL, 0, 1, 0, 0, 0, 0, ?, ?, ?)",
                    (run_old, pol_old_cfg['repo_key'], now_iso, now_iso, now_iso),
                )
                conn.execute(
                    "INSERT INTO dispatch_runs (run_id, repo_key, repo_root, beads_dir, beads_db_path, beads_dir_dev, beads_dir_ino, beads_db_dev, beads_db_ino, git_common_dir_dev, git_common_dir_ino, issue_id, actor, policy_path, policy_digest, base_sha, fingerprint, dispatch_state, attempt, max_attempts, spend_usd, max_spend_usd, outcome, reason, created_at, updated_at, completed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'cancelled', 1, 2, 0.0, 0.0, 'cancelled', 'stopped:old', ?, ?, ?)",
                    (run_old, pol_old_cfg['repo_key'], pol_old_cfg['repo_root'], tracker['beads_dir'], tracker['beads_db_path'], tracker['beads_dir_dev'], tracker['beads_dir_ino'], tracker['beads_db_dev'], tracker['beads_db_ino'], *self._seed_git_pin(pol_old_cfg['repo_key']), i_old, f'disp-test:{run_old}', str(old_real), old_digest, self.base_sha, fp_old, now_iso, now_iso, now_iso),
                )
                conn.execute(
                    "INSERT INTO runs (run_id, repo_key, status, current_stage, wait_generation, commit_only, no_ci, with_deploy, with_honcho, with_wiki, created_at, updated_at) VALUES (?, ?, 'active', 'admit', 0, 1, 0, 0, 0, 0, ?, ?)",
                    (run_act, pol_act_cfg['repo_key'], now_iso, now_iso),
                )
                conn.execute(
                    "INSERT INTO dispatch_runs (run_id, repo_key, repo_root, beads_dir, beads_db_path, beads_dir_dev, beads_dir_ino, beads_db_dev, beads_db_ino, git_common_dir_dev, git_common_dir_ino, issue_id, actor, policy_path, policy_digest, base_sha, fingerprint, dispatch_state, attempt, max_attempts, spend_usd, max_spend_usd, deadline_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'reviewing', 1, 2, 0.0, 0.0, ?, ?, ?)",
                    (run_act, pol_act_cfg['repo_key'], pol_act_cfg['repo_root'], tracker['beads_dir'], tracker['beads_db_path'], tracker['beads_dir_dev'], tracker['beads_dir_ino'], tracker['beads_db_dev'], tracker['beads_db_ino'], *self._seed_git_pin(pol_act_cfg['repo_key']), i_act, actor_act, str(act_real), act_digest, self.base_sha, fp_act, deadline_iso, now_iso, now_iso),
                )

            for ns in (
                SimpleNamespace(run_id=run_old, repo=str(self.repo), policy=None, policy_sha256=old_digest, reason='mix1'),
                SimpleNamespace(run_id=run_old, repo=None, policy=str(pol_act), policy_sha256=old_digest, reason='mix2'),
                SimpleNamespace(run_id=None, repo=str(self.repo), policy=str(pol_act), policy_sha256=act_digest, reason='mix3'),
            ):
                with self.assertRaisesRegex(mod.DispatchError, 'mutually exclusive'):
                    mod.cmd_stop(ns)

            cli1 = self._run_dispatch('stop', '--run-id', run_old, '--repo', str(self.repo), '--policy-sha256', old_digest, '--json')
            cli2 = self._run_dispatch('revoke', '--run-id', run_old, '--policy', str(pol_act), '--policy-sha256', old_digest, '--json')
            self.assertEqual(cli1.returncode, 2)
            self.assertEqual(cli2.returncode, 2)

            self.assertFalse(mod._repo_stop_path(state_dir, pol_act_cfg['repo_key']).exists())
            self.assertFalse(mod._run_stop_path(state_dir, run_old).exists())
            self.assertFalse(mod._run_stop_path(state_dir, run_act).exists())
            with closing(sqlite3.connect(f'{db_path.resolve().as_uri()}?mode=ro', uri=True)) as conn:
                conn.row_factory = sqlite3.Row
                act_row = conn.execute(
                    'SELECT stop_requested, dispatch_state, outcome FROM dispatch_runs WHERE run_id = ?',
                    (run_act,),
                ).fetchone()
                self.assertEqual((act_row['stop_requested'], act_row['dispatch_state'], act_row['outcome']), (0, 'reviewing', None))
                self.assertEqual(conn.execute('SELECT status FROM runs WHERE run_id = ?', (run_act,)).fetchone()[0], 'active')

    def test_r10b_reservation_commit_and_stop_share_per_repo_gate_lock(self) -> None:
        mod = _load_dispatch_module()
        db_path = self.xdg_state / 'pi-team-run' / 'state.db'
        state_dir = self.xdg_state / 'pi-team-dispatch'
        mod.ensure_dispatch_dirs(state_dir)

        i1 = self._create_issue('R10b stop wins gate before reservation')
        pol1 = self._write_policy('r10b_s1.json', issue_allowlist=[i1], run_sec=60)
        pol1_other = self._write_policy('r10b_s1_other.json', issue_allowlist=[i1], run_sec=90)
        pol1_cfg, pol1_digest, _ = mod.load_and_validate_policy(
            str(pol1), db_path=db_path, dispatch_state_dir=state_dir,
        )
        other_digest1 = sha256(pol1_other.read_bytes()).hexdigest()

        with patch.dict(os.environ, self.env, clear=True):
            stop_in_gate = threading.Event()
            tick_preselected = threading.Event()
            orig_write_marker = mod._write_stop_marker
            orig_preselect = mod._preselect_candidate
            marker_hook_done = {'done': False}

            def wrapped_write_marker(path, reason):
                if not marker_hook_done['done']:
                    marker_hook_done['done'] = True
                    stop_in_gate.set()
                    self.assertTrue(tick_preselected.wait(10.0), 'tick did not finish preselect while stop held gate')
                return orig_write_marker(path, reason)

            def wrapped_preselect(*args, **kwargs):
                res = orig_preselect(*args, **kwargs)
                if res.get('status') == 'selected':
                    tick_preselected.set()
                return res

            with (
                patch.object(mod, '_write_stop_marker', side_effect=wrapped_write_marker),
                patch.object(mod, '_preselect_candidate', side_effect=wrapped_preselect),
                ThreadPoolExecutor(max_workers=1) as pool,
            ):
                stop_fut = pool.submit(
                    mod.cmd_stop,
                    SimpleNamespace(
                        run_id=None, repo=None, policy=str(pol1_other), policy_sha256=other_digest1, reason='r10b gate first',
                    ),
                )
                self.assertTrue(stop_in_gate.wait(10.0), 'stop did not enter gate')
                rc1, rep1 = mod.cmd_tick(SimpleNamespace(policy=str(pol1), policy_sha256=pol1_digest))
                stop_rc, stop_rep = stop_fut.result(timeout=10.0)

            self.assertEqual((stop_rc, stop_rep['outcome']), (0, 'stop_requested'))
            self.assertEqual((rc1, rep1['outcome'], rep1['reason']), (1, 'cancelled', 'repo_stop_marker_active'))
            self.assertEqual(self._show_issue(i1)['status'], 'open')
            if db_path.exists():
                with closing(sqlite3.connect(f'{db_path.resolve().as_uri()}?mode=ro', uri=True)) as conn:
                    self.assertEqual(conn.execute('SELECT count(*) FROM runs').fetchone()[0], 0)
            mod._repo_stop_path(state_dir, pol1_cfg['repo_key']).unlink(missing_ok=True)

            i2 = self._create_issue('R10b tick commits under stop gate')
            pol2 = self._write_policy('r10b_s2.json', issue_allowlist=[i2], run_sec=60)
            pol2_other = self._write_policy('r10b_s2_other.json', issue_allowlist=[i2], run_sec=120)
            pol2_cfg, pol2_digest, _ = mod.load_and_validate_policy(
                str(pol2), db_path=db_path, dispatch_state_dir=state_dir,
            )
            repo_key2 = pol2_cfg['repo_key']
            other_digest2 = sha256(pol2_other.read_bytes()).hexdigest()
            stop_lock_path = state_dir / 'locks' / f'{sha256(repo_key2.encode()).hexdigest()[:16]}.stop.lock'

            def is_stop_lock_held() -> bool:
                fd = os.open(stop_lock_path, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
                try:
                    try:
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        return True
                    fcntl.flock(fd, fcntl.LOCK_UN)
                    return False
                finally:
                    os.close(fd)

            ev_lock = threading.Lock()
            events: list[tuple[object, ...]] = []
            stop_about_to_acquire = threading.Event()
            stop_result: dict[str, object] = {}
            orig_acquire_stop_gate = mod._acquire_stop_gate_lock
            orig_open_tx = mod.open_dispatch_tx
            orig_claim_reval = mod._claim_and_revalidate
            main_gate_seen = {'done': False}
            tx_seen = {'done': False}

            def run_concurrent_stop() -> None:
                try:
                    mod.cmd_stop(SimpleNamespace(
                        run_id=None, repo=None, policy=str(pol2_other), policy_sha256=other_digest2, reason='r10b mismatch after commit',
                    ))
                except BaseException as exc:
                    stop_result['exc'] = exc

            @contextmanager
            def wrapped_acquire_stop_gate(l_dir, r_key):
                if threading.current_thread().name == 'r10b-stop-thread':
                    stop_about_to_acquire.set()
                    with orig_acquire_stop_gate(l_dir, r_key):
                        with ev_lock:
                            events.append(('stop_gate_enter',))
                        yield
                elif not main_gate_seen['done']:
                    main_gate_seen['done'] = True
                    with orig_acquire_stop_gate(l_dir, r_key):
                        yield
                        with ev_lock:
                            events.append(('tick_gate_releasing',))
                else:
                    with orig_acquire_stop_gate(l_dir, r_key):
                        yield

            stop_thread = threading.Thread(target=run_concurrent_stop, name='r10b-stop-thread')

            @contextmanager
            def wrapped_open_tx(dbp):
                if not tx_seen['done']:
                    tx_seen['done'] = True
                    with orig_open_tx(dbp) as conn:
                        with ev_lock:
                            events.append(('tick_tx_enter', is_stop_lock_held()))
                        yield conn
                    with ev_lock:
                        events.append(('tick_tx_committed', is_stop_lock_held()))
                    stop_thread.start()
                    self.assertTrue(stop_about_to_acquire.wait(10.0), 'concurrent stop did not reach gate')
                else:
                    with orig_open_tx(dbp) as conn:
                        yield conn

            def wrapped_claim_reval(*args, **kwargs):
                stop_thread.join(timeout=10.0)
                self.assertFalse(stop_thread.is_alive())
                with ev_lock:
                    events.append(('tick_before_claim', is_stop_lock_held()))
                return orig_claim_reval(*args, **kwargs)

            with (
                patch.object(mod, '_acquire_stop_gate_lock', side_effect=wrapped_acquire_stop_gate),
                patch.object(mod, 'open_dispatch_tx', side_effect=wrapped_open_tx),
                patch.object(mod, '_claim_and_revalidate', side_effect=wrapped_claim_reval),
            ):
                rc2, rep2 = mod.cmd_tick(SimpleNamespace(policy=str(pol2), policy_sha256=pol2_digest))
            stop_thread.join(timeout=10.0)
            self.assertFalse(stop_thread.is_alive())

            self.assertEqual((rc2, rep2['outcome'], rep2['issue_id']), (0, 'candidate_ready', i2))
            self.assertIsInstance(stop_result.get('exc'), mod.DispatchError)
            self.assertIn('policy digest mismatch', str(stop_result['exc']))
            self.assertFalse(mod._repo_stop_path(state_dir, repo_key2).exists())
            self.assertFalse(mod._run_stop_path(state_dir, rep2['run_id']).exists())

            idx_enter = events.index(('tick_tx_enter', True))
            idx_commit = events.index(('tick_tx_committed', True))
            idx_release = events.index(('tick_gate_releasing',))
            idx_stop = events.index(('stop_gate_enter',))
            idx_claim = events.index(('tick_before_claim', False))
            self.assertLess(idx_enter, idx_commit)
            self.assertLess(idx_commit, idx_release)
            self.assertLess(idx_release, idx_stop)
            self.assertLess(idx_release, idx_claim)


if __name__ == '__main__':
    unittest.main()
