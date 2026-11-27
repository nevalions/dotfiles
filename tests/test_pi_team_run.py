#!/usr/bin/env python3
"""Standard-library integration tests for pi-team-run."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
import runpy
import os
from pathlib import Path
import shutil
import signal
import sqlite3
import stat
import subprocess
import sys
import tempfile
import threading
import time
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

    def test_delivery_profile_is_read_only_and_host_scoped(self) -> None:
        repo = 'nevalions/frontend-angular-signals'
        profile = self.run_json('delivery-profile', repo)
        self.assertFalse(profile['grants_authority'])
        self.assertEqual(profile['base'], 'master')
        self.assertEqual(len(profile['pr_checks']), 8)
        self.assertIn('CI / publish-image (push)', profile['push_checks'])
        self.assertFalse(self.xdg_state.exists())
        self.assertNotEqual(self.run_cli('delivery-profile', repo, '--host', 'example.org').returncode, 0)
        self.assertNotEqual(self.run_cli('monitor', repo, '--profile', '--require', 'test', '--rev', SHA_A).returncode, 0)

    def test_profile_queue_checks_base_and_frozen_policy(self) -> None:
        repo = 'nevalions/frontend-angular-signals'
        profile = self.run_json('delivery-profile', repo)
        run_id = self.run_json('start', str(self.repo_dir))['run_id']
        for stage in ('admit', 'implement', 'check', 'review', 'commit', 'publish'):
            self.run_json('checkpoint', run_id, stage, '--evidence', f'ev:{stage}')
        self.run_json('monitor', repo, '--pr', '12', '--run-id', run_id,
                      '--rev', SHA_A, '--profile', '--queue')
        db = self.xdg_state / 'pi-team-run' / 'state.db'
        poll = runpy.run_path(str(BIN_PATH))['poll_queued_ci']
        pr = {'state': 'open', 'head': {'sha': SHA_A}, 'base': {'ref': 'wrong', 'repo': {'full_name': repo}}}
        status = {'sha': SHA_A, 'statuses': [{'context': name, 'status': 'success'} for name in profile['pr_checks']]}
        with patch.dict(poll.__globals__, {'forgejo_get': lambda _, __, path: pr if path.startswith('pulls/') else status}):
            self.assertIn('PR target does not match', next(iter(poll(db)[1].values())))
            current = poll.__globals__['DELIVERY_PROFILES'][('git.butakov.su', repo)]
            with patch.dict(current, {'pr_checks': ['different']}):
                self.assertIn('checks changed', next(iter(poll(db)[1].values())))
            pr['base']['ref'] = 'master'
            self.assertEqual(poll(db)[0][0]['reason'], 'ci_passed')
        self.assertEqual(self.run_json('status', run_id)['current_stage'], 'integrate')

    def test_profile_post_merge_requires_current_base_and_image_publication(self) -> None:
        repo = 'nevalions/frontend-angular-signals'
        script = runpy.run_path(str(BIN_PATH))
        monitor = script['cmd_monitor']
        args = script['build_parser']().parse_args(['monitor', repo, '--rev', SHA_A, '--profile'])
        args.once = True
        branch = {'commit': {'id': SHA_B}}
        status = {'sha': SHA_A, 'statuses': [{'context': 'CI / quality-gate (push)', 'status': 'success'}]}
        with patch.dict(monitor.__globals__, {'forgejo_get': lambda _, __, path: branch if path.startswith('branches/') else status}):
            with self.assertRaisesRegex(script['CliError'], 'base tip does not match'):
                monitor(args, self.xdg_state)
            branch['commit']['id'] = SHA_A
            self.assertEqual(monitor(args, self.xdg_state)[1]['status'], 'pending')
            status['statuses'].append({'context': 'CI / publish-image (push)', 'status': 'success'})
            self.assertEqual(monitor(args, self.xdg_state)[1]['status'], 'success')

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

        with closing(sqlite3.connect(str(db_path))) as conn, conn:
            version = conn.execute('PRAGMA user_version').fetchone()[0]
            self.assertEqual(version, 3)
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

    def linked_pair(self):
        def git(*args):
            subprocess.run(['git', '-C', str(self.repo_dir), '-c', 'user.name=Test',
                            '-c', 'user.email=test@example.invalid', '-c', 'commit.gpgsign=false', *args],
                           check=True, capture_output=True)
        git('init')
        git('commit', '--allow-empty', '-m', 'base')
        a, b = (str(Path(self.tmp.name) / name) for name in ('task-a', 'task-b'))
        for path in (a, b):
            git('worktree', 'add', path)
        return a, b

    def test_scoped_admission_and_shared_delivery_race(self):
        a, b = self.linked_pair()
        self.assertNotEqual(self.run_cli('start', str(self.repo_dir), '--issue', 'repo-1').returncode, 0)
        with ThreadPoolExecutor(2) as pool:
            futures = [pool.submit(self.run_cli, 'start', path, '--issue', 'repo-1') for path in (a, b)]
            results = [f.result() for f in futures]
        self.assertEqual(sorted(p.returncode for p in results), [0, 1])
        win = next(i for i, p in enumerate(results) if not p.returncode)
        first = json.loads(results[win].stdout)['run_id']
        alias = Path(self.tmp.name) / 'alias'
        alias.symlink_to((a, b)[win])
        self.assertNotEqual(self.run_cli('start', str(alias), '--issue', 'repo-2').returncode, 0)
        self.assertNotEqual(self.run_cli('start', str(self.repo_dir)).returncode, 0)
        for stage in ('admit', 'implement', 'check', 'review', 'commit', 'publish'):
            self.run_json('checkpoint', first, stage, '--evidence', stage)
        self.run_json('wait', first, 'ci', '--target', 'ci', '--rev', SHA_A,
                      '--deadline', '2030-01-01T00:00:00Z')
        other = self.run_json('start', (a, b)[1-win], '--issue', 'repo-2')['run_id']
        for stage in ('admit', 'implement', 'check', 'review', 'commit', 'publish'):
            self.run_json('checkpoint', other, stage, '--evidence', stage)
        self.run_json('wait', other, 'ci', '--target', 'ci', '--rev', SHA_B,
                      '--deadline', '2030-01-01T00:00:00Z')
        for run, rev in ((first, SHA_A), (other, SHA_B)):
            self.run_json('checkpoint', run, 'ci', '--rev', rev, '--evidence', rev)
            self.assertEqual(self.run_json('resume', run)['action'], 'reserve')
            self.assertNotEqual(self.run_cli('checkpoint', run, 'integrate', '--evidence', 'early').returncode, 0)
        with ThreadPoolExecutor(2) as pool:
            futures = [pool.submit(self.run_cli, 'reserve', run, 'integrate') for run in (first, other)]
            results = [f.result() for f in futures]
        self.assertEqual(sorted(p.returncode for p in results), [0, 1])
        owner, waiter = (first, other) if results[0].returncode == 0 else (other, first)
        self.run_json('reserve', owner, 'integrate')
        self.run_json('checkpoint', owner, 'integrate', '--evidence', 'merged')
        self.assertIn(owner, self.run_cli('reserve', waiter, 'integrate').stderr)
        self.run_json('checkpoint', owner, 'verify', '--evidence', 'verified')
        self.run_json('reserve', waiter, 'integrate')
        self.assertIn(waiter, self.run_cli('reserve', owner, 'beads_close').stderr)
        self.run_json('cancel', waiter, 'integrate')
        self.run_json('reserve', owner, 'beads_close')
        self.assertFalse(self.run_json('checkpoint', owner, 'beads_close', '--evidence', 'sync')['reserved'])
        self.run_json('start', str(self.repo_dir))

    def test_no_ci_publish_and_optional_closeout_reservations(self):
        a, b = self.linked_pair()
        run = self.run_json('start', a, '--issue', 'repo-1', '--no-ci', '--with-deploy', '--with-wiki')['run_id']
        other = self.run_json('start', b, '--issue', 'repo-2', '--commit-only')['run_id']
        for stage in ('admit', 'implement', 'check', 'review', 'commit'):
            self.run_json('checkpoint', run, stage, '--evidence', stage)
        self.assertNotEqual(self.run_cli('checkpoint', run, 'publish', '--evidence', 'early').returncode, 0)
        self.run_json('reserve', run, 'publish')
        self.run_json('wait', run, 'publish', '--target', 'coordinator')
        self.assertIn(run, self.run_cli('reserve', other, 'admit').stderr)
        for stage in ('publish', 'integrate', 'verify', 'deploy'):
            result = self.run_json('checkpoint', run, stage, '--evidence', stage)
            self.assertEqual(result['reserved'], stage != 'deploy')
        self.run_json('reserve', run, 'beads_close')
        self.run_json('checkpoint', run, 'beads_close', '--evidence', 'synced')
        self.run_json('reserve', other, 'admit')
        self.assertNotEqual(self.run_cli('checkpoint', run, 'wiki', '--evidence', 'published').returncode, 0)
        self.run_json('checkpoint', run, 'wiki', '--skip', '--evidence', 'skip:not-applicable')
        self.assertFalse(self.run_json('checkpoint', other, 'admit', '--evidence', 'claimed')['reserved'])

    def test_startup_discovery_is_scoped_read_only_and_handles_missing_worktree(self):
        a, b = self.linked_pair()
        self.assertEqual(self.run_json('discover', str(self.repo_dir)), [])
        self.assertFalse(self.xdg_state.exists())
        self.run_json('start', 'other-repo')
        run = self.run_json('start', a, '--issue', 'repo-1')['run_id']
        row, = self.run_json('discover', b)
        self.assertEqual(row, dict(issue='repo-1', run_id=run, stage='admit', status='active', worktree=a))
        subprocess.run(['git', '-C', str(self.repo_dir), 'worktree', 'remove', a], check=True)
        self.assertIsNone(self.run_json('discover', str(self.repo_dir))[0]['worktree'])
        self.run_json('cancel', run, 'admit')
        self.assertEqual(self.run_json('discover', b), [])
        legacy = self.run_json('start', str(self.repo_dir))['run_id']
        self.assertEqual(self.run_json('discover', b)[0]['run_id'], legacy)
        self.assertIsNone(self.run_json('discover', b)[0]['issue'])

    def test_v1_run_stays_exclusive_across_migration(self):
        a, _ = self.linked_pair()
        db = self.xdg_state / 'pi-team-run/state.db'
        db.parent.mkdir(parents=True)
        with closing(sqlite3.connect(db)) as conn, conn:
            for stmt in runpy.run_path(str(BIN_PATH))['V1_SCHEMA']:
                conn.execute(stmt)
            conn.execute('PRAGMA user_version = 1')
            conn.execute("INSERT INTO runs(run_id,repo_key,status,current_stage,created_at,updated_at) "
                         "VALUES ('legacy',?,'active','implement','now','now')", (str(self.repo_dir),))
        self.assertIsNone(self.run_json('status', 'legacy')['issue'])
        with closing(sqlite3.connect(db)) as conn:
            self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0], 1)
        self.assertIn('legacy', self.run_cli('start', a, '--issue', 'repo-1').stderr)
        self.run_json('checkpoint', 'legacy', 'implement', '--evidence', 'old-work')
        self.assertIn('legacy', self.run_cli('start', a, '--issue', 'repo-1').stderr)
        self.run_json('cancel', 'legacy', 'check')
        self.run_json('start', a, '--issue', 'repo-1')

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
        self.assertEqual(local['active_stages'], ['admit', 'implement', 'check', 'review', 'commit'])
        for stage in local['active_stages']:
            done = self.run_json('checkpoint', local['run_id'], stage, '--evidence', 'ev:receipt')
        self.assertEqual(done['status'], 'completed')
        no_ci = self.run_json('start', 'no-ci-repo', '--no-ci')
        self.assertNotIn('ci', no_ci['active_stages'])
        self.assertIn('integrate', no_ci['active_stages'])

    def test_commit_only_closeout_opt_ins_and_rejections(self) -> None:
        for bad_flags in (
            ('--no-ci',),
            ('--with-deploy',),
            ('--with-honcho', '--no-ci'),
            ('--with-wiki', '--with-deploy'),
        ):
            bad = self.run_cli('start', 'bad-commit-only', '--commit-only', *bad_flags)
            self.assertNotEqual(bad.returncode, 0)
            self.assertIn('--commit-only', bad.stderr)

        honcho_only = self.run_json('start', 'repo-honcho', '--commit-only', '--with-honcho')
        self.assertEqual(
            honcho_only['active_stages'],
            ['admit', 'implement', 'check', 'review', 'commit', 'honcho'],
        )
        for stage in ('admit', 'implement', 'check', 'review'):
            self.run_json('checkpoint', honcho_only['run_id'], stage, '--evidence', f'ev:{stage}')
        premature = self.run_cli('checkpoint', honcho_only['run_id'], 'honcho', '--evidence', 'honcho:early')
        self.assertNotEqual(premature.returncode, 0)
        after_commit = self.run_json('checkpoint', honcho_only['run_id'], 'commit', '--evidence', 'git:commit-1')
        self.assertEqual(after_commit['status'], 'active')
        self.assertEqual(after_commit['current_stage'], 'honcho')
        done_honcho = self.run_json('checkpoint', honcho_only['run_id'], 'honcho', '--evidence', 'honcho:conclusion-1')
        self.assertEqual(done_honcho['status'], 'completed')
        self.assertIsNone(done_honcho['current_stage'])
        self.assertEqual(done_honcho['checkpoints'][-1]['disposition'], 'completed')

        wiki_only = self.run_json('start', 'repo-wiki', '--commit-only', '--with-wiki')
        self.assertEqual(
            wiki_only['active_stages'],
            ['admit', 'implement', 'check', 'review', 'commit', 'wiki'],
        )
        for stage in ('admit', 'implement', 'check', 'review', 'commit'):
            after = self.run_json('checkpoint', wiki_only['run_id'], stage, '--evidence', f'ev:{stage}')
        self.assertEqual(after['status'], 'active')
        self.assertEqual(after['current_stage'], 'wiki')
        done_wiki = self.run_json(
            'checkpoint', wiki_only['run_id'], 'wiki', '--skip', '--evidence', 'skip:draft:no-wiki-auth',
        )
        self.assertEqual(done_wiki['status'], 'completed')
        self.assertIsNone(done_wiki['current_stage'])
        self.assertEqual(done_wiki['checkpoints'][-1]['disposition'], 'skipped')

        both = self.run_json('start', 'repo-both', '--commit-only', '--with-honcho', '--with-wiki')
        self.assertEqual(
            both['active_stages'],
            ['admit', 'implement', 'check', 'review', 'commit', 'honcho', 'wiki'],
        )
        for stage in ('admit', 'implement', 'check', 'review', 'commit'):
            state = self.run_json('checkpoint', both['run_id'], stage, '--evidence', f'ev:{stage}')
        self.assertEqual(state['status'], 'active')
        self.assertEqual(state['current_stage'], 'honcho')
        out_of_order = self.run_cli('checkpoint', both['run_id'], 'wiki', '--evidence', 'wiki:early')
        self.assertNotEqual(out_of_order.returncode, 0)
        mid = self.run_json(
            'checkpoint', both['run_id'], 'honcho', '--skip', '--evidence', 'skip:not-applicable:no-facts',
        )
        self.assertEqual(mid['status'], 'active')
        self.assertEqual(mid['current_stage'], 'wiki')
        done_both = self.run_json('checkpoint', both['run_id'], 'wiki', '--evidence', 'wiki:commit-abc')
        self.assertEqual(done_both['status'], 'completed')
        self.assertIsNone(done_both['current_stage'])

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

    def test_canonicalize_repo_fails_closed_on_timeout_error_and_malformed_git_identity(self) -> None:
        git_repo = Path(self.tmp.name) / 'git-repo'
        worktree = Path(self.tmp.name) / 'git-wt'
        git_repo.mkdir()
        git_env = {
            'PATH': os.environ.get('PATH', '/usr/bin:/bin'),
            'HOME': '/nonexistent',
            'LANG': 'C.UTF-8',
            'LC_ALL': 'C.UTF-8',
            'GIT_CONFIG_NOSYSTEM': '1',
            'GIT_CONFIG_GLOBAL': '/dev/null',
            'GIT_TERMINAL_PROMPT': '0',
        }
        subprocess.run(['git', '-C', str(git_repo), 'init', '-b', 'main'], env=git_env, check=True, capture_output=True)
        subprocess.run(['git', '-C', str(git_repo), 'config', 'user.name', 'Test'], env=git_env, check=True, capture_output=True)
        subprocess.run(['git', '-C', str(git_repo), 'config', 'user.email', 'test@local.invalid'], env=git_env, check=True, capture_output=True)
        (git_repo / 'README.md').write_text('hello\n', encoding='utf-8')
        subprocess.run(['git', '-C', str(git_repo), 'add', 'README.md'], env=git_env, check=True, capture_output=True)
        subprocess.run(['git', '-C', str(git_repo), 'commit', '-m', 'init'], env=git_env, check=True, capture_output=True)
        subprocess.run(['git', '-C', str(git_repo), 'worktree', 'add', str(worktree), '-b', 'wt'], env=git_env, check=True, capture_output=True)

        started = self.run_json('start', str(git_repo))
        self.assertEqual(started['repo_key'], str((git_repo / '.git').resolve()))

        script = runpy.run_path(str(BIN_PATH))
        cmd_start = script['cmd_start']
        canonicalize = script['canonicalize_repo']
        parser = script['build_parser']()
        db_path = self.xdg_state / 'pi-team-run' / 'state.db'

        with patch.dict(canonicalize.__globals__, {'subprocess': type('Sub', (), {
            'TimeoutExpired': subprocess.TimeoutExpired,
            'run': staticmethod(lambda *a, **kw: (_ for _ in ()).throw(subprocess.TimeoutExpired(['git'], 5))),
        })()}):
            with self.assertRaisesRegex(script['CliError'], 'identity lookup failed'):
                cmd_start(parser.parse_args(['start', str(worktree)]), db_path)

        with patch.dict(canonicalize.__globals__, {'subprocess': type('Sub', (), {
            'TimeoutExpired': subprocess.TimeoutExpired,
            'run': staticmethod(lambda *a, **kw: (_ for _ in ()).throw(OSError('git unavailable'))),
        })()}):
            with self.assertRaisesRegex(script['CliError'], 'identity lookup failed'):
                cmd_start(parser.parse_args(['start', str(worktree)]), db_path)

        bad_out = subprocess.CompletedProcess(['git'], 0, stdout='relative/path\n', stderr='')
        with patch.dict(canonicalize.__globals__, {'subprocess': type('Sub', (), {
            'TimeoutExpired': subprocess.TimeoutExpired,
            'run': staticmethod(lambda *a, **kw: bad_out),
        })()}):
            with self.assertRaisesRegex(script['CliError'], 'unresolvable git common-dir'):
                canonicalize(str(worktree))

        broken_wt = Path(self.tmp.name) / 'broken-wt'
        broken_wt.mkdir()
        (broken_wt / '.git').write_text('gitdir: /nonexistent/gitdir\n', encoding='utf-8')
        with self.assertRaisesRegex(script['CliError'], 'unable to resolve git repository identity'):
            canonicalize(str(broken_wt))

        active = self.run_json('status')
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]['run_id'], started['run_id'])

        self.assertEqual(canonicalize(str(self.repo_dir)), str(self.repo_dir.resolve()))
        self.assertEqual(canonicalize('opaque-id'), 'opaque-id')

    def test_v2_read_only_discovery_defers_migration_until_write(self) -> None:
        a, b = self.linked_pair()
        repo_key = str((self.repo_dir / '.git').resolve())
        wt_a_admin = str((self.repo_dir / '.git' / 'worktrees' / 'task-a').resolve())
        db = self.xdg_state / 'pi-team-run' / 'state.db'
        db.parent.mkdir(parents=True)
        script = runpy.run_path(str(BIN_PATH))
        with closing(sqlite3.connect(db)) as conn, conn:
            for stmt in script['V1_SCHEMA']:
                conn.execute(stmt)
            for stmt in script['V2_MIGRATION']:
                conn.execute(stmt)
            conn.execute('PRAGMA user_version = 2')
            conn.execute(
                "INSERT INTO runs(run_id,repo_key,issue,worktree,status,current_stage,created_at,updated_at) "
                "VALUES ('v2-scoped',?, 'repo-1', ?, 'active', 'implement', 'now', 'now')",
                (repo_key, wt_a_admin),
            )

        discovered = self.run_json('discover', b)
        self.assertEqual(len(discovered), 1)
        self.assertEqual(discovered[0]['run_id'], 'v2-scoped')
        self.assertEqual(discovered[0]['issue'], 'repo-1')
        self.assertEqual(self.run_json('status', 'v2-scoped')['issue'], 'repo-1')
        preflight = self.run_json('preflight', b)
        self.assertNotIn('writer_fence_open', preflight)
        self.assertTrue(preflight['linked_worktree'])

        with closing(sqlite3.connect(db)) as conn:
            self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0], 2)
            self.assertIsNone(
                conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='writer_attempts'").fetchone()
            )

        second = self.run_json('start', b, '--issue', 'repo-2')
        self.assertEqual(second['issue'], 'repo-2')
        with closing(sqlite3.connect(db)) as conn:
            self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0], 3)
            self.assertIsNotNone(
                conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='writer_attempts'").fetchone()
            )
            self.assertIsNotNone(
                conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='trigger' AND name='writer_fence_before_run_insert'"
                ).fetchone()
            )
        self.assertEqual(self.run_json('status', 'v2-scoped')['current_stage'], 'implement')

    def test_direct_dispatcher_unscoped_insert_blocked_by_writer_fence_trigger(self) -> None:
        a, _ = self.linked_pair()
        repo_key = str((self.repo_dir / '.git').resolve())
        wt_a_admin = str((self.repo_dir / '.git' / 'worktrees' / 'task-a').resolve())
        seed = self.run_json('start', a, '--issue', 'repo-1')
        self.run_json('cancel', seed['run_id'], 'admit')
        db = self.xdg_state / 'pi-team-run' / 'state.db'

        insert_sql = (
            "INSERT INTO runs("
            "run_id, repo_key, issue, worktree, status, current_stage, wait_generation, "
            "commit_only, no_ci, with_deploy, with_honcho, with_wiki, created_at, updated_at"
            ") VALUES (?, ?, NULL, NULL, ?, 'admit', 0, 0, 0, 0, 0, 0, 'now', 'now')"
        )
        with closing(sqlite3.connect(db)) as conn, conn:
            conn.execute('PRAGMA foreign_keys = ON')
            conn.execute(
                "INSERT INTO writer_attempts(attempt_id, repo_key, worktree, issue, bound, run_id, status, created_at) "
                "VALUES ('wa-unbound', ?, ?, 'repo-1', 0, NULL, 'open', 'now')",
                (repo_key, wt_a_admin),
            )
            for st in ('active', 'waiting'):
                with self.assertRaisesRegex(sqlite3.IntegrityError, 'writer fence active for repository'):
                    conn.execute(insert_sql, (f'disp-unbound-{st}', repo_key, st))
            conn.execute(
                "UPDATE writer_attempts SET status = 'closed', exit_code = 0, closed_at = 'now' "
                "WHERE attempt_id = 'wa-unbound'"
            )

        scoped = self.run_json('start', a, '--issue', 'repo-1')['run_id']
        with closing(sqlite3.connect(db)) as conn, conn:
            conn.execute('PRAGMA foreign_keys = ON')
            conn.execute(
                "INSERT INTO writer_attempts(attempt_id, repo_key, worktree, issue, bound, run_id, status, created_at) "
                "VALUES ('wa-bound', ?, ?, 'repo-1', 1, ?, 'open', 'now')",
                (repo_key, wt_a_admin, scoped),
            )
            with self.assertRaisesRegex(sqlite3.IntegrityError, 'writer fence active for repository'):
                conn.execute(insert_sql, ('disp-bound-active', repo_key, 'active'))
            conn.execute(
                "UPDATE writer_attempts SET status = 'closed', exit_code = 0, closed_at = 'now' "
                "WHERE attempt_id = 'wa-bound'"
            )

        self.run_json('cancel', scoped, 'admit')
        with closing(sqlite3.connect(db)) as conn, conn:
            conn.execute(insert_sql, ('disp-clear', repo_key, 'active'))
        self.assertEqual(self.run_json('status', 'disp-clear')['status'], 'active')

    def test_writer_exec_rejects_state_ledger_inside_writable_worktree(self) -> None:
        if not os.access('/usr/bin/bwrap', os.X_OK):
            self.skipTest('/usr/bin/bwrap is required')
        a, _ = self.linked_pair()
        marker = Path(a) / 'payload-ran'
        bwrap_argv = [
            '/usr/bin/bwrap', '--unshare-pid', '--die-with-parent', '--ro-bind', '/', '/',
            '--bind', a, a, '--dev', '/dev', '--proc', '/proc', '--', '/bin/sh', '-c', f'touch {marker}',
        ]

        evil_xdg = Path(a) / 'evil-xdg'
        proc_dir = subprocess.run(
            [sys.executable, str(BIN_PATH), 'writer-exec', '--cwd', a, '--issue', 'repo-1', '--', *bwrap_argv],
            env={**self.env, 'XDG_STATE_HOME': str(evil_xdg)},
            text=True, capture_output=True, check=False,
        )
        self.assertNotEqual(proc_dir.returncode, 0)
        self.assertIn('writable worktree', proc_dir.stderr.lower())
        self.assertFalse(evil_xdg.exists())
        self.assertFalse(marker.exists())

        state_dir = self.xdg_state / 'pi-team-run'
        state_dir.mkdir(parents=True, exist_ok=True)
        evil_db = Path(a) / 'linked-state.db'
        (state_dir / 'state.db').symlink_to(evil_db)
        proc_db_link = self.run_cli('writer-exec', '--cwd', a, '--issue', 'repo-1', '--', *bwrap_argv)
        self.assertNotEqual(proc_db_link.returncode, 0)
        self.assertIn('writable worktree', proc_db_link.stderr.lower())
        self.assertFalse(evil_db.exists())
        self.assertFalse(marker.exists())

        (state_dir / 'state.db').unlink()
        state_dir.rmdir()
        evil_state_dir = Path(a) / 'linked-state-dir'
        state_dir.symlink_to(evil_state_dir)
        proc_dir_link = self.run_cli('writer-exec', '--cwd', a, '--issue', 'repo-1', '--', *bwrap_argv)
        self.assertNotEqual(proc_dir_link.returncode, 0)
        self.assertIn('writable worktree', proc_dir_link.stderr.lower())
        self.assertFalse(evil_state_dir.exists())
        self.assertFalse(marker.exists())
        state_dir.unlink()

        outside_target = Path(self.tmp.name) / 'outward-target'
        outside_target.mkdir(parents=True, exist_ok=True)
        outward_xdg = Path(a) / 'outward-xdg'
        outward_xdg.symlink_to(outside_target)
        proc_outward = subprocess.run(
            [sys.executable, str(BIN_PATH), 'writer-exec', '--cwd', a, '--issue', 'repo-1', '--', *bwrap_argv],
            env={**self.env, 'XDG_STATE_HOME': str(outward_xdg)},
            text=True, capture_output=True, check=False,
        )
        self.assertNotEqual(proc_outward.returncode, 0)
        self.assertIn('writable worktree', proc_outward.stderr.lower())
        self.assertFalse((outside_target / 'pi-team-run').exists())
        self.assertFalse(marker.exists())

        wt_sub = Path(a) / 'wt-sub'
        wt_sub.mkdir()
        outside_dotdot = Path(self.tmp.name) / 'outside-dotdot'
        proc_dotdot = subprocess.run(
            [sys.executable, str(BIN_PATH), 'writer-exec', '--cwd', a, '--issue', 'repo-1', '--', *bwrap_argv],
            env={**self.env, 'XDG_STATE_HOME': f'{wt_sub}/../{outside_dotdot.name}'},
            text=True, capture_output=True, check=False,
        )
        self.assertNotEqual(proc_dotdot.returncode, 0)
        self.assertIn('writable worktree', proc_dotdot.stderr.lower())
        self.assertFalse(outside_dotdot.exists())
        self.assertFalse(marker.exists())

        nested_outside = Path(self.tmp.name) / 'nested-outside'
        nested_outside.mkdir()
        wt_hop = Path(a) / 'wt-hop'
        wt_hop.symlink_to(nested_outside)
        state_dir.symlink_to(wt_hop)
        proc_nested = self.run_cli('writer-exec', '--cwd', a, '--issue', 'repo-1', '--', *bwrap_argv)
        self.assertNotEqual(proc_nested.returncode, 0)
        self.assertIn('writable worktree', proc_nested.stderr.lower())
        self.assertFalse((nested_outside / 'state.db').exists())
        self.assertFalse(marker.exists())
        state_dir.unlink()

        outside_sub = self.xdg_state / 'direct-sub'
        outside_sub.mkdir(parents=True, exist_ok=True)
        if subprocess.run(['/usr/bin/bwrap', '--unshare-pid', '--die-with-parent', '--ro-bind', '/', '/',
                           '--bind', a, a, '--dev', '/dev', '--proc', '/proc', '--', 'true'],
                          capture_output=True, check=False).returncode == 0:
            proc_clean = subprocess.run(
                [sys.executable, str(BIN_PATH), 'writer-exec', '--cwd', a, '--issue', 'repo-1', '--', *bwrap_argv],
                env={**self.env, 'XDG_STATE_HOME': f'{outside_sub}/..'},
                text=True, capture_output=True, check=False,
            )
            self.assertEqual(proc_clean.returncode, 0, msg=proc_clean.stderr)
            self.assertTrue(marker.exists())

    def test_writer_exec_rejects_matching_waiting_run(self) -> None:
        if not os.access('/usr/bin/bwrap', os.X_OK):
            self.skipTest('/usr/bin/bwrap is required')
        a, _ = self.linked_pair()
        run_id = self.run_json('start', a, '--issue', 'repo-1')['run_id']
        self.run_json('wait', run_id, 'admit', '--target', 'user', '--reason', 'hold')
        self.assertEqual(self.run_json('status', run_id)['status'], 'waiting')

        marker = Path(a) / 'payload-ran'
        bwrap_argv = [
            'bwrap', '--unshare-pid', '--die-with-parent', '--ro-bind', '/', '/',
            '--bind', a, a, '--dev', '/dev', '--proc', '/proc', '--', '/bin/sh', '-c', f'touch {marker}',
        ]
        proc = self.run_cli('writer-exec', '--cwd', a, '--issue', 'repo-1', '--', *bwrap_argv)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn('waiting', proc.stderr.lower())
        self.assertFalse(marker.exists())
        db = self.xdg_state / 'pi-team-run' / 'state.db'
        with closing(sqlite3.connect(f'{db.resolve().as_uri()}?mode=ro', uri=True)) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM writer_attempts').fetchone()[0], 0)

    def test_missing_legacy_linked_path_refuses_start_and_writer_exec(self) -> None:
        a, b = self.linked_pair()
        db = self.xdg_state / 'pi-team-run' / 'state.db'
        db.parent.mkdir(parents=True)
        with closing(sqlite3.connect(db)) as conn, conn:
            for stmt in runpy.run_path(str(BIN_PATH))['V1_SCHEMA']:
                conn.execute(stmt)
            conn.execute('PRAGMA user_version = 1')
            conn.execute(
                "INSERT INTO runs(run_id,repo_key,status,current_stage,created_at,updated_at) "
                "VALUES ('legacy-missing', ?, 'active', 'implement', 'now', 'now')",
                (a,),
            )

        subprocess.run(['git', '-C', str(self.repo_dir), 'worktree', 'remove', a], check=True, capture_output=True)
        self.assertFalse(Path(a).exists())

        scoped_start = self.run_cli('start', b, '--issue', 'repo-1')
        self.assertNotEqual(scoped_start.returncode, 0)
        self.assertIn('does not exist', scoped_start.stderr.lower())

        unscoped_start = self.run_cli('start', str(self.repo_dir))
        self.assertNotEqual(unscoped_start.returncode, 0)
        self.assertIn('does not exist', unscoped_start.stderr.lower())

        if not os.access('/usr/bin/bwrap', os.X_OK):
            self.skipTest('/usr/bin/bwrap is required')
        marker = Path(b) / 'payload-ran'
        bwrap_argv = [
            'bwrap', '--unshare-pid', '--die-with-parent', '--ro-bind', '/', '/',
            '--bind', b, b, '--dev', '/dev', '--proc', '/proc', '--', '/bin/sh', '-c', f'touch {marker}',
        ]
        writer = self.run_cli('writer-exec', '--cwd', b, '--issue', 'repo-1', '--', *bwrap_argv)
        self.assertNotEqual(writer.returncode, 0)
        self.assertIn('does not exist', writer.stderr.lower())
        self.assertFalse(marker.exists())

        with closing(sqlite3.connect(f'{db.resolve().as_uri()}?mode=ro', uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute('SELECT run_id, repo_key, status, current_stage FROM runs').fetchall()
            self.assertEqual([dict(row) for row in rows], [{
                'run_id': 'legacy-missing',
                'repo_key': a,
                'status': 'active',
                'current_stage': 'implement',
            }])
            has_attempts = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='writer_attempts'"
            ).fetchone()
            if has_attempts is not None:
                self.assertEqual(conn.execute('SELECT count(*) FROM writer_attempts').fetchone()[0], 0)

    def test_writer_exec_bootstrap_reports_missing_and_unexecutable_without_traceback(self) -> None:
        if not os.access('/usr/bin/bwrap', os.X_OK):
            self.skipTest('/usr/bin/bwrap is required')
        a, _ = self.linked_pair()
        missing = Path(self.tmp.name) / 'missing-writer'
        nonexec = Path(self.tmp.name) / 'nonexec-writer'
        nonexec.write_text('#!/bin/sh\nexit 0\n', encoding='utf-8')
        nonexec.chmod(0o644)

        base_bwrap = [
            'bwrap', '--unshare-pid', '--die-with-parent', '--ro-bind', '/', '/',
            '--bind', a, a, '--dev', '/dev', '--proc', '/proc', '--',
        ]
        miss_proc = self.run_cli(
            'writer-exec', '--cwd', a, '--issue', 'repo-1', '--',
            *base_bwrap, str(missing), '--secret-arg', 'secret-arg-do-not-leak',
        )
        self.assertEqual(miss_proc.returncode, 127)
        self.assertEqual(miss_proc.stderr.strip(), f'bwrap: execvp {missing}: No such file or directory')
        self.assertNotIn('Traceback', miss_proc.stderr)
        self.assertNotIn('FileNotFoundError', miss_proc.stderr)
        self.assertNotIn('secret-arg-do-not-leak', miss_proc.stderr)

        perm_proc = self.run_cli(
            'writer-exec', '--cwd', a, '--issue', 'repo-1', '--',
            *base_bwrap, str(nonexec), '--secret-arg', 'secret-arg-do-not-leak',
        )
        self.assertEqual(perm_proc.returncode, 126)
        self.assertEqual(perm_proc.stderr.strip(), f'bwrap: execvp {nonexec}: Permission denied')
        self.assertNotIn('Traceback', perm_proc.stderr)
        self.assertNotIn('PermissionError', perm_proc.stderr)
        self.assertNotIn('secret-arg-do-not-leak', perm_proc.stderr)

        db = self.xdg_state / 'pi-team-run' / 'state.db'
        with closing(sqlite3.connect(f'{db.resolve().as_uri()}?mode=ro', uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            attempts = [
                (row['status'], row['exit_code'])
                for row in conn.execute('SELECT status, exit_code FROM writer_attempts ORDER BY rowid').fetchall()
            ]
        self.assertEqual(attempts, [('closed', 127), ('closed', 126)])

    def test_writer_exec_pins_trusted_binaries_and_ignores_python_site_hooks(self) -> None:
        for exe in ('/usr/bin/bwrap', '/usr/bin/python3', '/usr/bin/git'):
            if not os.access(exe, os.X_OK):
                self.skipTest(f'{exe} is required')
        a, _ = self.linked_pair()
        if subprocess.run(['/usr/bin/bwrap', '--unshare-pid', '--die-with-parent', '--ro-bind', '/', '/',
                           '--bind', a, a, '--dev', '/dev', '--proc', '/proc', '--', 'true'],
                          capture_output=True, check=False).returncode != 0:
            self.skipTest('working /usr/bin/bwrap PID namespace is required')

        shadow_dir = Path(a) / 'shadow-bin'
        shadow_dir.mkdir()
        shadow_marker = Path(a) / 'shadow-bin-ran'
        for name in ('bwrap', 'git', 'python3'):
            exe = shadow_dir / name
            exe.write_text(f'#!/bin/sh\ntouch {shadow_marker}\nexit 99\n', encoding='utf-8')
            exe.chmod(0o755)

        hook_dir = Path(a) / 'py-hooks'
        hook_dir.mkdir()
        hook_marker = Path(a) / 'site-hook-ran'
        (hook_dir / 'sitecustomize.py').write_text(
            f'from pathlib import Path\nPath({str(hook_marker)!r}).write_text("pwned")\n',
            encoding='utf-8',
        )

        worker_dir = Path(self.tmp.name) / 'worker-bin'
        worker_dir.mkdir()
        worker_marker = Path(a) / 'worker-ran'
        fake_worker = worker_dir / 'fake-worker'
        fake_worker.write_text(f'#!/bin/sh\ntouch {worker_marker}\n', encoding='utf-8')
        fake_worker.chmod(0o755)

        poison_env = {
            **self.env,
            'PATH': f'{shadow_dir}:{worker_dir}:/usr/bin:/bin',
            'PYTHONPATH': str(hook_dir),
            'PYTHONUSERBASE': str(hook_dir),
        }
        proc = subprocess.run(
            [
                '/usr/bin/python3', '-I', '-S', str(BIN_PATH),
                'writer-exec', '--cwd', a, '--issue', 'repo-1', '--',
                '/usr/bin/bwrap', '--unshare-pid', '--die-with-parent', '--ro-bind', '/', '/',
                '--bind', a, a, '--dev', '/dev', '--proc', '/proc', '--',
                'fake-worker',
            ],
            cwd=a,
            env=poison_env,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertTrue(worker_marker.exists())
        self.assertFalse(shadow_marker.exists())
        self.assertFalse(hook_marker.exists())

    def test_short_sqlite_transaction_resolves_unfamiliar_keys_outside_lock_and_retries_new_keys(self) -> None:
        a, b = self.linked_pair()
        other = Path(self.tmp.name) / 'other-repo'
        other.mkdir()
        other_run = self.run_json('start', str(other))['run_id']
        db = self.xdg_state / 'pi-team-run' / 'state.db'

        script = runpy.run_path(str(BIN_PATH))
        cmd_start = script['cmd_start']
        real_canon = script['canonicalize_repo']
        parser = script['build_parser']()

        resolving_other = threading.Event()
        allow_finish = threading.Event()
        tx_probe_ok: list[bool] = []

        def delayed_canon(repo: str, *, git_bin: str = 'git') -> str:
            if repo == str(other):
                with closing(sqlite3.connect(str(db), timeout=0.05, isolation_level=None)) as probe:
                    probe.execute('BEGIN IMMEDIATE')
                    probe.execute('ROLLBACK')
                tx_probe_ok.append(True)
                resolving_other.set()
                self.assertTrue(allow_finish.wait(timeout=5.0))
            return real_canon(repo, git_bin=git_bin)

        result_holder: list[tuple[int, dict] | BaseException] = []

        def run_start() -> None:
            try:
                with patch.dict(cmd_start.__globals__, {'canonicalize_repo': delayed_canon}):
                    result_holder.append(cmd_start(parser.parse_args(['start', b, '--issue', 'repo-1']), db))
            except BaseException as exc:
                result_holder.append(exc)

        t = threading.Thread(target=run_start)
        t.start()
        self.assertTrue(resolving_other.wait(timeout=5.0))
        ckpt = self.run_json('checkpoint', other_run, 'admit', '--evidence', 'ev:unblocked')
        self.assertEqual(ckpt['current_stage'], 'implement')
        allow_finish.set()
        t.join(timeout=5.0)
        self.assertFalse(t.is_alive())
        self.assertEqual(tx_probe_ok, [True])
        self.assertIsInstance(result_holder[0], tuple)
        code, payload = result_holder[0]
        self.assertEqual(code, 0)
        self.assertEqual(payload['issue'], 'repo-1')

        # Now verify new-key race: while resolving an unfamiliar key outside tx, another run inserts a conflicting key.
        third = Path(self.tmp.name) / 'third-repo'
        third.mkdir()
        self.run_json('start', str(third))
        self.run_json('cancel', payload['run_id'], 'admit')

        resolving_third = threading.Event()
        allow_race_finish = threading.Event()
        race_holder: list[BaseException | tuple[int, dict]] = []

        def race_canon(repo: str, *, git_bin: str = 'git') -> str:
            if repo == str(third):
                resolving_third.set()
                self.assertTrue(allow_race_finish.wait(timeout=5.0))
            return real_canon(repo, git_bin=git_bin)

        def run_raced_start() -> None:
            try:
                with patch.dict(cmd_start.__globals__, {'canonicalize_repo': race_canon}):
                    race_holder.append(cmd_start(parser.parse_args(['start', b, '--issue', 'repo-2']), db))
            except BaseException as exc:
                race_holder.append(exc)

        t2 = threading.Thread(target=run_raced_start)
        t2.start()
        self.assertTrue(resolving_third.wait(timeout=5.0))
        self.run_json('start', a)
        allow_race_finish.set()
        t2.join(timeout=5.0)
        self.assertFalse(t2.is_alive())
        self.assertIsInstance(race_holder[0], script['CliError'])
        self.assertIn('active run already exists', str(race_holder[0]).lower())

    def test_writer_exec_unreadable_pidfd_after_wait_and_identity_failure_keep_fence_open(self) -> None:
        if not os.access('/usr/bin/bwrap', os.X_OK) or not hasattr(os, 'pidfd_open'):
            self.skipTest('/usr/bin/bwrap and os.pidfd_open are required')
        a, b = self.linked_pair()
        if subprocess.run(['/usr/bin/bwrap', '--unshare-pid', '--die-with-parent', '--ro-bind', '/', '/',
                           '--bind', a, a, '--dev', '/dev', '--proc', '/proc', '--', 'true'],
                          capture_output=True, check=False).returncode != 0:
            self.skipTest('working /usr/bin/bwrap PID namespace is required')

        script = runpy.run_path(str(BIN_PATH))
        cmd_writer_exec = script['cmd_writer_exec']
        parser = script['build_parser']()
        db = self.xdg_state / 'pi-team-run' / 'state.db'

        # Case A: negative identity verification proves no GO, no payload execution, and fence remains open.
        blocked_marker = Path(a) / 'identity-failed-ran'
        real_read_info = script['_read_bwrap_info']

        def tampered_read_info(info_r: int, timeout: float = script['INFO_READ_TIMEOUT_SEC']) -> dict:
            info = real_read_info(info_r, timeout)
            info['child-pid'] = os.getpid()
            return info

        args_ident = parser.parse_args([
            'writer-exec', '--cwd', a, '--issue', 'repo-ident', '--',
            '/usr/bin/bwrap', '--unshare-pid', '--die-with-parent', '--ro-bind', '/', '/',
            '--bind', a, a, '--dev', '/dev', '--proc', '/proc', '--',
            '/bin/sh', '-c', f'touch {blocked_marker}',
        ])
        with patch.dict(cmd_writer_exec.__globals__, {'_read_bwrap_info': tampered_read_info}):
            with self.assertRaisesRegex(script['CliError'], 'not a direct child|namespace'):
                cmd_writer_exec(args_ident, db)
        self.assertFalse(blocked_marker.exists())
        with closing(sqlite3.connect(f'{db.resolve().as_uri()}?mode=ro', uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            rows = [dict(r) for r in conn.execute('SELECT issue, status, exit_code FROM writer_attempts').fetchall()]
        self.assertEqual(rows, [{'issue': 'repo-ident', 'status': 'open', 'exit_code': None}])
        denied_ident = self.run_cli('start', b)
        self.assertNotEqual(denied_ident.returncode, 0)
        self.assertIn('writer fence', denied_ident.stderr.lower())

        # Clear the test-only fence row in disposable temp ledger before Case B.
        with closing(sqlite3.connect(str(db))) as conn, conn:
            conn.execute("UPDATE writer_attempts SET status = 'closed', exit_code = 1, closed_at = 'now'")

        # Case B: real bwrap lifecycle + real identity check + real worker exit, but unreadable witness after proc.wait().
        ran_marker = Path(a) / 'unreadable-witness-worker-ran'
        real_pin = script['_pin_verified_namespace_init']
        dummy_r, dummy_w = os.pipe2(os.O_CLOEXEC)
        try:
            def pin_with_unready_witness(info: dict, launcher_pid: int) -> int:
                real_pidfd = real_pin(info, launcher_pid)
                os.close(real_pidfd)
                return os.dup(dummy_r)

            args_witness = parser.parse_args([
                'writer-exec', '--cwd', a, '--issue', 'repo-witness', '--',
                '/usr/bin/bwrap', '--unshare-pid', '--die-with-parent', '--ro-bind', '/', '/',
                '--bind', a, a, '--dev', '/dev', '--proc', '/proc', '--',
                '/bin/sh', '-c', f'touch {ran_marker}',
            ])
            with patch.dict(cmd_writer_exec.__globals__, {
                '_pin_verified_namespace_init': pin_with_unready_witness,
                'PIDFD_WAIT_TIMEOUT_SEC': 0.05,
            }):
                with self.assertRaisesRegex(script['CliError'], 'pidfd not readable after launcher wait'):
                    cmd_writer_exec(args_witness, db)
        finally:
            os.close(dummy_r)
            os.close(dummy_w)

        self.assertTrue(ran_marker.exists())
        with closing(sqlite3.connect(f'{db.resolve().as_uri()}?mode=ro', uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            open_rows = [
                dict(r)
                for r in conn.execute("SELECT issue, status, exit_code FROM writer_attempts WHERE status = 'open'").fetchall()
            ]
        self.assertEqual(open_rows, [{'issue': 'repo-witness', 'status': 'open', 'exit_code': None}])
        self.assertNotIn('writer_fence_open', self.run_json('preflight', a))
        denied_witness = self.run_cli('start', b)
        self.assertNotEqual(denied_witness.returncode, 0)
        self.assertIn('writer fence', denied_witness.stderr.lower())

    def test_start_and_writer_exec_pin_trusted_git_and_ignore_git_env_overrides(self) -> None:
        if not os.access('/usr/bin/git', os.X_OK):
            self.skipTest('/usr/bin/git is required')
        a, b = self.linked_pair()
        repo_key = str((self.repo_dir / '.git').resolve())
        wt_a_admin = str((self.repo_dir / '.git' / 'worktrees' / 'task-a').resolve())

        unrelated = Path(self.tmp.name) / 'unrelated-repo'
        unrelated.mkdir()
        git_env = {
            'PATH': '/usr/bin:/bin',
            'HOME': '/nonexistent',
            'GIT_CONFIG_NOSYSTEM': '1',
            'GIT_CONFIG_GLOBAL': '/dev/null',
            'GIT_TERMINAL_PROMPT': '0',
        }
        subprocess.run(['/usr/bin/git', '-C', str(unrelated), 'init', '-b', 'main'], env=git_env, check=True, capture_output=True)
        subprocess.run(['/usr/bin/git', '-C', str(unrelated), 'config', 'user.name', 'Test'], env=git_env, check=True, capture_output=True)
        subprocess.run(['/usr/bin/git', '-C', str(unrelated), 'config', 'user.email', 'test@example.invalid'], env=git_env, check=True, capture_output=True)
        subprocess.run(['/usr/bin/git', '-C', str(unrelated), 'commit', '--allow-empty', '-m', 'base'], env=git_env, check=True, capture_output=True)

        seed = self.run_json('start', a, '--issue', 'repo-seed')
        self.run_json('cancel', seed['run_id'], 'admit')
        db = self.xdg_state / 'pi-team-run' / 'state.db'
        with closing(sqlite3.connect(str(db))) as conn, conn:
            conn.execute(
                "INSERT INTO writer_attempts(attempt_id, repo_key, worktree, issue, bound, run_id, status, created_at) "
                "VALUES ('wa-open-git-pin', ?, ?, 'repo-1', 0, NULL, 'open', 'now')",
                (repo_key, wt_a_admin),
            )

        shadow_dir = Path(self.tmp.name) / 'shadow-git-bin'
        shadow_dir.mkdir()
        shadow_marker = Path(self.tmp.name) / 'shadow-git-ran'
        fake_git = shadow_dir / 'git'
        fake_git.write_text(
            f'#!/bin/sh\ntouch {shadow_marker}\nprintf "%s\\n" "{unrelated}/.git"\n',
            encoding='utf-8',
        )
        fake_git.chmod(0o755)

        poison_env = {
            **self.env,
            'PATH': f'{shadow_dir}:{self.env.get("PATH", "/usr/bin:/bin")}',
            'GIT_DIR': str(unrelated / '.git'),
            'GIT_COMMON_DIR': str(unrelated / '.git'),
            'GIT_WORK_TREE': str(unrelated),
            'GIT_INDEX_FILE': str(unrelated / '.git' / 'index'),
            'GIT_CEILING_DIRECTORIES': str(Path(self.tmp.name)),
            'GIT_DISCOVERY_ACROSS_FILESYSTEM': '0',
            'GIT_CONFIG_PARAMETERS': "'core.bare=true'",
        }

        for start_args in (['start', b], ['start', b, '--issue', 'repo-2']):
            denied = subprocess.run(
                [sys.executable, str(BIN_PATH), *start_args],
                env=poison_env, text=True, capture_output=True, check=False,
            )
            self.assertNotEqual(denied.returncode, 0, msg=denied.stdout)
            self.assertIn('writer fence', denied.stderr.lower())
        self.assertFalse(shadow_marker.exists())

        self.assertNotEqual(self.run_cli('writer-fence', b).returncode, 0)

        if os.access('/usr/bin/bwrap', os.X_OK):
            blocked_marker = Path(b) / 'poison-wexec-ran'
            wexec_denied = subprocess.run(
                [
                    sys.executable, str(BIN_PATH), 'writer-exec', '--cwd', b, '--issue', 'repo-2', '--',
                    '/usr/bin/bwrap', '--unshare-pid', '--die-with-parent', '--ro-bind', '/', '/',
                    '--bind', b, b, '--dev', '/dev', '--proc', '/proc', '--',
                    '/bin/sh', '-c', f'touch {blocked_marker}',
                ],
                env=poison_env, text=True, capture_output=True, check=False,
            )
            self.assertNotEqual(wexec_denied.returncode, 0, msg=wexec_denied.stdout)
            self.assertIn('writer fence', wexec_denied.stderr.lower())
            self.assertFalse(blocked_marker.exists())
            self.assertFalse(shadow_marker.exists())

        script = runpy.run_path(str(BIN_PATH))
        cmd_start = script['cmd_start']
        parser = script['build_parser']()

        seen_cmds: list[tuple[list[str], dict[str, str]]] = []
        real_run = subprocess.run

        def recording_run(cmd, *r_args, **r_kwargs):
            seen_cmds.append((list(cmd), dict(r_kwargs.get('env') or {})))
            return real_run(cmd, *r_args, **r_kwargs)

        with patch.dict(os.environ, {
            'GIT_DIR': str(unrelated / '.git'),
            'GIT_COMMON_DIR': str(unrelated / '.git'),
            'GIT_WORK_TREE': str(unrelated),
            'GIT_CONFIG_PARAMETERS': "'core.bare=true'",
        }):
            with patch.dict(cmd_start.__globals__, {'subprocess': type('Sub', (), {
                'TimeoutExpired': subprocess.TimeoutExpired,
                'run': staticmethod(recording_run),
            })()}):
                with self.assertRaisesRegex(script['CliError'], 'writer fence'):
                    cmd_start(parser.parse_args(['start', b, '--issue', 'repo-2']), db)
        self.assertEqual(len(seen_cmds), 2)
        for cmd, env_used in seen_cmds:
            self.assertEqual(cmd[0], '/usr/bin/git')
            self.assertIn('rev-parse', cmd)
            self.assertNotIn('status', cmd)
            self.assertNotIn('GIT_DIR', env_used)
            self.assertNotIn('GIT_COMMON_DIR', env_used)
            self.assertNotIn('GIT_WORK_TREE', env_used)
            self.assertEqual(env_used.get('GIT_CONFIG_NOSYSTEM'), '1')
            self.assertEqual(env_used.get('GIT_CONFIG_GLOBAL'), '/dev/null')
            self.assertEqual(env_used.get('GIT_TERMINAL_PROMPT'), '0')

        for bad_out in (
            subprocess.CompletedProcess(['/usr/bin/git'], 128, stdout='', stderr='fatal'),
            subprocess.CompletedProcess(['/usr/bin/git'], 0, stdout=f'{b}\n{wt_a_admin}\n', stderr=''),
            subprocess.CompletedProcess(['/usr/bin/git'], 0, stdout='relative\n', stderr=''),
            subprocess.CompletedProcess(['/usr/bin/git'], 0, stdout=f'{repo_key}\0\n', stderr=''),
        ):
            with patch.dict(cmd_start.__globals__, {'subprocess': type('Sub', (), {
                'TimeoutExpired': subprocess.TimeoutExpired,
                'run': staticmethod(lambda *a, _res=bad_out, **kw: _res),
            })()}):
                with self.assertRaises(script['CliError']):
                    cmd_start(parser.parse_args(['start', b]), db)

    def test_writer_exec_rejects_ledger_hardlink_nonregular_and_late_inode_swap(self) -> None:
        if not os.access('/usr/bin/bwrap', os.X_OK) or not hasattr(os, 'pidfd_open'):
            self.skipTest('/usr/bin/bwrap and os.pidfd_open are required')
        a, _ = self.linked_pair()
        if subprocess.run(['/usr/bin/bwrap', '--unshare-pid', '--die-with-parent', '--ro-bind', '/', '/',
                           '--bind', a, a, '--dev', '/dev', '--proc', '/proc', '--', 'true'],
                          capture_output=True, check=False).returncode != 0:
            self.skipTest('working /usr/bin/bwrap PID namespace is required')

        seed = self.run_json('start', a, '--issue', 'repo-seed')
        self.run_json('cancel', seed['run_id'], 'admit')
        db = self.xdg_state / 'pi-team-run' / 'state.db'
        before_bytes = db.read_bytes()
        marker = Path(a) / 'hardlink-payload-ran'
        bwrap_argv = [
            '/usr/bin/bwrap', '--unshare-pid', '--die-with-parent', '--ro-bind', '/', '/',
            '--bind', a, a, '--dev', '/dev', '--proc', '/proc', '--', '/bin/sh', '-c', f'touch {marker}',
        ]

        wt_hardlink = Path(a) / 'state-hardlink.db'
        os.link(db, wt_hardlink)
        self.assertEqual(db.stat().st_nlink, 2)
        proc = self.run_cli('writer-exec', '--cwd', a, '--issue', 'repo-hardlink', '--', *bwrap_argv)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn('hardlink', proc.stderr.lower())
        self.assertFalse(marker.exists())
        self.assertEqual(db.read_bytes(), before_bytes)
        wt_hardlink.unlink()
        with closing(sqlite3.connect(f'{db.resolve().as_uri()}?mode=ro', uri=True)) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM writer_attempts').fetchone()[0], 0)
            self.assertEqual(conn.execute('SELECT count(*) FROM runs').fetchone()[0], 1)

        fifo_xdg = Path(self.tmp.name) / 'fifo-xdg'
        fifo_dir = fifo_xdg / 'pi-team-run'
        fifo_dir.mkdir(parents=True)
        fifo_db = fifo_dir / 'state.db'
        os.mkfifo(fifo_db)
        fifo_proc = subprocess.run(
            [sys.executable, str(BIN_PATH), 'writer-exec', '--cwd', a, '--issue', 'repo-fifo', '--', *bwrap_argv],
            env={**self.env, 'XDG_STATE_HOME': str(fifo_xdg)},
            text=True, capture_output=True, check=False,
        )
        self.assertNotEqual(fifo_proc.returncode, 0)
        self.assertIn('regular file', fifo_proc.stderr.lower())
        self.assertFalse(marker.exists())

        script = runpy.run_path(str(BIN_PATH))
        cmd_writer_exec = script['cmd_writer_exec']
        parser = script['build_parser']()
        real_validate = script['_validate_writer_state_path']
        calls = 0

        def inject_late_hardlink(path_arg: Path, cwd_arg: Path, *, require_exists: bool = False):
            nonlocal calls
            calls += 1
            if calls == 2 and not wt_hardlink.exists():
                os.link(db, wt_hardlink)
            return real_validate(path_arg, cwd_arg, require_exists=require_exists)

        args_late = parser.parse_args(['writer-exec', '--cwd', a, '--issue', 'repo-late', '--', *bwrap_argv])
        with patch.dict(cmd_writer_exec.__globals__, {'_validate_writer_state_path': inject_late_hardlink}):
            with self.assertRaisesRegex(script['CliError'], 'hardlink'):
                cmd_writer_exec(args_late, db)
        self.assertFalse(marker.exists())
        wt_hardlink.unlink()
        with closing(sqlite3.connect(f'{db.resolve().as_uri()}?mode=ro', uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            rows = [dict(r) for r in conn.execute('SELECT issue, status, exit_code FROM writer_attempts').fetchall()]
        self.assertEqual(rows, [{'issue': 'repo-late', 'status': 'open', 'exit_code': None}])

    def test_writer_exec_high_exit_200_requires_witness_and_only_signal_killed_launcher_bypasses_close(self) -> None:
        if not os.access('/usr/bin/bwrap', os.X_OK) or not hasattr(os, 'pidfd_open'):
            self.skipTest('/usr/bin/bwrap and os.pidfd_open are required')
        a, b = self.linked_pair()
        if subprocess.run(['/usr/bin/bwrap', '--unshare-pid', '--die-with-parent', '--ro-bind', '/', '/',
                           '--bind', a, a, '--dev', '/dev', '--proc', '/proc', '--', 'true'],
                          capture_output=True, check=False).returncode != 0:
            self.skipTest('working /usr/bin/bwrap PID namespace is required')

        marker_200 = Path(a) / 'exit-200-ran'
        proc_200 = self.run_cli(
            'writer-exec', '--cwd', a, '--issue', 'repo-200', '--',
            '/usr/bin/bwrap', '--unshare-pid', '--die-with-parent', '--ro-bind', '/', '/',
            '--bind', a, a, '--dev', '/dev', '--proc', '/proc', '--',
            '/bin/sh', '-c', f'touch {marker_200}; exit 200',
        )
        self.assertEqual(proc_200.returncode, 200, msg=proc_200.stderr)
        self.assertTrue(marker_200.exists())
        db = self.xdg_state / 'pi-team-run' / 'state.db'
        with closing(sqlite3.connect(f'{db.resolve().as_uri()}?mode=ro', uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            rows = [dict(r) for r in conn.execute('SELECT issue, status, exit_code FROM writer_attempts').fetchall()]
        self.assertEqual(rows, [{'issue': 'repo-200', 'status': 'closed', 'exit_code': 200}])
        self.assertNotIn('writer_fence_open', self.run_json('preflight', a))

        script = runpy.run_path(str(BIN_PATH))
        cmd_writer_exec = script['cmd_writer_exec']
        parser = script['build_parser']()
        real_pin = script['_pin_verified_namespace_init']

        marker_unready = Path(a) / 'exit-200-unready-ran'
        dummy_r, dummy_w = os.pipe2(os.O_CLOEXEC)
        try:
            def pin_unready(info: dict, launcher_pid: int) -> int:
                real_pidfd = real_pin(info, launcher_pid)
                os.close(real_pidfd)
                return os.dup(dummy_r)

            args_200 = parser.parse_args([
                'writer-exec', '--cwd', a, '--issue', 'repo-200-unready', '--',
                '/usr/bin/bwrap', '--unshare-pid', '--die-with-parent', '--ro-bind', '/', '/',
                '--bind', a, a, '--dev', '/dev', '--proc', '/proc', '--',
                '/bin/sh', '-c', f'touch {marker_unready}; exit 200',
            ])
            with patch.dict(cmd_writer_exec.__globals__, {
                '_pin_verified_namespace_init': pin_unready,
                'PIDFD_WAIT_TIMEOUT_SEC': 0.05,
            }):
                with self.assertRaisesRegex(script['CliError'], 'pidfd not readable after launcher wait'):
                    cmd_writer_exec(args_200, db)
        finally:
            os.close(dummy_r)
            os.close(dummy_w)

        self.assertTrue(marker_unready.exists())
        with closing(sqlite3.connect(f'{db.resolve().as_uri()}?mode=ro', uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            open_rows = [
                dict(r)
                for r in conn.execute("SELECT issue, status, exit_code FROM writer_attempts WHERE status = 'open'").fetchall()
            ]
        self.assertEqual(open_rows, [{'issue': 'repo-200-unready', 'status': 'open', 'exit_code': None}])

        with closing(sqlite3.connect(str(db))) as conn, conn:
            conn.execute("UPDATE writer_attempts SET status = 'closed', exit_code = 200, closed_at = 'now'")

        marker_sig = Path(a) / 'sigkill-launcher-ready'
        real_popen = subprocess.Popen
        killer_threads: list[threading.Thread] = []

        def popen_and_kill_launcher(*p_args, **p_kwargs):
            proc = real_popen(*p_args, **p_kwargs)

            def kill_when_ready() -> None:
                deadline = time.monotonic() + 5.0
                while time.monotonic() < deadline and not marker_sig.exists():
                    time.sleep(0.005)
                if marker_sig.exists():
                    try:
                        os.kill(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass

            kt = threading.Thread(target=kill_when_ready, daemon=True)
            kt.start()
            killer_threads.append(kt)
            return proc

        args_sig = parser.parse_args([
            'writer-exec', '--cwd', a, '--issue', 'repo-sigkill', '--',
            '/usr/bin/bwrap', '--unshare-pid', '--die-with-parent', '--ro-bind', '/', '/',
            '--bind', a, a, '--dev', '/dev', '--proc', '/proc', '--',
            '/bin/sh', '-c', f'touch {marker_sig}; exec /bin/sleep 0.3',
        ])
        with patch.dict(cmd_writer_exec.__globals__, {'subprocess': type('Sub', (), {
            'Popen': staticmethod(popen_and_kill_launcher),
            'TimeoutExpired': subprocess.TimeoutExpired,
            'SubprocessError': subprocess.SubprocessError,
            'run': staticmethod(subprocess.run),
        })()}):
            rc, _ = cmd_writer_exec(args_sig, db)
        for kt in killer_threads:
            kt.join(timeout=5.0)
        time.sleep(0.35)

        self.assertEqual(rc, 128 + signal.SIGKILL)
        self.assertTrue(marker_sig.exists())
        with closing(sqlite3.connect(f'{db.resolve().as_uri()}?mode=ro', uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            sig_rows = [
                dict(r)
                for r in conn.execute("SELECT issue, status, exit_code FROM writer_attempts WHERE status = 'open'").fetchall()
            ]
        self.assertEqual(sig_rows, [{'issue': 'repo-sigkill', 'status': 'open', 'exit_code': None}])
        self.assertNotEqual(self.run_cli('start', b).returncode, 0)


if __name__ == '__main__':
    unittest.main()
