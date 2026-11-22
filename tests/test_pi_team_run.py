#!/usr/bin/env python3
"""Standard-library integration tests for pi-team-run."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import runpy
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
BIN_PATH = REPO_ROOT / 'pi' / '.pi' / 'agent' / 'bin' / 'pi-team-run'
SHA_A = 'a' * 40
SHA_B = 'b' * 40


class PiTeamRunTests(unittest.TestCase):
    """Fresh-process CLI tests using isolated temporary XDG state."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix='pi-team-run-test-')
        self.xdg_state = Path(self.tmp.name) / 'xdg-state'
        self.repo_dir = Path(self.tmp.name) / 'sample-repo'
        self.repo_dir.mkdir(parents=True, exist_ok=True)
        self.env = dict(os.environ, XDG_STATE_HOME=str(self.xdg_state))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(BIN_PATH), *args],
            env=self.env,
            text=True,
            capture_output=True,
            check=False,
        )

    def run_json(self, *args: str) -> dict | list:
        proc = self.run_cli(*args, '--json')
        self.assertEqual(proc.returncode, 0, msg=f'stderr={proc.stderr}\nstdout={proc.stdout}')
        return json.loads(proc.stdout)

    def watch_notices(self) -> list[dict]:
        proc = self.run_cli('watch')
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        return [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]

    def test_monitor_resumes_same_scope_and_checkpoints_verified_head(self) -> None:
        run = self.run_json('start', str(self.repo_dir))
        run_id = run['run_id']
        for stage in ('admit', 'implement', 'check', 'review', 'commit', 'publish'):
            self.run_json('checkpoint', run_id, stage, '--evidence', f'ev:{stage}')
        script = runpy.run_path(str(BIN_PATH))
        monitor = script['cmd_monitor']
        db = self.xdg_state / 'pi-team-run' / 'state.db'
        args = script['build_parser']().parse_args([
            'monitor', 'owner/repo', '--pr', '12', '--run-id', run_id, '--rev', SHA_A,
            '--require', 'build', '--require', 'test',
        ])
        pr = {'state': 'open', 'head': {'sha': SHA_A}}
        status = {'sha': SHA_A, 'statuses': [{'context': 'build', 'status': 'success'},
                                            {'context': 'test', 'status': 'failure'}]}
        with patch.dict(monitor.__globals__, {'forgejo_get': lambda _, __, path: pr if path.startswith('pulls/') else status}):
            with self.assertRaisesRegex(script['CliError'], 'required CI did not pass: test'):
                monitor(args, db)
            self.assertEqual(self.run_json('resume', run_id)['expected_rev'], SHA_A)
            args.require = ['build']
            with self.assertRaisesRegex(script['CliError'], 'required check set'):
                monitor(args, db)
            args.require = ['test', 'build']
            status['statuses'][1]['status'] = 'success'
            pr['head']['sha'] = SHA_B
            with self.assertRaisesRegex(script['CliError'], 'stale'):
                monitor(args, db)
            pr['head']['sha'] = SHA_A
            code, result = monitor(args, db)
        self.assertEqual((code, result['status']), (0, 'success'))
        self.assertEqual(self.run_json('status', run_id)['current_stage'], 'integrate')

    def test_background_watch_records_failure_then_success_without_coordinator(self) -> None:
        run_id = self.run_json('start', str(self.repo_dir))['run_id']
        for stage in ('admit', 'implement', 'check', 'review', 'commit', 'publish'):
            self.run_json('checkpoint', run_id, stage, '--evidence', f'ev:{stage}')
        queued = self.run_json('monitor', 'owner/repo', '--pr', '12', '--run-id', run_id,
                               '--rev', SHA_A, '--require', 'build', '--queue')
        self.assertEqual(queued['status'], 'queued')
        db = self.xdg_state / 'pi-team-run' / 'state.db'
        watch = runpy.run_path(str(BIN_PATH))['cmd_watch']
        pr = {'state': 'open', 'head': {'sha': SHA_A}}
        status = {'sha': SHA_A, 'statuses': [{'context': 'build', 'status': 'pending'}]}
        with patch.dict(watch.__globals__, {'forgejo_get': lambda _, __, path: pr if path.startswith('pulls/') else status}):
            self.assertEqual(watch(None, db), (0, []))
            status['statuses'][0]['status'] = 'failure'
            self.assertEqual(watch(None, db)[1][0]['reason'], 'ci_unverified')
            self.assertEqual(watch(None, db), (0, []))
            status['statuses'][0]['status'] = 'success'
            self.assertEqual(watch(None, db)[1][0]['reason'], 'ci_passed')
            self.assertEqual(watch(None, db), (0, []))
        final = self.run_json('status', run_id)
        self.assertEqual(final['current_stage'], 'integrate')
        self.assertEqual(final['checkpoints'][-1]['rev'], SHA_A)
        self.assertEqual(final['notices'][0]['reason'], 'ci_unverified')

    def test_monitor_never_treats_missing_skipped_or_old_success_as_current(self) -> None:
        script = runpy.run_path(str(BIN_PATH))
        waiting, failed = script['check_required']([
            {'context': 'scan', 'status': 'skipped'},
            {'context': 'test', 'status': 'pending'},
            {'context': 'test', 'status': 'success'},
        ], ['scan', 'test', 'build'])
        self.assertEqual(waiting, ['test', 'build'])
        self.assertEqual(failed, ['scan'])

    def test_private_xdg_state_and_schema_version_check(self) -> None:
        run = self.run_json('start', str(self.repo_dir))
        state_dir = self.xdg_state / 'pi-team-run'
        db_path = state_dir / 'state.db'
        self.assertEqual(stat.S_IMODE(state_dir.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(db_path.stat().st_mode), 0o600)

        with sqlite3.connect(str(db_path)) as conn:
            version = conn.execute('PRAGMA user_version').fetchone()[0]
            self.assertEqual(version, 1)
            conn.execute('PRAGMA user_version = 99')

        bad = self.run_cli('status', run['run_id'])
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn('schema version', bad.stderr.lower())

    def test_restart_to_ci_exact_match_and_terminal_frees_repo_key(self) -> None:
        started = self.run_json('start', str(self.repo_dir))
        run_id = started['run_id']
        self.assertEqual(started['current_stage'], 'admit')

        for stage in ('admit', 'implement', 'check', 'review', 'commit', 'publish'):
            self.run_json('checkpoint', run_id, stage, '--evidence', f'ev:{stage}')

        no_wait = self.run_cli('checkpoint', run_id, 'ci', '--rev', SHA_A, '--evidence', 'ci:1')
        self.assertNotEqual(no_wait.returncode, 0)
        self.assertIn('wait', no_wait.stderr.lower())

        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat().replace('+00:00', 'Z')
        self.run_json('wait', run_id, 'ci', '--target', 'ci', '--rev', SHA_A, '--deadline', future)

        resumed = self.run_json('resume', run_id)
        self.assertEqual(resumed['action'], 'await_ci')
        self.assertEqual(resumed['expected_rev'], SHA_A)
        self.assertFalse(resumed['authorized'])

        self.assertEqual(self.watch_notices(), [])

        short_sha = self.run_cli('checkpoint', run_id, 'ci', '--rev', SHA_A[:8], '--evidence', 'ci:1')
        self.assertNotEqual(short_sha.returncode, 0)

        wrong_sha = self.run_cli('checkpoint', run_id, 'ci', '--rev', SHA_B, '--evidence', 'ci:1')
        self.assertNotEqual(wrong_sha.returncode, 0)
        self.assertIn('mismatch', wrong_sha.stderr.lower())

        self.run_json('checkpoint', run_id, 'ci', '--rev', SHA_A, '--evidence', 'ci:1')
        self.run_json('checkpoint', run_id, 'integrate', '--evidence', 'merge:1')
        self.run_json('checkpoint', run_id, 'verify', '--evidence', 'verify:1')
        done = self.run_json('checkpoint', run_id, 'beads_close', '--evidence', 'bd:1')
        self.assertEqual(done['status'], 'completed')
        self.assertIsNone(done['current_stage'])

        restarted = self.run_json('start', str(self.repo_dir))
        self.assertNotEqual(restarted['run_id'], run_id)

    def test_duplicates_and_stale_operations(self) -> None:
        run_id = self.run_json('start', str(self.repo_dir) + '/')['run_id']
        dup = self.run_cli('start', str(self.repo_dir))
        self.assertNotEqual(dup.returncode, 0)
        self.assertIn('active run already exists', dup.stderr.lower())

        stale_ckpt = self.run_cli('checkpoint', run_id, 'implement', '--evidence', 'ev:impl')
        self.assertNotEqual(stale_ckpt.returncode, 0)
        self.assertIn('stale', stale_ckpt.stderr.lower())

        stale_wait = self.run_cli('wait', run_id, 'review', '--target', 'user')
        self.assertNotEqual(stale_wait.returncode, 0)

        self.run_json('wait', run_id, 'admit', '--target', 'user')
        dup_wait = self.run_cli('wait', run_id, 'admit', '--target', 'user')
        self.assertNotEqual(dup_wait.returncode, 0)

        self.run_json('checkpoint', run_id, 'admit', '--evidence', 'ev:admit')
        old_stage_ckpt = self.run_cli('checkpoint', run_id, 'admit', '--evidence', 'ev:again')
        self.assertNotEqual(old_stage_ckpt.returncode, 0)

    def test_optional_opt_in_and_explicit_skip_rules(self) -> None:
        run = self.run_json(
            'start',
            str(self.repo_dir),
            '--with-deploy',
            '--with-honcho',
            '--with-wiki',
        )
        run_id = run['run_id']
        self.assertIn('deploy', run['active_stages'])
        self.assertIn('honcho', run['active_stages'])
        self.assertIn('wiki', run['active_stages'])

        bad_skip = self.run_cli('checkpoint', run_id, 'admit', '--skip', '--evidence', 'skip:no')
        self.assertNotEqual(bad_skip.returncode, 0)

        for stage in ('admit', 'implement', 'check', 'review', 'commit', 'publish'):
            self.run_json('checkpoint', run_id, stage, '--evidence', f'ev:{stage}')

        future = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat().replace('+00:00', 'Z')
        self.run_json('wait', run_id, 'ci', '--target', 'ci', '--rev', SHA_A, '--deadline', future)
        self.run_json('checkpoint', run_id, 'ci', '--rev', SHA_A, '--evidence', 'ci:ok')
        self.run_json('checkpoint', run_id, 'integrate', '--evidence', 'int:ok')
        self.run_json('checkpoint', run_id, 'verify', '--evidence', 'ver:ok')
        self.run_json('checkpoint', run_id, 'deploy', '--evidence', 'dep:ok')
        self.run_json('checkpoint', run_id, 'beads_close', '--evidence', 'bd:ok')
        self.run_json('checkpoint', run_id, 'honcho', '--skip', '--evidence', 'skip:honcho')
        done = self.run_json('checkpoint', run_id, 'wiki', '--evidence', 'wiki:ok')
        self.assertEqual(done['status'], 'completed')

    def test_watcher_dedupe_no_advance_and_wait_routing(self) -> None:
        run_id = self.run_json('start', str(self.repo_dir))['run_id']
        self.run_json('wait', run_id, 'admit', '--target', 'user', '--reason', 'approve claim')

        resumed = self.run_json('resume', run_id)
        self.assertEqual(resumed['action'], 'await_user')
        self.assertFalse(resumed['authorized'])

        first_notices = self.watch_notices()
        self.assertEqual(len(first_notices), 1)
        self.assertEqual(first_notices[0]['target'], 'user')
        self.assertEqual(first_notices[0]['wait_generation'], 1)
        self.assertEqual(self.watch_notices(), [])

        self.run_json('checkpoint', run_id, 'admit', '--evidence', 'ev:admit')
        self.run_json('wait', run_id, 'implement', '--target', 'coordinator', '--reason', 'assign worker')
        coord_resume = self.run_json('resume', run_id)
        self.assertEqual(coord_resume['action'], 'await_coordinator')
        self.assertFalse(coord_resume['authorized'])
        coord_notices = self.watch_notices()
        self.assertEqual(len(coord_notices), 1)
        self.assertEqual(coord_notices[0]['target'], 'coordinator')
        self.assertEqual(coord_notices[0]['wait_generation'], 2)
        self.assertEqual(self.watch_notices(), [])

        self.run_json('checkpoint', run_id, 'implement', '--evidence', 'ev:implement')
        for stage in ('check', 'review', 'commit', 'publish'):
            self.run_json('checkpoint', run_id, stage, '--evidence', f'ev:{stage}')

        past = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat().replace('+00:00', 'Z')
        self.run_json('wait', run_id, 'ci', '--target', 'ci', '--rev', SHA_A, '--deadline', past)

        overdue = self.watch_notices()
        self.assertEqual(len(overdue), 1)
        self.assertEqual(overdue[0]['target'], 'coordinator')
        self.assertEqual(overdue[0]['wait_target'], 'ci')
        self.assertEqual(overdue[0]['reason'], 'ci_overdue')
        self.assertEqual(overdue[0]['wait_generation'], 3)
        self.assertEqual(self.watch_notices(), [])

        still_waiting = self.run_json('status', run_id)
        self.assertEqual(still_waiting['status'], 'waiting')
        self.assertEqual(still_waiting['current_stage'], 'ci')

    def test_parallel_start_and_watcher(self) -> None:
        with ThreadPoolExecutor(2) as pool:
            starts = list(pool.map(lambda _: self.run_cli('start', str(self.repo_dir)), range(2)))
            self.assertEqual(sorted(proc.returncode for proc in starts), [0, 1])
            run_id = json.loads(next(proc.stdout for proc in starts if proc.returncode == 0))['run_id']
            self.run_json('start', 'other-repo')
            self.run_json('wait', run_id, 'admit', '--target', 'user')
            notices = list(pool.map(lambda _: self.watch_notices(), range(2)))
            self.assertEqual(sorted(map(len, notices)), [0, 1])
        self.assertEqual(self.run_json('status', run_id)['current_stage'], 'admit')

    def test_delivery_scope_selected_at_start(self) -> None:
        local = self.run_json('start', 'local-only', '--commit-only')
        self.assertEqual(local['active_stages'][-1], 'commit')
        for stage in local['active_stages']:
            done = self.run_json('checkpoint', local['run_id'], stage, '--evidence', 'ev:receipt')
        self.assertEqual(done['status'], 'completed')
        no_ci = self.run_json('start', 'no-ci-repo', '--no-ci')
        self.assertNotIn('ci', no_ci['active_stages'])
        self.assertIn('integrate', no_ci['active_stages'])

    def test_cancel_requires_current_stage_and_frees_repo_key(self) -> None:
        run_id = self.run_json('start', str(self.repo_dir))['run_id']
        self.run_json('checkpoint', run_id, 'admit', '--evidence', 'ev:admit')

        wrong_cancel = self.run_cli('cancel', run_id, 'admit')
        self.assertNotEqual(wrong_cancel.returncode, 0)

        cancelled = self.run_json('cancel', run_id, 'implement', '--reason', 'aborted')
        self.assertEqual(cancelled['status'], 'cancelled')
        self.assertEqual(cancelled['cancelled_stage'], 'implement')
        self.assertIsNone(cancelled['current_stage'])

        again = self.run_cli('cancel', run_id, 'implement')
        self.assertNotEqual(again.returncode, 0)

        restarted = self.run_json('start', str(self.repo_dir))
        self.assertEqual(restarted['status'], 'active')


if __name__ == '__main__':
    unittest.main()
