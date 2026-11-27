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
            self.assertEqual(version, 2)
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


if __name__ == '__main__':
    unittest.main()
