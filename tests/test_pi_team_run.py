#!/usr/bin/env python3
"""Standard-library integration tests for pi-team-run."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta, timezone
import errno
import io
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
            self.assertEqual(version, 4)
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

    def test_exhausted_patch_handoff_survives_restart_without_replay_or_delivery(self):
        wt, _ = self.linked_pair()
        run = self.run_json('start', wt, '--issue', 'repo-1', '--commit-only')['run_id']
        self.run_json('checkpoint', run, 'admit', '--evidence', 'claim')
        from hashlib import sha256
        rejected, corrected, amended = b'rejected diff', b'corrected diff', b'amended diff'
        bad, fixed, final = (sha256(data).hexdigest() for data in (rejected, corrected, amended))
        snapshot = Path(self.tmp.name) / 'snapshot.diff'
        def park(stage, digest, *options):
            return self.run_json('wait', run, stage, '--target', 'coordinator', '--rejected-patch', digest,
                                 '--reason', 'review:causal-attribution', *options)
        def supply(gen, digest, content=None):
            snapshot.write_bytes(content or {bad: rejected, fixed: corrected, final: amended}[digest])
            return self.run_cli('supply-patch', run, '--generation', str(gen), '--candidate', digest,
                                '--snapshot', str(snapshot), '--evidence', 'maintainer:patch')
        def step(stage, digest, gen=None, *options):
            args = ['checkpoint', run, stage, '--evidence', 'checks:verified', '--rev', digest]
            return self.run_cli(*args, *(['--generation', str(gen)] if gen is not None else []), *options)
        gen = park('implement', bad)['wait_generation']
        self.assertEqual(park('implement', bad)['wait_generation'], gen)
        for _ in range(2):
            self.assertEqual(self.run_json('resume', run)['action'], 'await_external_patch')
        self.assertEqual(self.run_json('discover', wt)[0]['action'], 'await_external_patch')
        self.assertEqual([r['reason'] for r in self.watch_notices()], ['external_patch_required'])
        self.assertEqual(self.watch_notices(), [])
        self.assertNotEqual(self.run_cli('wait', run, 'implement', '--target', 'user', '--replace').returncode, 0)
        self.assertNotEqual(step('implement', bad, gen).returncode, 0)
        self.assertNotEqual(supply(gen, bad).returncode, 0)
        self.assertNotEqual(supply(gen, fixed, rejected).returncode, 0)
        self.assertNotEqual(supply(gen + 1, fixed).returncode, 0)
        self.assertEqual(supply(gen, fixed).returncode, 0)
        self.assertEqual(supply(gen, fixed).returncode, 0)
        self.assertNotEqual(supply(gen + 1, final).returncode, 0)
        self.assertEqual(self.run_json('resume', run)['action'], 'verify_external_patch')
        self.assertEqual([r['reason'] for r in self.watch_notices()], ['external_patch_ready'])
        self.assertEqual(self.watch_notices(), [])
        self.assertNotEqual(step('implement', fixed, gen).returncode, 0)
        self.assertNotEqual(step('implement', bad, gen + 1).returncode, 0)
        self.assertEqual(step('implement', fixed, gen + 1).returncode, 0)
        self.assertNotEqual(step('check', bad).returncode, 0)
        self.assertEqual(step('check', fixed).returncode, 0)
        gen2 = park('review', fixed)['wait_generation']
        self.assertNotEqual(supply(gen2, bad).returncode, 0)
        self.assertEqual(supply(gen2, final).returncode, 0)
        self.assertNotEqual(step('review', final, gen2 + 1).returncode, 0)
        self.assertEqual(step('review', final, gen2 + 1, '--checks-evidence', 'checks:amended').returncode, 0)
        snapshot = self.run_json('status', run)
        db = self.xdg_state / 'pi-team-run/state.db'
        with closing(sqlite3.connect(db)) as conn:
            with self.assertRaisesRegex(sqlite3.IntegrityError, 'writer budget not reset'):
                conn.execute("""INSERT INTO writer_attempts(attempt_id,repo_key,worktree,issue,bound,run_id,status,created_at)
                                VALUES (?,?,?,?,1,?,'open','now')""",
                             ('test-replay',snapshot['repo_key'],snapshot['worktree'],'repo-1',run))
            prior = conn.execute("SELECT rejected FROM external_patches JOIN waits ON wait_id=waits.id WHERE run_id=? ORDER BY wait_id", (run,)).fetchall()
            self.assertEqual(prior, [(bad,), (bad,), (fixed,), (fixed,)])
        self.assertTrue(snapshot['commit_only'])
        self.assertEqual(snapshot['current_stage'], 'commit')
        self.assertEqual(snapshot['checkpoints'][-1]['rev'], final)

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
            self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0], 4)
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

    def test_switch_never_signals_on_partial_or_mismatched_identity(self):
        script = runpy.run_path(str(BIN_PATH))
        stop = script['_stop_switch_source']
        with closing(sqlite3.connect(':memory:')) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute('CREATE TABLE writer_switch_witness(attempt_id, actor, host, identities)')
            conn.execute("INSERT INTO writer_switch_witness VALUES ('old','owner','{}','[]')")
            attempt = {'attempt_id': 'old', 'status': 'open'}
            with patch.dict(stop.__globals__, {'_verify_pinned_ledger_under_tx': lambda *_: None,
                                               '_pidfs_inode': lambda _: 7}), \
                    patch.object(signal, 'pidfd_send_signal') as send:
                for ids, host, error in [([], {}, 'incomplete'), ([[2,3],[2,4]], {}, 'incomplete'),
                                         ([], {'boot':'other'}, 'host/ledger evidence mismatch'),
                                         ([[os.getpid(), 2],[os.getppid(), 3]], {}, 'identity mismatch')]:
                    conn.execute('UPDATE writer_switch_witness SET identities=?',(json.dumps(ids),))
                    with self.assertRaisesRegex(script['CliError'], error):
                        stop(conn, attempt, 'owner', host, Path('/unused'))
                send.assert_not_called()

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

    def _recovery_host_patches(
        self,
        cmd_fn,
        db_path: Path,
        *,
        boot_id: str,
        machine_id: str = '1' * 32,
        fs_type: str = 'ext4',
        fsid: int = 0x9123456789ABCDEF,
        pid_ns_ino: int = 0xEFFFFFFC,
        nstgid_line: str = 'NStgid:\t1000\n',
        proc_fs: str = 'proc',
        proc_root: str = '/',
        proc_dev: str | None = None,
        extra_mounts: str = '',
        proc_magic: int | None = None,
        ledger_magic: int | None = None,
        ledger_dev_maj_min: str | None = None,
    ):
        probe_path = db_path if db_path.exists() else (db_path.parent if db_path.parent.exists() else Path(self.tmp.name))
        st = os.stat(probe_path)
        maj_min = ledger_dev_maj_min if ledger_dev_maj_min is not None else f'{os.major(st.st_dev)}:{os.minor(st.st_dev)}'
        if proc_dev is None:
            proc_st = os.stat('/proc')
            proc_dev = f'{os.major(proc_st.st_dev)}:{os.minor(proc_st.st_dev)}'
        mountinfo = (
            f'22 1 {maj_min} / / rw,relatime - {fs_type} /dev/sda2 rw\n'
            f'31 22 {proc_dev} {proc_root} /proc rw,nosuid,nodev,noexec - {proc_fs} proc rw\n'
        )
        if extra_mounts:
            mountinfo += extra_mounts.rstrip('\n') + '\n'
        real_fstatfs_magic = cmd_fn.__globals__['_fstatfs_magic']
        real_fstat = os.fstat
        fs_magics = cmd_fn.__globals__['LOCAL_DURABLE_FS_MAGICS']

        def patched_fstatfs_magic(fd: int) -> int:
            st_fd = real_fstat(fd)
            if stat.S_ISDIR(st_fd.st_mode):
                return real_fstatfs_magic(fd) if proc_magic is None else proc_magic
            if ledger_magic is not None:
                return ledger_magic
            return fs_magics.get(fs_type, 0x01021994)

        return patch.dict(
            cmd_fn.__globals__,
            {
                '_fstatfs_magic': patched_fstatfs_magic,
                '_read_host_boot_id': lambda _proc_fd: boot_id,
                '_read_machine_id_raw': lambda: machine_id,
                '_read_proc_self_mountinfo': lambda _proc_fd: mountinfo,
                '_read_proc_self_status': lambda _proc_fd: f'Name:\tpython3\n{nstgid_line}',
                '_read_proc_self_ns_pid': lambda _proc_fd: (f'pid:[{pid_ns_ino}]', pid_ns_ino),
                '_read_fd_statvfs_fsid': lambda _fd: fsid,
                '_read_path_statvfs_fsid': lambda _path: fsid,
            },
        )

    def test_writer_recovery_missing_and_legacy_v1_v2_state_fail_closed_without_init_or_migration(self) -> None:
        a, _ = self.linked_pair()
        att_id = 'wa-' + 'a1' * 16
        db = self.xdg_state / 'pi-team-run' / 'state.db'
        script = runpy.run_path(str(BIN_PATH))
        cmd_recovery = script['cmd_writer_recovery']
        parser = script['build_parser']()
        boot_1 = '11111111-1111-4111-8111-111111111111'

        missing_arg = self.run_cli('writer-recovery', 'status')
        self.assertNotEqual(missing_arg.returncode, 0)

        res = self.run_cli('writer-recovery', 'status', att_id)
        self.assertNotEqual(res.returncode, 0)
        self.assertIn('missing', res.stderr.lower())
        self.assertFalse(self.xdg_state.exists())

        with self._recovery_host_patches(cmd_recovery, db, boot_id=boot_1):
            for action in ('arm', 'retire'):
                args = parser.parse_args([
                    'writer-recovery', action, att_id, '--cwd', a, '--issue', 'repo-1',
                    '--unbound', '--confirm-local-ledger',
                ])
                with self.assertRaisesRegex(script['CliError'], 'missing'):
                    cmd_recovery(args, db)
                self.assertFalse(self.xdg_state.exists())

        for version in (1, 2):
            sub_xdg = Path(self.tmp.name) / f'xdg-v{version}'
            sub_dir = sub_xdg / 'pi-team-run'
            sub_dir.mkdir(parents=True)
            sub_dir.chmod(0o700)
            sub_db = sub_dir / 'state.db'
            with closing(sqlite3.connect(sub_db)) as conn, conn:
                for stmt in script['V1_SCHEMA']:
                    conn.execute(stmt)
                if version == 2:
                    for stmt in script['V2_MIGRATION']:
                        conn.execute(stmt)
                conn.execute(f'PRAGMA user_version = {version}')
            sub_db.chmod(0o600)

            st_proc = subprocess.run(
                [sys.executable, str(BIN_PATH), 'writer-recovery', 'status', att_id],
                env={**self.env, 'XDG_STATE_HOME': str(sub_xdg)},
                text=True, capture_output=True, check=False,
            )
            self.assertNotEqual(st_proc.returncode, 0)
            self.assertIn(f'got {version}', st_proc.stderr.lower())

            with self._recovery_host_patches(cmd_recovery, sub_db, boot_id=boot_1):
                arm_args = parser.parse_args([
                    'writer-recovery', 'arm', att_id, '--cwd', a, '--issue', 'repo-1',
                    '--unbound', '--confirm-local-ledger',
                ])
                with self.assertRaisesRegex(script['CliError'], f'got {version}'):
                    cmd_recovery(arm_args, sub_db)

            with closing(sqlite3.connect(f'{sub_db.resolve().as_uri()}?mode=ro', uri=True)) as conn:
                self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0], version)
                self.assertIsNone(
                    conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='writer_attempts'").fetchone()
                )
                self.assertIsNone(
                    conn.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='writer_recovery_events'"
                    ).fetchone()
                )

    def test_writer_recovery_pre_db_validation_and_real_tmpfs_refusal(self) -> None:
        a, _ = self.linked_pair()
        seed = self.run_json('start', a, '--issue', 'repo-1')
        self.run_json('cancel', seed['run_id'], 'admit')
        db = self.xdg_state / 'pi-team-run' / 'state.db'
        att_id = 'wa-' + 'c3' * 16
        repo_key = str((self.repo_dir / '.git').resolve())
        wt_a_admin = str((self.repo_dir / '.git' / 'worktrees' / 'task-a').resolve())
        with closing(sqlite3.connect(db)) as conn, conn:
            conn.execute(
                "INSERT INTO writer_attempts(attempt_id, repo_key, worktree, issue, bound, run_id, status, created_at) "
                "VALUES (?, ?, ?, 'repo-1', 0, NULL, 'open', '2026-11-27T10:00:00Z')",
                (att_id, repo_key, wt_a_admin),
            )

        for bad_id in ('wa-short', 'wa-' + 'A' * 32, 'wa-unbound', 'not-an-attempt'):
            bad_proc = self.run_cli(
                'writer-recovery', 'arm', bad_id, '--cwd', a, '--issue', 'repo-1',
                '--unbound', '--confirm-local-ledger',
            )
            self.assertNotEqual(bad_proc.returncode, 0)
            self.assertIn('invalid writer attempt id', bad_proc.stderr.lower())

        no_attest = self.run_cli('writer-recovery', 'arm', att_id, '--cwd', a, '--issue', 'repo-1', '--unbound')
        self.assertNotEqual(no_attest.returncode, 0)
        self.assertIn('--confirm-local-ledger', no_attest.stderr)

        main_cwd = self.run_cli(
            'writer-recovery', 'arm', att_id, '--cwd', str(self.repo_dir), '--issue', 'repo-1',
            '--unbound', '--confirm-local-ledger',
        )
        self.assertNotEqual(main_cwd.returncode, 0)
        self.assertIn('linked git worktree', main_cwd.stderr.lower())

        nonexistent_cwd = self.run_cli(
            'writer-recovery', 'arm', att_id, '--cwd', str(Path(self.tmp.name) / 'no-such-wt'),
            '--issue', 'repo-1', '--unbound', '--confirm-local-ledger',
        )
        self.assertNotEqual(nonexistent_cwd.returncode, 0)

        for fake_flag in ('--boot-id', '--machine-id'):
            proc_flag = self.run_cli(
                'writer-recovery', 'arm', att_id, '--cwd', a, '--issue', 'repo-1',
                '--unbound', '--confirm-local-ledger', fake_flag, 'deadbeef',
            )
            self.assertNotEqual(proc_flag.returncode, 0)

        script = runpy.run_path(str(BIN_PATH))
        nsfs_fixture = (
            '22 1 259:2 / / rw,relatime shared:1 - ext4 /dev/nvme0n1p2 rw\n'
            '31 22 0:26 / /proc rw,nosuid,nodev,noexec - proc proc rw\n'
            '567 22 0:4 net:[4026533698] /run/docker/netns/abc123 rw shared:123 - nsfs nsfs rw\n'
            '568 22 0:4 mnt:[4026531841] /run/snapd/ns/foo.mnt rw - nsfs nsfs rw\n'
        )
        parsed_nsfs = script['_parse_mountinfo'](nsfs_fixture)
        self.assertIn(('0:4', 'net:[4026533698]', '/run/docker/netns/abc123', 'nsfs'), parsed_nsfs)
        self.assertIn(('0:4', 'mnt:[4026531841]', '/run/snapd/ns/foo.mnt', 'nsfs'), parsed_nsfs)
        for bad_mountinfo in (
            '',
            'malformed line without separator\n',
            '22 1 0:4 / - ext4 /dev/sda1 rw\n',
            'x 1 0:4 / / rw - ext4 /dev/sda1 rw\n',
            '22 1 bad / / rw - ext4 /dev/sda1 rw\n',
            '22 1 0:4 net:[4026533698] /mnt/x rw - ext4 /dev/sda1 rw\n',
            '22 1 0:4 net:[notanumber] /run/docker/netns/x rw - nsfs nsfs rw\n',
            '22 1 0:4 relative/root /run/docker/netns/x rw - nsfs nsfs rw\n',
            '22 1 0:4 / relative/mp rw - tmpfs tmpfs rw\n',
        ):
            with self.assertRaises(script['CliError']):
                script['_parse_mountinfo'](bad_mountinfo)

        mounts = script['_parse_mountinfo'](Path('/proc/self/mountinfo').read_text(encoding='utf-8'))
        tmp_resolved = Path(self.tmp.name).resolve()
        matching = [m for m in mounts if tmp_resolved == Path(m[2]) or tmp_resolved.is_relative_to(Path(m[2]))]
        tmp_fs = [m for m in matching if len(Path(m[2]).parts) == max(len(Path(x[2]).parts) for x in matching)][-1][3]
        proc_fd, _ = script['_open_pinned_proc_root']()
        try:
            proc_ns_ino = script['_read_proc_self_ns_pid'](proc_fd)[1]
        finally:
            os.close(proc_fd)
        if tmp_fs not in script['LOCAL_DURABLE_FS_TYPES'] and proc_ns_ino == script['PROC_PID_INIT_INO']:
            real_arm = self.run_cli(
                'writer-recovery', 'arm', att_id, '--cwd', a, '--issue', 'repo-1',
                '--unbound', '--confirm-local-ledger',
            )
            self.assertNotEqual(real_arm.returncode, 0)
            self.assertIn('not an allowed local durable filesystem', real_arm.stderr.lower())
            with closing(sqlite3.connect(f'{db.resolve().as_uri()}?mode=ro', uri=True)) as conn:
                self.assertIsNone(
                    conn.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='writer_recovery_events'"
                    ).fetchone()
                )

    def test_writer_recovery_bound_review_attempt_arm_same_boot_refusals_and_post_reboot_retire(self) -> None:
        a, b = self.linked_pair()
        repo_key = str((self.repo_dir / '.git').resolve())
        wt_a_admin = str((self.repo_dir / '.git' / 'worktrees' / 'task-a').resolve())
        wt_b_admin = str((self.repo_dir / '.git' / 'worktrees' / 'task-b').resolve())

        run_a = self.run_json('start', a, '--issue', 'repo-1')['run_id']
        for stage in ('admit', 'implement', 'check'):
            self.run_json('checkpoint', run_a, stage, '--evidence', f'ev:{stage}')
        self.run_json('wait', run_a, 'review', '--target', 'coordinator', '--reason', 'waiting review')
        run_b = self.run_json('start', b, '--issue', 'repo-2')['run_id']

        db = self.xdg_state / 'pi-team-run' / 'state.db'
        att_target = 'wa-' + 'd4' * 16
        att_other = 'wa-' + 'e5' * 16
        with closing(sqlite3.connect(db)) as conn, conn:
            conn.execute(
                "INSERT INTO writer_attempts(attempt_id, repo_key, worktree, issue, bound, run_id, status, created_at) "
                "VALUES (?, ?, ?, 'repo-1', 1, ?, 'open', '2026-11-27T09:00:00Z')",
                (att_target, repo_key, wt_a_admin, run_a),
            )
            conn.execute(
                "INSERT INTO writer_attempts(attempt_id, repo_key, worktree, issue, bound, run_id, status, created_at) "
                "VALUES (?, ?, ?, 'repo-2', 1, ?, 'open', '2026-11-27T09:05:00Z')",
                (att_other, repo_key, wt_b_admin, run_b),
            )

        pre_status_a = self.run_json('status', run_a)
        self.assertEqual(pre_status_a['status'], 'waiting')
        self.assertEqual(pre_status_a['current_stage'], 'review')
        self.assertFalse(pre_status_a['reserved'])

        unarmed_status = self.run_json('writer-recovery', 'status', att_target)
        self.assertEqual(unarmed_status['recovery_state'], 'unarmed')
        self.assertIsNone(unarmed_status['disposition'])
        self.assertEqual(unarmed_status['recovery_events'], [])
        with closing(sqlite3.connect(f'{db.resolve().as_uri()}?mode=ro', uri=True)) as conn:
            self.assertIsNone(
                conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='writer_recovery_events'"
                ).fetchone()
            )

        script = runpy.run_path(str(BIN_PATH))
        cmd_recovery = script['cmd_writer_recovery']
        parser = script['build_parser']()
        boot_1 = '1a2b3c4d-5e6f-4a1b-8c2d-3e4f5a6b7c8d'
        boot_2 = '9f8e7d6c-5b4a-4f3e-8d2c-1b0a9f8e7d6c'

        with self._recovery_host_patches(cmd_recovery, db, boot_id=boot_1):
            retire_before_arm = parser.parse_args([
                'writer-recovery', 'retire', att_target, '--cwd', a, '--issue', 'repo-1',
                '--run-id', run_a, '--confirm-local-ledger',
            ])
            with self.assertRaisesRegex(script['CliError'], 'not armed'):
                cmd_recovery(retire_before_arm, db)

            for bad_cli in (
                ['writer-recovery', 'arm', att_target, '--cwd', a, '--issue', 'repo-wrong', '--run-id', run_a, '--confirm-local-ledger'],
                ['writer-recovery', 'arm', att_target, '--cwd', b, '--issue', 'repo-1', '--run-id', run_a, '--confirm-local-ledger'],
                ['writer-recovery', 'arm', att_target, '--cwd', a, '--issue', 'repo-1', '--unbound', '--confirm-local-ledger'],
                ['writer-recovery', 'arm', att_target, '--cwd', a, '--issue', 'repo-1', '--run-id', run_b, '--confirm-local-ledger'],
                ['writer-recovery', 'arm', 'wa-' + 'ff' * 16, '--cwd', a, '--issue', 'repo-1', '--run-id', run_a, '--confirm-local-ledger'],
            ):
                with self.assertRaises(script['CliError']):
                    cmd_recovery(parser.parse_args(bad_cli), db)

        arm_args = parser.parse_args([
            'writer-recovery', 'arm', att_target, '--cwd', a, '--issue', 'repo-1',
            '--run-id', run_a, '--confirm-local-ledger', '--json',
        ])
        for bad_env_kwargs in (
            {'boot_id': '00000000-0000-0000-0000-000000000000'},
            {'boot_id': ''},
            {'boot_id': 'not-a-uuid'},
            {'boot_id': boot_1.upper()},
            {'boot_id': boot_1.replace('-', '')},
            {'machine_id': '0' * 32},
            {'machine_id': ''},
            {'machine_id': '1' * 31},
            {'machine_id': 'A' * 32},
            {'fs_type': 'tmpfs'},
            {'fs_type': 'nfs'},
            {'fs_type': 'nsfs'},
            {'fsid': 0},
            {'pid_ns_ino': 4026539999},
            {'nstgid_line': 'NStgid:\t1000\t1\n'},
            {'proc_fs': 'tmpfs'},
            {'proc_root': '/subdir'},
            {'extra_mounts': '99 31 0:99 / /proc/sys/kernel/random/boot_id rw - tmpfs tmpfs rw'},
            {'extra_mounts': '99 31 0:4 net:[4026533698] /proc/sys/kernel/random/boot_id rw - nsfs nsfs rw'},
        ):
            with self.subTest(bad_env=bad_env_kwargs):
                env_opts = dict(bad_env_kwargs)
                with self._recovery_host_patches(cmd_recovery, db, boot_id=env_opts.pop('boot_id', boot_1), **env_opts):
                    with self.assertRaises(script['CliError']):
                        cmd_recovery(arm_args, db)

        if Path('/proc/sys/kernel/random/boot_id').is_file():
            proc_fd, _ = script['_open_pinned_proc_root']()
            try:
                raw_boot = script['_read_host_boot_id'](proc_fd)
            finally:
                os.close(proc_fd)
            self.assertEqual(script['_validate_boot_id'](raw_boot), raw_boot)

        for bad_mode_target, bad_mode in (
            (db, 0o640),
            (db, 0o620),
            (db, 0o604),
            (db.parent, 0o750),
            (db.parent, 0o710),
        ):
            orig_mode = stat.S_IMODE(bad_mode_target.stat().st_mode)
            bad_mode_target.chmod(bad_mode)
            try:
                with self._recovery_host_patches(cmd_recovery, db, boot_id=boot_1):
                    with self.assertRaisesRegex(script['CliError'], 'private permissions'):
                        cmd_recovery(arm_args, db)
            finally:
                bad_mode_target.chmod(orig_mode)

        with closing(sqlite3.connect(f'{db.resolve().as_uri()}?mode=ro', uri=True)) as conn:
            self.assertIsNone(
                conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='writer_recovery_events'"
                ).fetchone()
            )
            self.assertEqual(
                conn.execute('SELECT status, exit_code, closed_at FROM writer_attempts WHERE attempt_id = ?', (att_target,)).fetchone()[:],
                ('open', None, None),
            )

        with self._recovery_host_patches(
            cmd_recovery,
            db,
            boot_id=boot_1,
            extra_mounts='567 22 0:4 net:[4026533698] /run/docker/netns/abc123 rw shared:123 - nsfs nsfs rw',
        ):
            code, armed = cmd_recovery(arm_args, db)
            self.assertEqual(code, 0)
            self.assertEqual(armed['action'], 'arm')
            self.assertEqual(armed['status'], 'open')
            self.assertIsNone(armed['exit_code'])
            self.assertIsNone(armed['disposition'])
            self.assertEqual(armed['observed_boot_id'], boot_1)
            self.assertEqual(armed['ledger_fs_type'], 'ext4')
            self.assertNotIn('1' * 32, json.dumps(armed))

            with self.assertRaisesRegex(script['CliError'], 'already has recovery event'):
                cmd_recovery(arm_args, db)

            retire_args = parser.parse_args([
                'writer-recovery', 'retire', att_target, '--cwd', a, '--issue', 'repo-1',
                '--run-id', run_a, '--confirm-local-ledger', '--json',
            ])
            with self.assertRaisesRegex(script['CliError'], 'same host boot'):
                cmd_recovery(retire_args, db)

        self.assertEqual(self.run_json('writer-recovery', 'status', att_target)['recovery_state'], 'armed')

        for drift_kwargs in (
            {'machine_id': '2' * 32},
            {'fsid': 0x12345678},
            {'fs_type': 'xfs'},
            {'pid_ns_ino': 4026539999},
        ):
            with self._recovery_host_patches(cmd_recovery, db, boot_id=boot_2, **drift_kwargs):
                with self.assertRaises(script['CliError']):
                    cmd_recovery(retire_args, db)

        for bad_retire_env in (
            {'boot_id': '00000000-0000-0000-0000-000000000000'},
            {'boot_id': 'malformed'},
            {'machine_id': '0' * 32},
        ):
            with self.subTest(bad_env=bad_retire_env):
                env_opts = dict(bad_retire_env)
                with self._recovery_host_patches(cmd_recovery, db, boot_id=env_opts.pop('boot_id', boot_2), **env_opts):
                    with self.assertRaises(script['CliError']):
                        cmd_recovery(retire_args, db)

        with self._recovery_host_patches(cmd_recovery, db, boot_id=boot_2):
            for bad_retire in (
                ['writer-recovery', 'retire', att_target, '--cwd', a, '--issue', 'repo-wrong', '--run-id', run_a, '--confirm-local-ledger'],
                ['writer-recovery', 'retire', att_target, '--cwd', b, '--issue', 'repo-1', '--run-id', run_a, '--confirm-local-ledger'],
                ['writer-recovery', 'retire', att_target, '--cwd', a, '--issue', 'repo-1', '--unbound', '--confirm-local-ledger'],
                ['writer-recovery', 'retire', att_target, '--cwd', a, '--issue', 'repo-1', '--run-id', run_b, '--confirm-local-ledger'],
            ):
                with self.assertRaises(script['CliError']):
                    cmd_recovery(parser.parse_args(bad_retire), db)

            code, retired = cmd_recovery(retire_args, db)
            self.assertEqual(code, 0)
            self.assertEqual(retired['action'], 'retire')
            self.assertEqual(retired['status'], 'closed')
            self.assertIsNone(retired['exit_code'])
            self.assertEqual(retired['disposition'], 'interrupted')
            self.assertEqual(retired['armed_boot_id'], boot_1)
            self.assertEqual(retired['retired_boot_id'], boot_2)
            self.assertTrue(retired['closed_at'])

            with self.assertRaisesRegex(script['CliError'], 'already been retired'):
                cmd_recovery(retire_args, db)
            with self.assertRaisesRegex(script['CliError'], 'not open'):
                cmd_recovery(arm_args, db)

        with self._recovery_host_patches(cmd_recovery, db, boot_id='33333333-3333-4333-8333-333333333333'):
            with self.assertRaisesRegex(script['CliError'], 'already been retired'):
                cmd_recovery(retire_args, db)

        post_status_a = self.run_json('status', run_a)
        expected_status_a = {
            **pre_status_a,
            'last_writer_attempt': {
                **pre_status_a['last_writer_attempt'],
                'status': 'closed',
                'exit_code': None,
                'closed_at': retired['closed_at'],
            },
        }
        self.assertEqual(post_status_a, expected_status_a)
        final_rec = self.run_json('writer-recovery', 'status', att_target)
        self.assertEqual(final_rec['status'], 'closed')
        self.assertIsNone(final_rec['exit_code'])
        self.assertEqual(final_rec['recovery_state'], 'retired')
        self.assertEqual(final_rec['disposition'], 'interrupted')
        self.assertEqual([ev['action'] for ev in final_rec['recovery_events']], ['arm', 'retire'])

        with closing(sqlite3.connect(f'{db.resolve().as_uri()}?mode=ro', uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0], 4)
            other_row = dict(conn.execute('SELECT status, exit_code, closed_at FROM writer_attempts WHERE attempt_id = ?', (att_other,)).fetchone())
            self.assertEqual(other_row, {'status': 'open', 'exit_code': None, 'closed_at': None})
        other_rec = self.run_json('writer-recovery', 'status', att_other)
        self.assertEqual((other_rec['status'], other_rec['recovery_state']), ('open', 'unarmed'))

    def test_writer_recovery_unbound_attempt_lifecycle(self) -> None:
        a, _ = self.linked_pair()
        repo_key = str((self.repo_dir / '.git').resolve())
        wt_a_admin = str((self.repo_dir / '.git' / 'worktrees' / 'task-a').resolve())
        seed = self.run_json('start', a, '--issue', 'repo-1')
        self.run_json('cancel', seed['run_id'], 'admit')

        db = self.xdg_state / 'pi-team-run' / 'state.db'
        att_unbound = 'wa-' + 'f6' * 16
        with closing(sqlite3.connect(db)) as conn, conn:
            conn.execute(
                "INSERT INTO writer_attempts(attempt_id, repo_key, worktree, issue, bound, run_id, status, created_at) "
                "VALUES (?, ?, ?, 'repo-1', 0, NULL, 'open', '2026-11-27T08:00:00Z')",
                (att_unbound, repo_key, wt_a_admin),
            )

        blocked = self.run_cli('start', a, '--issue', 'repo-1')
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn('writer fence', blocked.stderr.lower())

        script = runpy.run_path(str(BIN_PATH))
        cmd_recovery = script['cmd_writer_recovery']
        parser = script['build_parser']()
        boot_1 = '11111111-1111-4111-8111-111111111111'
        boot_2 = '22222222-2222-4222-8222-222222222222'

        with self._recovery_host_patches(cmd_recovery, db, boot_id=boot_1):
            with self.assertRaises(script['CliError']):
                cmd_recovery(parser.parse_args([
                    'writer-recovery', 'arm', att_unbound, '--cwd', a, '--issue', 'repo-1',
                    '--run-id', seed['run_id'], '--confirm-local-ledger',
                ]), db)
            code, armed = cmd_recovery(parser.parse_args([
                'writer-recovery', 'arm', att_unbound, '--cwd', a, '--issue', 'repo-1',
                '--unbound', '--confirm-local-ledger',
            ]), db)
            self.assertEqual((code, armed['bound'], armed['run_id']), (0, False, None))

        with self._recovery_host_patches(cmd_recovery, db, boot_id=boot_2):
            code, retired = cmd_recovery(parser.parse_args([
                'writer-recovery', 'retire', att_unbound, '--cwd', a, '--issue', 'repo-1',
                '--unbound', '--confirm-local-ledger',
            ]), db)
            self.assertEqual(code, 0)
            self.assertEqual(retired['status'], 'closed')
            self.assertIsNone(retired['exit_code'])
            self.assertEqual(retired['disposition'], 'interrupted')
            self.assertFalse(retired['bound'])
            self.assertIsNone(retired['run_id'])

        fresh = self.run_json('start', a, '--issue', 'repo-1')
        self.assertEqual(fresh['status'], 'active')

    def test_writer_recovery_refuses_whitespace_cwd_and_attempt_id_without_receipt(self) -> None:
        a, _ = self.linked_pair()
        repo_key = str((self.repo_dir / '.git').resolve())
        wt_a_admin = str((self.repo_dir / '.git' / 'worktrees' / 'task-a').resolve())
        seed = self.run_json('start', a, '--issue', 'repo-1')
        self.run_json('cancel', seed['run_id'], 'admit')

        db = self.xdg_state / 'pi-team-run' / 'state.db'
        att_id = 'wa-' + '21' * 16
        with closing(sqlite3.connect(db)) as conn, conn:
            conn.execute(
                "INSERT INTO writer_attempts(attempt_id, repo_key, worktree, issue, bound, run_id, status, created_at) "
                "VALUES (?, ?, ?, 'repo-1', 0, NULL, 'open', '2026-11-27T08:00:00Z')",
                (att_id, repo_key, wt_a_admin),
            )

        script = runpy.run_path(str(BIN_PATH))
        cmd_recovery = script['cmd_writer_recovery']
        parser = script['build_parser']()
        self.assertTrue(Path(a).is_dir())

        for action in ('arm', 'retire'):
            for bad_argv in (
                ['writer-recovery', action, att_id, '--cwd', f'{a} ', '--issue', 'repo-1',
                 '--unbound', '--confirm-local-ledger'],
                ['writer-recovery', action, att_id, '--cwd', f' {a}', '--issue', 'repo-1',
                 '--unbound', '--confirm-local-ledger'],
                ['writer-recovery', action, f'{att_id} ', '--cwd', a, '--issue', 'repo-1',
                 '--unbound', '--confirm-local-ledger'],
                ['writer-recovery', action, f' {att_id}', '--cwd', a, '--issue', 'repo-1',
                 '--unbound', '--confirm-local-ledger'],
            ):
                with self.subTest(action=action, argv=bad_argv):
                    with self.assertRaises(script['CliError']):
                        cmd_recovery(parser.parse_args(bad_argv), db)

            cwd_refusal = self.run_cli(
                'writer-recovery', action, att_id, '--cwd', f'{a} ', '--issue', 'repo-1',
                '--unbound', '--confirm-local-ledger',
            )
            self.assertNotEqual(cwd_refusal.returncode, 0)
            self.assertIn('whitespace', cwd_refusal.stderr.lower())

            id_refusal = self.run_cli(
                'writer-recovery', action, f'{att_id} ', '--cwd', a, '--issue', 'repo-1',
                '--unbound', '--confirm-local-ledger',
            )
            self.assertNotEqual(id_refusal.returncode, 0)
            self.assertIn('invalid writer attempt id', id_refusal.stderr.lower())

        with closing(sqlite3.connect(f'{db.resolve().as_uri()}?mode=ro', uri=True)) as conn:
            self.assertIsNone(
                conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='writer_recovery_events'"
                ).fetchone()
            )
            self.assertEqual(
                conn.execute(
                    'SELECT status, exit_code, closed_at FROM writer_attempts WHERE attempt_id = ?', (att_id,)
                ).fetchone()[:],
                ('open', None, None),
            )

    def test_writer_recovery_scope_options_single_use_and_run_id_verbatim(self) -> None:
        a, _ = self.linked_pair()
        repo_key = str((self.repo_dir / '.git').resolve())
        wt_a_admin = str((self.repo_dir / '.git' / 'worktrees' / 'task-a').resolve())
        db = self.xdg_state / 'pi-team-run' / 'state.db'
        seed = self.run_json('start', a, '--issue', 'repo-1')
        self.run_json('cancel', seed['run_id'], 'admit')

        legacy_run = ' legacy run 21 '
        att_id = 'wa-' + '22' * 16
        with closing(sqlite3.connect(db)) as conn, conn:
            conn.execute(
                'INSERT INTO runs(run_id, repo_key, status, current_stage, created_at, updated_at, issue, worktree) '
                "VALUES (?, ?, 'active', 'review', '2026-11-27T09:00:00Z', '2026-11-27T09:00:00Z', 'repo-legacy', ?)",
                (legacy_run, repo_key, wt_a_admin),
            )
            conn.execute(
                "INSERT INTO writer_attempts(attempt_id, repo_key, worktree, issue, bound, run_id, status, created_at) "
                "VALUES (?, ?, ?, 'repo-legacy', 1, ?, 'open', '2026-11-27T09:10:00Z')",
                (att_id, repo_key, wt_a_admin, legacy_run),
            )

        script = runpy.run_path(str(BIN_PATH))
        cmd_recovery = script['cmd_writer_recovery']
        parser = script['build_parser']()
        boot_1 = '11111111-1111-4111-8111-111111111111'
        boot_2 = '22222222-2222-4222-8222-222222222222'

        duplicate_option_lists = (
            ['--cwd', a, '--cwd', a, '--issue', 'repo-legacy', '--run-id', legacy_run,
             '--confirm-local-ledger'],
            ['--cwd', a, '--cwd', str(self.repo_dir), '--issue', 'repo-legacy', '--run-id', legacy_run,
             '--confirm-local-ledger'],
            ['--cwd', a, '--issue', 'repo-legacy', '--issue', 'repo-legacy', '--run-id', legacy_run,
             '--confirm-local-ledger'],
            ['--cwd', a, '--issue', 'repo-legacy', '--issue', 'repo-1', '--run-id', legacy_run,
             '--confirm-local-ledger'],
            ['--cwd', a, '--issue', 'repo-legacy', '--run-id', legacy_run, '--run-id', legacy_run,
             '--confirm-local-ledger'],
            ['--cwd', a, '--issue', 'repo-legacy', '--run-id', legacy_run, '--run-id', 'run-other',
             '--confirm-local-ledger'],
        )
        for action in ('arm', 'retire'):
            for opts in duplicate_option_lists:
                with self.subTest(action=action, opts=opts):
                    with self.assertRaises(SystemExit) as raised:
                        parser.parse_args(['writer-recovery', action, att_id, *opts])
                    self.assertEqual(raised.exception.code, 2)

            repeated = self.run_cli(
                'writer-recovery', action, att_id, '--cwd', a, '--issue', 'repo-legacy',
                '--run-id', legacy_run, '--run-id', legacy_run, '--confirm-local-ledger',
            )
            self.assertEqual(repeated.returncode, 2)
            self.assertIn('only once', repeated.stderr.lower())

        with closing(sqlite3.connect(f'{db.resolve().as_uri()}?mode=ro', uri=True)) as conn:
            self.assertIsNone(
                conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='writer_recovery_events'"
                ).fetchone()
            )
            self.assertEqual(
                conn.execute(
                    'SELECT status, exit_code, closed_at FROM writer_attempts WHERE attempt_id = ?', (att_id,)
                ).fetchone()[:],
                ('open', None, None),
            )

        trimmed_arm = parser.parse_args([
            'writer-recovery', 'arm', att_id, '--cwd', a, '--issue', 'repo-legacy',
            '--run-id', legacy_run.strip(), '--confirm-local-ledger',
        ])
        with self._recovery_host_patches(cmd_recovery, db, boot_id=boot_1):
            with self.assertRaisesRegex(script['CliError'], 'scope does not match'):
                cmd_recovery(trimmed_arm, db)

        arm_args = parser.parse_args([
            'writer-recovery', 'arm', att_id, '--cwd', a, '--issue', 'repo-legacy',
            '--run-id', legacy_run, '--confirm-local-ledger',
        ])
        with self._recovery_host_patches(cmd_recovery, db, boot_id=boot_1):
            code, armed = cmd_recovery(arm_args, db)
        self.assertEqual(code, 0)
        self.assertEqual(armed['run_id'], legacy_run)

        retire_trimmed = parser.parse_args([
            'writer-recovery', 'retire', att_id, '--cwd', a, '--issue', 'repo-legacy',
            '--run-id', legacy_run.strip(), '--confirm-local-ledger',
        ])
        retire_args = parser.parse_args([
            'writer-recovery', 'retire', att_id, '--cwd', a, '--issue', 'repo-legacy',
            '--run-id', legacy_run, '--confirm-local-ledger',
        ])
        with self._recovery_host_patches(cmd_recovery, db, boot_id=boot_2):
            with self.assertRaisesRegex(script['CliError'], 'scope does not match'):
                cmd_recovery(retire_trimmed, db)
            code, retired = cmd_recovery(retire_args, db)
        self.assertEqual(code, 0)
        self.assertEqual((retired['status'], retired['run_id']), ('closed', legacy_run))
        self.assertEqual(retired['disposition'], 'interrupted')

        with closing(sqlite3.connect(f'{db.resolve().as_uri()}?mode=ro', uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            self.assertEqual(
                [dict(row) for row in conn.execute(
                    'SELECT action, attempt_run_id FROM writer_recovery_events WHERE attempt_id = ? ORDER BY action',
                    (att_id,),
                )],
                [{'action': 'arm', 'attempt_run_id': legacy_run},
                 {'action': 'retire', 'attempt_run_id': legacy_run}],
            )
            self.assertEqual(
                conn.execute('SELECT status FROM runs WHERE run_id = ?', (legacy_run,)).fetchone()['status'],
                'active',
            )
            self.assertEqual(
                conn.execute(
                    'SELECT status, exit_code FROM writer_attempts WHERE attempt_id = ?', (att_id,)
                ).fetchone()[:],
                ('closed', None),
            )

    def test_writer_recovery_rejects_already_closed_tampering_and_inode_drift(self) -> None:
        a, _ = self.linked_pair()
        repo_key = str((self.repo_dir / '.git').resolve())
        wt_a_admin = str((self.repo_dir / '.git' / 'worktrees' / 'task-a').resolve())
        seed = self.run_json('start', a, '--issue', 'repo-1')
        self.run_json('cancel', seed['run_id'], 'admit')

        db = self.xdg_state / 'pi-team-run' / 'state.db'
        att_closed = 'wa-' + '07' * 16
        att_open = 'wa-' + '08' * 16
        with closing(sqlite3.connect(db)) as conn, conn:
            conn.execute(
                "INSERT INTO writer_attempts(attempt_id, repo_key, worktree, issue, bound, run_id, status, exit_code, created_at, closed_at) "
                "VALUES (?, ?, ?, 'repo-1', 0, NULL, 'closed', 0, '2026-11-27T07:00:00Z', '2026-11-27T07:05:00Z')",
                (att_closed, repo_key, wt_a_admin),
            )
            conn.execute(
                "INSERT INTO writer_attempts(attempt_id, repo_key, worktree, issue, bound, run_id, status, created_at) "
                "VALUES (?, ?, ?, 'repo-1', 0, NULL, 'open', '2026-11-27T08:00:00Z')",
                (att_open, repo_key, wt_a_admin),
            )

        script = runpy.run_path(str(BIN_PATH))
        cmd_recovery = script['cmd_writer_recovery']
        parser = script['build_parser']()
        boot_1 = '11111111-1111-4111-8111-111111111111'
        boot_2 = '22222222-2222-4222-8222-222222222222'

        with self._recovery_host_patches(cmd_recovery, db, boot_id=boot_1):
            with self.assertRaisesRegex(script['CliError'], 'not open'):
                cmd_recovery(parser.parse_args([
                    'writer-recovery', 'arm', att_closed, '--cwd', a, '--issue', 'repo-1',
                    '--unbound', '--confirm-local-ledger',
                ]), db)
            cmd_recovery(parser.parse_args([
                'writer-recovery', 'arm', att_open, '--cwd', a, '--issue', 'repo-1',
                '--unbound', '--confirm-local-ledger',
            ]), db)

        with closing(sqlite3.connect(db)) as conn, conn:
            with self.assertRaisesRegex(sqlite3.DatabaseError, 'append-only'):
                conn.execute("UPDATE writer_recovery_events SET boot_id = ? WHERE attempt_id = ?", (boot_2, att_open))
            with self.assertRaisesRegex(sqlite3.DatabaseError, 'append-only'):
                conn.execute("DELETE FROM writer_recovery_events WHERE attempt_id = ?", (att_open,))

        retire_args = parser.parse_args([
            'writer-recovery', 'retire', att_open, '--cwd', a, '--issue', 'repo-1',
            '--unbound', '--confirm-local-ledger',
        ])

        real_pin_check = cmd_recovery.__globals__['_verify_pinned_ledger_under_tx']
        calls = 0

        def fail_on_precommit_pin(path_arg: Path, expected_arg: dict) -> None:
            nonlocal calls
            calls += 1
            if calls == 4:
                raise script['CliError']('writer ledger inode changed under mutation boundary')
            return real_pin_check(path_arg, expected_arg)

        with self._recovery_host_patches(cmd_recovery, db, boot_id=boot_2):
            with patch.dict(cmd_recovery.__globals__, {'_verify_pinned_ledger_under_tx': fail_on_precommit_pin}):
                with self.assertRaisesRegex(script['CliError'], 'inode changed under mutation boundary'):
                    cmd_recovery(retire_args, db)

        with closing(sqlite3.connect(f'{db.resolve().as_uri()}?mode=ro', uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            self.assertEqual(
                conn.execute('SELECT status, exit_code FROM writer_attempts WHERE attempt_id = ?', (att_open,)).fetchone()['status'],
                'open',
            )
            self.assertEqual(
                conn.execute('SELECT count(*) FROM writer_recovery_events WHERE attempt_id = ?', (att_open,)).fetchone()[0],
                1,
            )

        with closing(sqlite3.connect(db)) as conn, conn:
            conn.execute(
                "UPDATE writer_attempts SET created_at = '2026-11-27T08:00:01Z' WHERE attempt_id = ?",
                (att_open,),
            )
        with self._recovery_host_patches(cmd_recovery, db, boot_id=boot_2):
            with self.assertRaisesRegex(script['CliError'], 'changed since arm'):
                cmd_recovery(retire_args, db)
        with closing(sqlite3.connect(db)) as conn, conn:
            conn.execute(
                "UPDATE writer_attempts SET created_at = '2026-11-27T08:00:00Z' WHERE attempt_id = ?",
                (att_open,),
            )

        hardlink_db = db.parent / 'state-hardlink.db'
        os.link(db, hardlink_db)
        try:
            with self._recovery_host_patches(cmd_recovery, db, boot_id=boot_2):
                with self.assertRaisesRegex(script['CliError'], 'hardlink'):
                    cmd_recovery(retire_args, db)
        finally:
            hardlink_db.unlink()

        copied_db = db.parent / 'state-copy.db'
        shutil.copy2(db, copied_db)
        copied_db.chmod(0o600)
        os.replace(copied_db, db)
        with self._recovery_host_patches(cmd_recovery, db, boot_id=boot_2):
            with self.assertRaisesRegex(script['CliError'], 'ledger continuity mismatch'):
                cmd_recovery(retire_args, db)

        moved_db = db.parent / 'state-moved.db'
        os.replace(db, moved_db)
        db.symlink_to(moved_db)
        try:
            with self._recovery_host_patches(cmd_recovery, db, boot_id=boot_2):
                with self.assertRaisesRegex(script['CliError'], 'symlink-free'):
                    cmd_recovery(retire_args, db)
        finally:
            db.unlink()
            os.replace(moved_db, db)

        with closing(sqlite3.connect(f'{db.resolve().as_uri()}?mode=ro', uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            self.assertEqual(
                dict(conn.execute('SELECT status, exit_code, closed_at FROM writer_attempts WHERE attempt_id = ?', (att_open,)).fetchone()),
                {'status': 'open', 'exit_code': None, 'closed_at': None},
            )

        db.chmod(0o640)
        try:
            with self._recovery_host_patches(cmd_recovery, db, boot_id=boot_2):
                with self.assertRaisesRegex(script['CliError'], 'private permissions'):
                    cmd_recovery(retire_args, db)
        finally:
            db.chmod(0o600)

        perm_calls = 0

        def drift_perms_under_tx(path_arg: Path, expected_arg: dict) -> None:
            nonlocal perm_calls
            perm_calls += 1
            if perm_calls == 3:
                path_arg.parent.chmod(0o750)
            return real_pin_check(path_arg, expected_arg)

        try:
            with self._recovery_host_patches(cmd_recovery, db, boot_id=boot_2):
                with patch.dict(cmd_recovery.__globals__, {'_verify_pinned_ledger_under_tx': drift_perms_under_tx}):
                    with self.assertRaisesRegex(script['CliError'], 'private permissions'):
                        cmd_recovery(retire_args, db)
        finally:
            db.parent.chmod(0o700)

        with self._recovery_host_patches(cmd_recovery, db, boot_id=boot_2):
            req = script['_validate_recovery_request'](retire_args, db)
            with script['_open_recovery_write_tx'](db, req) as tx_conn:
                self.assertEqual(tx_conn.execute('PRAGMA synchronous').fetchone()[0], 3)
                self.assertEqual(str(tx_conn.execute('PRAGMA journal_mode').fetchone()[0]).lower(), 'delete')

        with closing(sqlite3.connect(db)) as conn:
            conn.execute('PRAGMA journal_mode = WAL')
        try:
            with self._recovery_host_patches(cmd_recovery, db, boot_id=boot_2):
                with self.assertRaisesRegex(script['CliError'], 'rollback journal mode'):
                    cmd_recovery(retire_args, db)
            with closing(sqlite3.connect(f'{db.resolve().as_uri()}?mode=ro', uri=True)) as conn:
                self.assertEqual(str(conn.execute('PRAGMA journal_mode').fetchone()[0]).lower(), 'wal')
                self.assertEqual(
                    conn.execute('SELECT status, exit_code, closed_at FROM writer_attempts WHERE attempt_id = ?', (att_open,)).fetchone()[:],
                    ('open', None, None),
                )
                self.assertEqual(
                    conn.execute('SELECT count(*) FROM writer_recovery_events WHERE attempt_id = ?', (att_open,)).fetchone()[0],
                    1,
                )
        finally:
            with closing(sqlite3.connect(db)) as conn:
                conn.execute('PRAGMA journal_mode = DELETE')

    def test_recovery_write_tx_preserves_posix_lock_across_under_tx_rechecks(self) -> None:
        a, _ = self.linked_pair()
        repo_key = str((self.repo_dir / '.git').resolve())
        wt_a_admin = str((self.repo_dir / '.git' / 'worktrees' / 'task-a').resolve())
        seed = self.run_json('start', a, '--issue', 'repo-1')
        self.run_json('cancel', seed['run_id'], 'admit')

        db = self.xdg_state / 'pi-team-run' / 'state.db'
        att_id = 'wa-' + '19' * 16
        with closing(sqlite3.connect(db)) as conn, conn:
            conn.execute(
                "INSERT INTO writer_attempts(attempt_id, repo_key, worktree, issue, bound, run_id, status, created_at) "
                "VALUES (?, ?, ?, 'repo-1', 0, NULL, 'open', '2026-11-27T08:00:00Z')",
                (att_id, repo_key, wt_a_admin),
            )

        script = runpy.run_path(str(BIN_PATH))
        cmd_recovery = script['cmd_writer_recovery']
        parser = script['build_parser']()
        boot_1 = '11111111-1111-4111-8111-111111111111'
        arm_args = parser.parse_args([
            'writer-recovery', 'arm', att_id, '--cwd', a, '--issue', 'repo-1',
            '--unbound', '--confirm-local-ledger',
        ])

        probe_code = (
            'import sqlite3, sys\n'
            'conn = sqlite3.connect(sys.argv[1], uri=True, timeout=0.05, isolation_level=None)\n'
            'try:\n'
            '    conn.execute("PRAGMA busy_timeout = 50")\n'
            '    try:\n'
            '        conn.execute("BEGIN IMMEDIATE")\n'
            '    except sqlite3.OperationalError as exc:\n'
            '        code = getattr(exc, "sqlite_errorcode", None)\n'
            '        name = getattr(exc, "sqlite_errorname", None)\n'
            '        msg = str(exc)\n'
            '        is_busy = (\n'
            '            code == getattr(sqlite3, "SQLITE_BUSY", 5)\n'
            '            or name == "SQLITE_BUSY"\n'
            '            or "locked" in msg.lower()\n'
            '            or "busy" in msg.lower()\n'
            '        )\n'
            '        if is_busy:\n'
            '            label = name or "SQLITE_BUSY"\n'
            '            print(f"{label}:{msg}")\n'
            '            sys.exit(2)\n'
            '        raise\n'
            '    try:\n'
            '        conn.execute("ROLLBACK")\n'
            '    except sqlite3.Error:\n'
            '        pass\n'
            '    print("ACQUIRED")\n'
            '    sys.exit(0)\n'
            'finally:\n'
            '    conn.close()\n'
        )
        db_uri = f'{db.resolve().as_uri()}?mode=rw'

        def probe_begin_immediate() -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [sys.executable, '-I', '-c', probe_code, db_uri],
                text=True,
                capture_output=True,
                check=False,
                timeout=5,
            )

        pre_probe = probe_begin_immediate()
        self.assertEqual(pre_probe.returncode, 0, msg=pre_probe.stdout + pre_probe.stderr)
        self.assertEqual(pre_probe.stdout.strip(), 'ACQUIRED')

        with self._recovery_host_patches(cmd_recovery, db, boot_id=boot_1):
            req = script['_validate_recovery_request'](arm_args, db)
            with script['_open_recovery_write_tx'](db, req) as tx_conn:
                self.assertTrue(tx_conn.in_transaction)
                held_probe = probe_begin_immediate()
                self.assertEqual(held_probe.returncode, 2, msg=held_probe.stdout + held_probe.stderr)
                self.assertRegex(held_probe.stdout.lower(), r'sqlite_busy|locked')

                script['_verify_pinned_ledger_under_tx'](db, req)
                os.statvfs(db)
                recheck_probe = probe_begin_immediate()
                self.assertEqual(recheck_probe.returncode, 2, msg=recheck_probe.stdout + recheck_probe.stderr)
                self.assertRegex(recheck_probe.stdout.lower(), r'sqlite_busy|locked')

            after_probe = probe_begin_immediate()
            self.assertEqual(after_probe.returncode, 0, msg=after_probe.stdout + after_probe.stderr)
            self.assertEqual(after_probe.stdout.strip(), 'ACQUIRED')

            with self.assertRaisesRegex(script['CliError'], 'rollback abort'):
                with script['_open_recovery_write_tx'](db, req) as tx_conn:
                    tx_conn.execute(
                        "UPDATE writer_attempts SET status = 'closed', closed_at = '2026-11-27T08:01:00Z' "
                        "WHERE attempt_id = ?",
                        (att_id,),
                    )
                    rollback_probe = probe_begin_immediate()
                    self.assertEqual(rollback_probe.returncode, 2, msg=rollback_probe.stdout + rollback_probe.stderr)
                    self.assertRegex(rollback_probe.stdout.lower(), r'sqlite_busy|locked')
                    raise script['CliError']('rollback abort')

        after_rollback_probe = probe_begin_immediate()
        self.assertEqual(after_rollback_probe.returncode, 0, msg=after_rollback_probe.stdout + after_rollback_probe.stderr)
        self.assertEqual(after_rollback_probe.stdout.strip(), 'ACQUIRED')
        with closing(sqlite3.connect(f'{db.resolve().as_uri()}?mode=ro', uri=True)) as conn:
            self.assertEqual(
                conn.execute('SELECT status, closed_at FROM writer_attempts WHERE attempt_id = ?', (att_id,)).fetchone()[:],
                ('open', None),
            )

        with self._recovery_host_patches(cmd_recovery, db, boot_id=boot_1):
            req = script['_validate_recovery_request'](arm_args, db)
            with patch.dict(cmd_recovery.__globals__, {'_read_path_statvfs_fsid': lambda _path: 0x12345678}):
                with self.assertRaisesRegex(script['CliError'], 'filesystem ID changed under mutation boundary'):
                    with script['_open_recovery_write_tx'](db, req):
                        pass

            def drift_during_statvfs(path_arg: Path) -> int:
                path_arg.chmod(0o640)
                return 0x9123456789ABCDEF

            try:
                with patch.dict(cmd_recovery.__globals__, {'_read_path_statvfs_fsid': drift_during_statvfs}):
                    with self.assertRaisesRegex(script['CliError'], 'private permissions'):
                        with script['_open_recovery_write_tx'](db, req):
                            pass
            finally:
                db.chmod(0o600)

    def test_writer_recovery_kernel_openat2_boot_read_and_boundary_refusals(self) -> None:
        if sys.platform != 'linux' or os.uname().machine not in ('x86_64', 'aarch64'):
            self.skipTest('Linux x86_64/aarch64 openat2 required')
        if not Path('/proc/sys/kernel/random/boot_id').is_file():
            self.skipTest('/proc/sys/kernel/random/boot_id required')

        script = runpy.run_path(str(BIN_PATH))
        proc_fd, proc_st = script['_open_pinned_proc_root']()
        try:
            self.assertEqual(proc_st.st_ino, script['PROC_ROOT_INO'])
            self.assertEqual(script['_fstatfs_magic'](proc_fd), script['PROC_SUPER_MAGIC'])
            self.assertEqual(script['_read_proc_self_pid'](proc_fd), os.getpid())
            raw_boot = script['_read_host_boot_id'](proc_fd)
            self.assertEqual(script['_validate_boot_id'](raw_boot), raw_boot)

            mounts = script['_parse_mountinfo'](script['_read_proc_self_mountinfo'](proc_fd))
            proc_mounts = [m for m in mounts if m[2] == '/proc']
            self.assertEqual(len(proc_mounts), 1)
            actual_maj_min = f'{os.major(proc_st.st_dev)}:{os.minor(proc_st.st_dev)}'
            self.assertEqual(proc_mounts[0][0], actual_maj_min)
            self.assertEqual(proc_mounts[0][1], '/')
            self.assertEqual(proc_mounts[0][3], 'proc')

            status_text = script['_read_proc_self_status'](proc_fd)
            self.assertIn('NStgid:', status_text)
            ns_link, ns_ino = script['_read_proc_self_ns_pid'](proc_fd)
            self.assertEqual(ns_link, f'pid:[{ns_ino}]')
            nstgid_line = next(line for line in status_text.splitlines() if line.startswith('NStgid:'))
            if len(nstgid_line.split(':', 1)[1].split()) == 1 and ns_ino == script['PROC_PID_INIT_INO']:
                verified_ino, _ = script['_verify_initial_pid_namespace_and_procfs'](proc_fd, proc_st)
                self.assertEqual(verified_ino, script['PROC_PID_INIT_INO'])
        finally:
            os.close(proc_fd)

        a, _ = self.linked_pair()
        repo_key = str((self.repo_dir / '.git').resolve())
        wt_a_admin = str((self.repo_dir / '.git' / 'worktrees' / 'task-a').resolve())
        seed = self.run_json('start', a, '--issue', 'repo-1')
        self.run_json('cancel', seed['run_id'], 'admit')

        db = self.xdg_state / 'pi-team-run' / 'state.db'
        att_id = 'wa-' + '2b' * 16
        with closing(sqlite3.connect(db)) as conn, conn:
            conn.execute(
                "INSERT INTO writer_attempts(attempt_id, repo_key, worktree, issue, bound, run_id, status, created_at) "
                "VALUES (?, ?, ?, 'repo-1', 0, NULL, 'open', '2026-11-27T09:00:00Z')",
                (att_id, repo_key, wt_a_admin),
            )

        cmd_recovery = script['cmd_writer_recovery']
        parser = script['build_parser']()
        arm_args = parser.parse_args([
            'writer-recovery', 'arm', att_id, '--cwd', a, '--issue', 'repo-1',
            '--unbound', '--confirm-local-ledger',
        ])
        retire_args = parser.parse_args([
            'writer-recovery', 'retire', att_id, '--cwd', a, '--issue', 'repo-1',
            '--unbound', '--confirm-local-ledger',
        ])
        real_openat2 = script['_linux_openat2']
        real_read_boot = script['_read_host_boot_id']

        for err_no in (errno.EXDEV, errno.ELOOP, errno.ENOSYS):
            def fail_boot_openat2(dir_fd: int, rel_path: str, flags: int, resolve: int, _err=err_no) -> int:
                if rel_path == 'sys/kernel/random/boot_id':
                    raise OSError(_err, os.strerror(_err))
                return real_openat2(dir_fd, rel_path, flags, resolve)

            with self._recovery_host_patches(cmd_recovery, db, boot_id=raw_boot):
                with patch.dict(cmd_recovery.__globals__, {
                    '_read_host_boot_id': real_read_boot,
                    '_linux_openat2': fail_boot_openat2,
                }):
                    with self.assertRaisesRegex(script['CliError'], 'pinned procfs root'):
                        cmd_recovery(arm_args, db)

        with self._recovery_host_patches(cmd_recovery, db, boot_id=raw_boot):
            with patch.dict(cmd_recovery.__globals__, {'_read_host_boot_id': real_read_boot}):
                with patch('os.uname', return_value=type('U', (), {'machine': 'riscv64'})()):
                    with self.assertRaisesRegex(script['CliError'], 'not supported on architecture'):
                        cmd_recovery(arm_args, db)
                with patch.object(sys, 'platform', 'darwin'):
                    with self.assertRaisesRegex(script['CliError'], 'requires Linux'):
                        cmd_recovery(arm_args, db)

        real_fstat = os.fstat

        def wrong_proc_inode_fstat(fd: int):
            st = real_fstat(fd)
            if stat.S_ISDIR(st.st_mode) and st.st_ino == script['PROC_ROOT_INO']:
                return os.stat_result((
                    st.st_mode, 2, st.st_dev, st.st_nlink, st.st_uid, st.st_gid,
                    st.st_size, st.st_atime, st.st_mtime, st.st_ctime,
                ))
            return st

        with self._recovery_host_patches(cmd_recovery, db, boot_id=raw_boot):
            with patch('os.fstat', side_effect=wrong_proc_inode_fstat):
                with self.assertRaisesRegex(script['CliError'], 'untrusted /proc root inode'):
                    cmd_recovery(arm_args, db)

        with self._recovery_host_patches(cmd_recovery, db, boot_id=raw_boot, proc_dev='0:99999'):
            with self.assertRaisesRegex(script['CliError'], 'device mismatch'):
                cmd_recovery(arm_args, db)

        with self._recovery_host_patches(
            cmd_recovery,
            db,
            boot_id=raw_boot,
            extra_mounts='99 22 0:99 / /proc rw - proc proc rw',
        ):
            with self.assertRaisesRegex(script['CliError'], 'unique /proc mount'):
                cmd_recovery(arm_args, db)

        with closing(sqlite3.connect(f'{db.resolve().as_uri()}?mode=ro', uri=True)) as conn:
            self.assertEqual(
                conn.execute('SELECT status, exit_code, closed_at FROM writer_attempts WHERE attempt_id = ?', (att_id,)).fetchone()[:],
                ('open', None, None),
            )
            self.assertIsNone(
                conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='writer_recovery_events'").fetchone()
            )

        with self._recovery_host_patches(cmd_recovery, db, boot_id='11111111-1111-4111-8111-111111111111'):
            code, armed = cmd_recovery(arm_args, db)
            self.assertEqual(code, 0)
            self.assertEqual(armed['action'], 'arm')

        def fail_retire_exdev(dir_fd: int, rel_path: str, flags: int, resolve: int) -> int:
            if rel_path == 'sys/kernel/random/boot_id':
                raise OSError(errno.EXDEV, os.strerror(errno.EXDEV))
            return real_openat2(dir_fd, rel_path, flags, resolve)

        with self._recovery_host_patches(cmd_recovery, db, boot_id='22222222-2222-4222-8222-222222222222'):
            with patch.dict(cmd_recovery.__globals__, {
                '_read_host_boot_id': real_read_boot,
                '_linux_openat2': fail_retire_exdev,
            }):
                with self.assertRaisesRegex(script['CliError'], 'pinned procfs root'):
                    cmd_recovery(retire_args, db)

        with closing(sqlite3.connect(f'{db.resolve().as_uri()}?mode=ro', uri=True)) as conn:
            self.assertEqual(
                conn.execute('SELECT status, exit_code, closed_at FROM writer_attempts WHERE attempt_id = ?', (att_id,)).fetchone()[:],
                ('open', None, None),
            )
            self.assertEqual(
                [r[0] for r in conn.execute('SELECT action FROM writer_recovery_events WHERE attempt_id = ?', (att_id,)).fetchall()],
                ['arm'],
            )

    def test_writer_recovery_authenticates_procfs_self_pid_and_ledger_fs_magic(self) -> None:
        if sys.platform != 'linux' or os.uname().machine not in ('x86_64', 'aarch64'):
            self.skipTest('Linux x86_64/aarch64 fstatfs required')
        if not Path('/proc/sys/kernel/random/boot_id').is_file():
            self.skipTest('/proc/sys/kernel/random/boot_id required')

        a, _ = self.linked_pair()
        repo_key = str((self.repo_dir / '.git').resolve())
        wt_a_admin = str((self.repo_dir / '.git' / 'worktrees' / 'task-a').resolve())
        seed = self.run_json('start', a, '--issue', 'repo-1')
        self.run_json('cancel', seed['run_id'], 'admit')

        db = self.xdg_state / 'pi-team-run' / 'state.db'
        att_id = 'wa-' + '4e' * 16
        with closing(sqlite3.connect(db)) as conn, conn:
            conn.execute(
                "INSERT INTO writer_attempts(attempt_id, repo_key, worktree, issue, bound, run_id, status, created_at) "
                "VALUES (?, ?, ?, 'repo-1', 0, NULL, 'open', '2026-11-27T09:00:00Z')",
                (att_id, repo_key, wt_a_admin),
            )

        script = runpy.run_path(str(BIN_PATH))
        cmd_recovery = script['cmd_writer_recovery']
        parser = script['build_parser']()
        boot_1 = '11111111-1111-4111-8111-111111111111'
        boot_2 = '22222222-2222-4222-8222-222222222222'
        arm_args = parser.parse_args([
            'writer-recovery', 'arm', att_id, '--cwd', a, '--issue', 'repo-1',
            '--unbound', '--confirm-local-ledger',
        ])
        retire_args = parser.parse_args([
            'writer-recovery', 'retire', att_id, '--cwd', a, '--issue', 'repo-1',
            '--unbound', '--confirm-local-ledger',
        ])

        # Verify real fstatfs on host ledger FD and fail-closed on bad FD / ABI.
        probe_fd = os.open(db, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            real_magic = script['_fstatfs_magic'](probe_fd)
            self.assertGreater(real_magic, 0)
            mounts = script['_parse_mountinfo'](Path('/proc/self/mountinfo').read_text(encoding='utf-8'))
            db_resolved = db.resolve()
            matching = [m for m in mounts if db_resolved == Path(m[2]) or db_resolved.is_relative_to(Path(m[2]))]
            host_fs = [m for m in matching if len(Path(m[2]).parts) == max(len(Path(x[2]).parts) for x in matching)][-1][3]
            if host_fs in script['LOCAL_DURABLE_FS_MAGICS']:
                self.assertEqual(real_magic, script['LOCAL_DURABLE_FS_MAGICS'][host_fs])
            elif host_fs == 'tmpfs':
                self.assertEqual(real_magic, 0x01021994)
        finally:
            os.close(probe_fd)
        with self.assertRaisesRegex(script['CliError'], 'valid open file descriptor'):
            script['_fstatfs_magic'](-1)
        unused_r, unused_w = os.pipe()
        os.close(unused_r)
        os.close(unused_w)
        with self.assertRaisesRegex(script['CliError'], 'fstatfs'):
            script['_fstatfs_magic'](unused_r)
        fake_ctypes = type('FakeCtypes', (), {
            'sizeof': staticmethod(lambda _t: 4),
            'c_long': script['ctypes'].c_long,
            'c_void_p': script['ctypes'].c_void_p,
        })()
        with patch.dict(cmd_recovery.__globals__, {'ctypes': fake_ctypes}):
            with self.assertRaisesRegex(script['CliError'], '64-bit LP64 ABI'):
                cmd_recovery(arm_args, db)

        # 1. Simulated wrong /proc magic despite matching root inode (1) and /proc mountinfo.
        for bad_proc_magic in (0x01021994, 0xEF53):
            with self._recovery_host_patches(cmd_recovery, db, boot_id=boot_1, proc_magic=bad_proc_magic):
                with self.assertRaisesRegex(script['CliError'], 'untrusted /proc filesystem magic'):
                    cmd_recovery(arm_args, db)
        proc_fd, proc_st = script['_open_pinned_proc_root']()
        try:
            mountinfo_calls: list[int] = []
            with patch.dict(cmd_recovery.__globals__, {
                '_fstatfs_magic': lambda _fd: 0x01021994,
                '_read_proc_self_mountinfo': lambda fd: (mountinfo_calls.append(fd), '')[1],
            }):
                with self.assertRaisesRegex(script['CliError'], 'untrusted /proc filesystem magic'):
                    script['_verify_initial_pid_namespace_and_procfs'](proc_fd, proc_st)
            self.assertEqual(mountinfo_calls, [])
        finally:
            os.close(proc_fd)

        # 2. Fake /proc/self link mismatch with otherwise valid numeric witness; no numeric reads or mutation.
        real_readlink = os.readlink
        mismatch_pid = str(os.getpid() + 1)
        for bad_self in (mismatch_pid, f'0{os.getpid()}', 'not-a-pid'):
            numeric_reads: list[str] = []

            def fake_self_readlink(path, *, dir_fd=None, _bad=bad_self):
                if path == 'self' and dir_fd is not None:
                    return _bad
                return real_readlink(path) if dir_fd is None else real_readlink(path, dir_fd=dir_fd)

            with self._recovery_host_patches(cmd_recovery, db, boot_id=boot_1):
                with patch.dict(cmd_recovery.__globals__, {
                    '_read_proc_self_mountinfo': lambda _fd: (numeric_reads.append('mountinfo'), '')[1],
                    '_read_proc_self_status': lambda _fd: (numeric_reads.append('status'), '')[1],
                    '_read_proc_self_ns_pid': lambda _fd: (numeric_reads.append('ns'), ('pid:[1]', 1))[1],
                }):
                    with patch('os.readlink', side_effect=fake_self_readlink):
                        with self.assertRaisesRegex(script['CliError'], '/proc/self PID mismatch'):
                            cmd_recovery(arm_args, db)
            self.assertEqual(numeric_reads, [])

        # 3. Fake btrfs major-0 mountinfo claim paired with non-btrfs FD refuses; other FS mismatches refuse too.
        real_lstat = os.lstat
        real_fstat = os.fstat
        db_ino = db.stat().st_ino
        btrfs_subvol_dev = os.makedev(0, 99)

        def _with_dev(st: os.stat_result, dev: int) -> os.stat_result:
            return os.stat_result((
                st.st_mode, st.st_ino, dev, st.st_nlink, st.st_uid, st.st_gid,
                st.st_size, st.st_atime, st.st_mtime, st.st_ctime,
            ))

        def major_zero_lstat(path, *l_args, **l_kwargs):
            st = real_lstat(path, *l_args, **l_kwargs)
            if stat.S_ISREG(st.st_mode) and st.st_ino == db_ino:
                return _with_dev(st, btrfs_subvol_dev)
            return st

        def major_zero_fstat(fd: int):
            st = real_fstat(fd)
            if stat.S_ISREG(st.st_mode) and st.st_ino == db_ino:
                return _with_dev(st, btrfs_subvol_dev)
            return st

        with patch('os.lstat', side_effect=major_zero_lstat), patch('os.fstat', side_effect=major_zero_fstat):
            for non_btrfs_magic in (0x01021994, 0xEF53, 0x58465342):
                with self._recovery_host_patches(
                    cmd_recovery,
                    db,
                    boot_id=boot_1,
                    fs_type='btrfs',
                    ledger_dev_maj_min='0:42',
                    ledger_magic=non_btrfs_magic,
                ):
                    with self.assertRaisesRegex(script['CliError'], 'magic mismatch'):
                        cmd_recovery(arm_args, db)

        for claimed_fs, wrong_magic in (('ext4', 0x58465342), ('xfs', 0xEF53), ('f2fs', 0x01021994)):
            with self._recovery_host_patches(
                cmd_recovery,
                db,
                boot_id=boot_1,
                fs_type=claimed_fs,
                ledger_magic=wrong_magic,
            ):
                with self.assertRaisesRegex(script['CliError'], 'magic mismatch'):
                    cmd_recovery(arm_args, db)

        with closing(sqlite3.connect(f'{db.resolve().as_uri()}?mode=ro', uri=True)) as conn:
            self.assertEqual(
                conn.execute('SELECT status, exit_code, closed_at FROM writer_attempts WHERE attempt_id = ?', (att_id,)).fetchone()[:],
                ('open', None, None),
            )
            self.assertIsNone(
                conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='writer_recovery_events'").fetchone()
            )

        # Genuine /proc/self + genuine btrfs magic pass arm, with zero extra os.open calls while SQLite tx is open.
        real_open = os.open
        real_connect = sqlite3.connect
        db_resolved_str = str(db.resolve())
        sql_open_calls: list[str] = []
        tx_active = [False]

        def tracked_connect(*c_args, **c_kwargs):
            tx_active[0] = True
            return real_connect(*c_args, **c_kwargs)

        def tracked_open(path, flags, *o_args, **o_kwargs):
            if tx_active[0] and str(path) == db_resolved_str:
                sql_open_calls.append(str(path))
            return real_open(path, flags, *o_args, **o_kwargs)

        with patch('os.lstat', side_effect=major_zero_lstat), patch('os.fstat', side_effect=major_zero_fstat):
            with self._recovery_host_patches(
                cmd_recovery,
                db,
                boot_id=boot_1,
                fs_type='btrfs',
                ledger_dev_maj_min='0:42',
                ledger_magic=0x9123683E,
            ):
                with patch.object(sqlite3, 'connect', side_effect=tracked_connect):
                    with patch('os.open', side_effect=tracked_open):
                        code, armed = cmd_recovery(arm_args, db)
        self.assertEqual((code, armed['action'], armed['ledger_fs_type']), (0, 'arm', 'btrfs'))
        self.assertEqual(sql_open_calls, [])

        # Retire refuses fake /proc/self mismatch without mutation, then passes on genuine /proc/self.
        def fake_retire_readlink(path, *, dir_fd=None):
            if path == 'self' and dir_fd is not None:
                return mismatch_pid
            return real_readlink(path) if dir_fd is None else real_readlink(path, dir_fd=dir_fd)

        with patch('os.lstat', side_effect=major_zero_lstat), patch('os.fstat', side_effect=major_zero_fstat):
            with self._recovery_host_patches(
                cmd_recovery,
                db,
                boot_id=boot_2,
                fs_type='btrfs',
                ledger_dev_maj_min='0:42',
                ledger_magic=0x9123683E,
            ):
                with patch('os.readlink', side_effect=fake_retire_readlink):
                    with self.assertRaisesRegex(script['CliError'], '/proc/self PID mismatch'):
                        cmd_recovery(retire_args, db)
                with closing(sqlite3.connect(f'{db.resolve().as_uri()}?mode=ro', uri=True)) as conn:
                    self.assertEqual(
                        conn.execute('SELECT status, exit_code, closed_at FROM writer_attempts WHERE attempt_id = ?', (att_id,)).fetchone()[:],
                        ('open', None, None),
                    )
                    self.assertEqual(
                        [r[0] for r in conn.execute('SELECT action FROM writer_recovery_events WHERE attempt_id = ?', (att_id,)).fetchall()],
                        ['arm'],
                    )
                code_r, retired = cmd_recovery(retire_args, db)
                self.assertEqual((code_r, retired['status'], retired['disposition']), (0, 'closed', 'interrupted'))

    def test_writer_recovery_rejects_sibling_copied_git_pointer_and_malformed_gitdir(self) -> None:
        a, _ = self.linked_pair()
        repo_key = str((self.repo_dir / '.git').resolve())
        wt_a_admin = str((self.repo_dir / '.git' / 'worktrees' / 'task-a').resolve())
        seed = self.run_json('start', a, '--issue', 'repo-1')
        self.run_json('cancel', seed['run_id'], 'admit')

        db = self.xdg_state / 'pi-team-run' / 'state.db'
        att_id = 'wa-' + '3c' * 16
        with closing(sqlite3.connect(db)) as conn, conn:
            conn.execute(
                "INSERT INTO writer_attempts(attempt_id, repo_key, worktree, issue, bound, run_id, status, created_at) "
                "VALUES (?, ?, ?, 'repo-1', 0, NULL, 'open', '2026-11-27T09:00:00Z')",
                (att_id, repo_key, wt_a_admin),
            )

        sibling = Path(self.tmp.name) / 'sibling-copy'
        sibling.mkdir()
        (sibling / '.git').write_bytes((Path(a) / '.git').read_bytes())

        symlink_sibling = Path(self.tmp.name) / 'sibling-symlink'
        symlink_sibling.mkdir()
        (symlink_sibling / '.git').symlink_to(Path(a) / '.git')

        cli_sibling = self.run_cli(
            'writer-recovery', 'arm', att_id, '--cwd', str(sibling), '--issue', 'repo-1',
            '--unbound', '--confirm-local-ledger',
        )
        self.assertNotEqual(cli_sibling.returncode, 0)
        self.assertIn('linked git worktree', cli_sibling.stderr.lower())

        script = runpy.run_path(str(BIN_PATH))
        cmd_recovery = script['cmd_writer_recovery']
        parser = script['build_parser']()
        boot_1 = '11111111-1111-4111-8111-111111111111'

        with self._recovery_host_patches(cmd_recovery, db, boot_id=boot_1):
            for bad_cwd in (sibling, symlink_sibling):
                bad_args = parser.parse_args([
                    'writer-recovery', 'arm', att_id, '--cwd', str(bad_cwd), '--issue', 'repo-1',
                    '--unbound', '--confirm-local-ledger',
                ])
                with self.assertRaisesRegex(script['CliError'], 'linked Git worktree'):
                    cmd_recovery(bad_args, db)

            gitdir_path = Path(wt_a_admin) / 'gitdir'
            orig_gitdir = gitdir_path.read_text(encoding='utf-8')
            symlink_target = Path(self.tmp.name) / 'gitdir-link-target'
            symlink_target.write_text(orig_gitdir, encoding='utf-8')
            arm_real = parser.parse_args([
                'writer-recovery', 'arm', att_id, '--cwd', a, '--issue', 'repo-1',
                '--unbound', '--confirm-local-ledger',
            ])
            try:
                gitdir_path.unlink()
                with self.assertRaisesRegex(script['CliError'], 'gitdir backlink'):
                    cmd_recovery(arm_real, db)

                gitdir_path.symlink_to(symlink_target)
                with self.assertRaisesRegex(script['CliError'], 'gitdir backlink'):
                    cmd_recovery(arm_real, db)
                gitdir_path.unlink()

                for bad_content in ('', f'{orig_gitdir}{orig_gitdir}', f'{orig_gitdir.rstrip()}\n\n', '   \n'):
                    gitdir_path.write_text(bad_content, encoding='utf-8')
                    with self.assertRaisesRegex(script['CliError'], 'gitdir'):
                        cmd_recovery(arm_real, db)

                rel_gitdir = os.path.relpath(Path(a).resolve() / '.git', Path(wt_a_admin).resolve())
                gitdir_path.write_text(f'{rel_gitdir}\n', encoding='utf-8')
                self.assertEqual(script['scoped_worktree'](a, repo_key, 'repo-1'), wt_a_admin)
            finally:
                if gitdir_path.is_symlink() or gitdir_path.exists():
                    gitdir_path.unlink()
                gitdir_path.write_text(orig_gitdir, encoding='utf-8')

        with closing(sqlite3.connect(f'{db.resolve().as_uri()}?mode=ro', uri=True)) as conn:
            self.assertEqual(
                conn.execute('SELECT status, exit_code, closed_at FROM writer_attempts WHERE attempt_id = ?', (att_id,)).fetchone()[:],
                ('open', None, None),
            )
            self.assertIsNone(
                conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='writer_recovery_events'").fetchone()
            )

        with self._recovery_host_patches(cmd_recovery, db, boot_id=boot_1):
            code, armed = cmd_recovery(arm_real, db)
            self.assertEqual(code, 0)
            self.assertEqual(armed['action'], 'arm')
            self.assertEqual(armed['worktree'], wt_a_admin)

    def test_writer_recovery_exact_run_id_matching_long_whitespace_and_punctuation(self) -> None:
        a, b = self.linked_pair()
        repo_key = str((self.repo_dir / '.git').resolve())
        wt_a_admin = str((self.repo_dir / '.git' / 'worktrees' / 'task-a').resolve())
        wt_b_admin = str((self.repo_dir / '.git' / 'worktrees' / 'task-b').resolve())

        long_id = 'r-' + 'x' * 260
        ws_punct_id = '-run with spaces:v3 '
        self.assertGreater(len(long_id), 256)
        seed = self.run_json('start', a, '--issue', 'repo-1')
        self.run_json('cancel', seed['run_id'], 'admit')

        db = self.xdg_state / 'pi-team-run' / 'state.db'
        with closing(sqlite3.connect(db)) as conn, conn:
            conn.execute(
                "INSERT INTO runs(run_id, repo_key, issue, worktree, status, current_stage, created_at, updated_at) "
                "VALUES (?, ?, 'repo-1', ?, 'active', 'implement', '2026-11-27T09:00:00Z', '2026-11-27T09:00:00Z')",
                (long_id, repo_key, wt_a_admin),
            )
            conn.execute(
                "INSERT INTO runs(run_id, repo_key, issue, worktree, status, current_stage, created_at, updated_at) "
                "VALUES (?, ?, 'repo-2', ?, 'active', 'implement', '2026-11-27T09:05:00Z', '2026-11-27T09:05:00Z')",
                (ws_punct_id, repo_key, wt_b_admin),
            )
        att_long = 'wa-' + '4d' * 16
        att_ws = 'wa-' + '5e' * 16
        with closing(sqlite3.connect(db)) as conn, conn:
            conn.execute(
                "INSERT INTO writer_attempts(attempt_id, repo_key, worktree, issue, bound, run_id, status, created_at) "
                "VALUES (?, ?, ?, 'repo-1', 1, ?, 'open', '2026-11-27T09:00:00Z')",
                (att_long, repo_key, wt_a_admin, long_id),
            )
            conn.execute(
                "INSERT INTO writer_attempts(attempt_id, repo_key, worktree, issue, bound, run_id, status, created_at) "
                "VALUES (?, ?, ?, 'repo-2', 1, ?, 'open', '2026-11-27T09:05:00Z')",
                (att_ws, repo_key, wt_b_admin, ws_punct_id),
            )

        script = runpy.run_path(str(BIN_PATH))
        cmd_recovery = script['cmd_writer_recovery']
        parser = script['build_parser']()
        boot_1 = '11111111-1111-4111-8111-111111111111'
        boot_2 = '22222222-2222-4222-8222-222222222222'

        with self._recovery_host_patches(cmd_recovery, db, boot_id=boot_1):
            for bad_run_flag in ('--run-id=', f'--run-id= {long_id}', f'--run-id={long_id} ', f'--run-id={long_id}\n'):
                with self.assertRaises(script['CliError']):
                    cmd_recovery(parser.parse_args([
                        'writer-recovery', 'arm', att_long, '--cwd', a, '--issue', 'repo-1',
                        bad_run_flag, '--confirm-local-ledger',
                    ]), db)
            with self.assertRaises(script['CliError']):
                cmd_recovery(parser.parse_args([
                    'writer-recovery', 'arm', att_ws, '--cwd', b, '--issue', 'repo-2',
                    f'--run-id={ws_punct_id.strip()}', '--confirm-local-ledger',
                ]), db)

            with closing(sqlite3.connect(f'{db.resolve().as_uri()}?mode=ro', uri=True)) as conn:
                self.assertIsNone(
                    conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='writer_recovery_events'").fetchone()
                )

            code_l, armed_l = cmd_recovery(parser.parse_args([
                'writer-recovery', 'arm', att_long, '--cwd', a, '--issue', 'repo-1',
                f'--run-id={long_id}', '--confirm-local-ledger',
            ]), db)
            self.assertEqual((code_l, armed_l['run_id']), (0, long_id))

            code_w, armed_w = cmd_recovery(parser.parse_args([
                'writer-recovery', 'arm', att_ws, '--cwd', b, '--issue', 'repo-2',
                f'--run-id={ws_punct_id}', '--confirm-local-ledger',
            ]), db)
            self.assertEqual((code_w, armed_w['run_id']), (0, ws_punct_id))

        with self._recovery_host_patches(cmd_recovery, db, boot_id=boot_2):
            code_rl, retired_l = cmd_recovery(parser.parse_args([
                'writer-recovery', 'retire', att_long, '--cwd', a, '--issue', 'repo-1',
                f'--run-id={long_id}', '--confirm-local-ledger',
            ]), db)
            self.assertEqual((code_rl, retired_l['status'], retired_l['run_id']), (0, 'closed', long_id))

            code_rw, retired_w = cmd_recovery(parser.parse_args([
                'writer-recovery', 'retire', att_ws, '--cwd', b, '--issue', 'repo-2',
                f'--run-id={ws_punct_id}', '--confirm-local-ledger',
            ]), db)
            self.assertEqual((code_rw, retired_w['status'], retired_w['run_id']), (0, 'closed', ws_punct_id))

    def test_writer_recovery_rejects_outer_whitespace_xdg_state_home_before_evidence_and_db(self) -> None:
        a, b = self.linked_pair()
        repo_key = str((self.repo_dir / '.git').resolve())
        wt_a_admin = str((self.repo_dir / '.git' / 'worktrees' / 'task-a').resolve())
        wt_b_admin = str((self.repo_dir / '.git' / 'worktrees' / 'task-b').resolve())

        trimmed_xdg = Path(self.tmp.name) / 'trimmed-xdg'
        trimmed_db = trimmed_xdg / 'pi-team-run' / 'state.db'
        test_home = Path(self.tmp.name) / 'test-home'
        test_home.mkdir()
        default_db = test_home / '.local' / 'state' / 'pi-team-run' / 'state.db'

        script = runpy.run_path(str(BIN_PATH))
        cmd_recovery = script['cmd_writer_recovery']
        parser = script['build_parser']()
        boot_1 = '11111111-1111-4111-8111-111111111111'

        att_arm = 'wa-' + '6a' * 16
        att_retire = 'wa-' + '6b' * 16
        base_env = {k: v for k, v in self.env.items() if k != 'XDG_STATE_HOME'}
        fixtures = [
            (trimmed_db, {**base_env, 'HOME': str(test_home), 'XDG_STATE_HOME': str(trimmed_xdg)}),
            (default_db, {**base_env, 'HOME': str(test_home)}),
        ]
        run_b_by_db: dict[Path, str] = {}
        for db_file, f_env in fixtures:
            s_a = subprocess.run(
                [sys.executable, str(BIN_PATH), 'start', a, '--issue', 'repo-1', '--json'],
                env=f_env, text=True, capture_output=True, check=True,
            )
            run_a = json.loads(s_a.stdout)['run_id']
            subprocess.run(
                [sys.executable, str(BIN_PATH), 'cancel', run_a, 'admit', '--json'],
                env=f_env, text=True, capture_output=True, check=True,
            )
            s_b = subprocess.run(
                [sys.executable, str(BIN_PATH), 'start', b, '--issue', 'repo-2', '--json'],
                env=f_env, text=True, capture_output=True, check=True,
            )
            run_b = json.loads(s_b.stdout)['run_id']
            run_b_by_db[db_file] = run_b

            with closing(sqlite3.connect(db_file)) as conn, conn:
                conn.execute(
                    "INSERT INTO writer_attempts(attempt_id, repo_key, worktree, issue, bound, run_id, status, created_at) "
                    "VALUES (?, ?, ?, 'repo-1', 0, NULL, 'open', '2026-11-27T09:00:00Z')",
                    (att_arm, repo_key, wt_a_admin),
                )
                conn.execute(
                    "INSERT INTO writer_attempts(attempt_id, repo_key, worktree, issue, bound, run_id, status, created_at) "
                    "VALUES (?, ?, ?, 'repo-2', 1, ?, 'open', '2026-11-27T09:05:00Z')",
                    (att_retire, repo_key, wt_b_admin, run_b),
                )

            with self._recovery_host_patches(cmd_recovery, db_file, boot_id=boot_1):
                code, armed = cmd_recovery(parser.parse_args([
                    'writer-recovery', 'arm', att_retire, '--cwd', b, '--issue', 'repo-2',
                    '--run-id', run_b, '--confirm-local-ledger',
                ]), db_file)
                self.assertEqual((code, armed['action']), (0, 'arm'))

            self.assertTrue(db_file.is_file())
            with closing(sqlite3.connect(f'{db_file.resolve().as_uri()}?mode=ro', uri=True)) as conn:
                self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0], 4)
                self.assertEqual(
                    conn.execute('SELECT status, exit_code, closed_at FROM writer_attempts WHERE attempt_id = ?', (att_arm,)).fetchone()[:],
                    ('open', None, None),
                )
                self.assertEqual(
                    conn.execute('SELECT status, exit_code, closed_at FROM writer_attempts WHERE attempt_id = ?', (att_retire,)).fetchone()[:],
                    ('open', None, None),
                )
                self.assertEqual(
                    [r[0] for r in conn.execute('SELECT action FROM writer_recovery_events WHERE attempt_id = ?', (att_retire,)).fetchall()],
                    ['arm'],
                )

        norm_repo = Path(self.tmp.name) / 'norm-repo'
        ws_repo = Path(self.tmp.name) / 'ws-repo'
        norm_repo.mkdir()
        ws_repo.mkdir()
        norm_start = subprocess.run(
            [sys.executable, str(BIN_PATH), 'start', str(norm_repo), '--json'],
            env={**base_env, 'HOME': str(test_home), 'XDG_STATE_HOME': f' {trimmed_xdg} '},
            text=True, capture_output=True, check=False,
        )
        self.assertEqual(norm_start.returncode, 0, msg=norm_start.stderr)
        ws_start = subprocess.run(
            [sys.executable, str(BIN_PATH), 'start', str(ws_repo), '--json'],
            env={**base_env, 'HOME': str(test_home), 'XDG_STATE_HOME': '   '},
            text=True, capture_output=True, check=False,
        )
        self.assertEqual(ws_start.returncode, 0, msg=ws_start.stderr)

        bad_xdg_values = (
            (f' {trimmed_xdg}', trimmed_db),
            (f'{trimmed_xdg} ', trimmed_db),
            (f' {trimmed_xdg} ', trimmed_db),
            (f'\t{trimmed_xdg}\n', trimmed_db),
            (' ', default_db),
            ('\t', default_db),
            ('  \n', default_db),
        )
        for bad_xdg, target_db in bad_xdg_values:
            bad_env = {**base_env, 'HOME': str(test_home), 'XDG_STATE_HOME': bad_xdg}
            run_b = run_b_by_db[target_db]
            cli_cases = (
                ['writer-recovery', 'arm', att_arm, '--cwd', a, '--issue', 'repo-1', '--unbound', '--confirm-local-ledger'],
                ['writer-recovery', 'retire', att_retire, '--cwd', b, '--issue', 'repo-2', '--run-id', run_b, '--confirm-local-ledger'],
                ['writer-recovery', 'status', att_arm],
            )
            for argv in cli_cases:
                with self.subTest(bad_xdg=bad_xdg, action=argv[1]):
                    proc = subprocess.run(
                        [sys.executable, str(BIN_PATH), *argv],
                        env=bad_env, text=True, capture_output=True, check=False,
                    )
                    self.assertNotEqual(proc.returncode, 0)
                    self.assertIn('xdg_state_home', proc.stderr.lower())
                    self.assertIn('surrounding whitespace', proc.stderr.lower())
                    self.assertNotIn('missing', proc.stderr.lower())
                    self.assertNotIn('not an allowed local durable filesystem', proc.stderr.lower())

        calls: list[str] = []

        def fail_if_called(name: str):
            def _boom(*_args, **_kwargs):
                calls.append(name)
                raise AssertionError(f'{name} must not run when XDG_STATE_HOME has outer whitespace')
            return _boom

        with patch.dict(os.environ, {'HOME': str(test_home), 'XDG_STATE_HOME': f' {trimmed_xdg} '}):
            with patch.dict(script['main'].__globals__, {
                'resolve_state_db_path': fail_if_called('resolve_state_db_path'),
                '_open_pinned_proc_root': fail_if_called('_open_pinned_proc_root'),
                '_read_machine_id_raw': fail_if_called('_read_machine_id_raw'),
            }):
                with patch('sqlite3.connect', side_effect=fail_if_called('sqlite3.connect')):
                    for argv in (
                        ['writer-recovery', 'arm', att_arm, '--cwd', a, '--issue', 'repo-1', '--unbound', '--confirm-local-ledger'],
                        ['writer-recovery', 'retire', att_retire, '--cwd', b, '--issue', 'repo-2', '--run-id', run_b_by_db[trimmed_db], '--confirm-local-ledger'],
                        ['writer-recovery', 'status', att_arm],
                    ):
                        err_buf = io.StringIO()
                        with patch('sys.stderr', err_buf):
                            rc = script['main'](argv)
                        self.assertEqual(rc, 1)
                        self.assertIn('surrounding whitespace', err_buf.getvalue().lower())
                        with self.assertRaisesRegex(script['CliError'], 'surrounding whitespace'):
                            cmd_recovery(parser.parse_args(argv), trimmed_db)
        self.assertEqual(calls, [])

        for db_file, _ in fixtures:
            with closing(sqlite3.connect(f'{db_file.resolve().as_uri()}?mode=ro', uri=True)) as conn:
                self.assertEqual(
                    conn.execute('SELECT status, exit_code, closed_at FROM writer_attempts WHERE attempt_id = ?', (att_arm,)).fetchone()[:],
                    ('open', None, None),
                )
                self.assertEqual(
                    conn.execute('SELECT count(*) FROM writer_recovery_events WHERE attempt_id = ?', (att_arm,)).fetchone()[0],
                    0,
                )
                self.assertEqual(
                    conn.execute('SELECT status, exit_code, closed_at FROM writer_attempts WHERE attempt_id = ?', (att_retire,)).fetchone()[:],
                    ('open', None, None),
                )
                self.assertEqual(
                    [r[0] for r in conn.execute('SELECT action FROM writer_recovery_events WHERE attempt_id = ?', (att_retire,)).fetchall()],
                    ['arm'],
                )

    def test_writer_recovery_machine_id_fd_complete_read_overflow_and_canonical_validation(self) -> None:
        a, _ = self.linked_pair()
        repo_key = str((self.repo_dir / '.git').resolve())
        wt_a_admin = str((self.repo_dir / '.git' / 'worktrees' / 'task-a').resolve())
        seed = self.run_json('start', a, '--issue', 'repo-1')
        self.run_json('cancel', seed['run_id'], 'admit')

        db = self.xdg_state / 'pi-team-run' / 'state.db'
        att_id = 'wa-' + '7b' * 16
        with closing(sqlite3.connect(db)) as conn, conn:
            conn.execute(
                "INSERT INTO writer_attempts(attempt_id, repo_key, worktree, issue, bound, run_id, status, created_at) "
                "VALUES (?, ?, ?, 'repo-1', 0, NULL, 'open', '2026-11-27T09:00:00Z')",
                (att_id, repo_key, wt_a_admin),
            )

        mid_dir = Path(self.tmp.name) / 'machine-ids'
        mid_dir.mkdir()
        id_1 = '1' * 32
        id_2 = '2' * 32

        def write_mid(name: str, payload: bytes) -> Path:
            p = mid_dir / name
            p.write_bytes(payload)
            return p

        valid_nl = write_mid('valid-nl', (id_1 + '\n').encode('ascii'))
        valid_no_nl = write_mid('valid-no-nl', id_2.encode('ascii'))
        overflow_ws_second = write_mid('overflow-ws-second', (id_1 + ' ' * 100 + id_2 + '\n').encode('ascii'))
        within_cap_ws_second = write_mid('within-cap-ws-second', (id_1 + ' ' * 10 + id_2 + '\n').encode('ascii'))
        non_utf8 = write_mid('non-utf8', b'\xff' * 32 + b'\n')
        bad_payloads = [
            ('leading-space', (' ' + id_1 + '\n').encode('ascii')),
            ('trailing-space-nl', (id_1 + ' \n').encode('ascii')),
            ('trailing-space', (id_1 + ' ').encode('ascii')),
            ('trailing-tab', (id_1 + '\t').encode('ascii')),
            ('crlf', (id_1 + '\r\n').encode('ascii')),
            ('double-nl', (id_1 + '\n\n').encode('ascii')),
            ('nl-space', (id_1 + '\n ').encode('ascii')),
            ('two-lines', (id_1 + '\n' + id_2 + '\n').encode('ascii')),
            ('all-zero', ('0' * 32 + '\n').encode('ascii')),
            ('uppercase', ('A' * 32 + '\n').encode('ascii')),
        ]
        bad_files = [(name, write_mid(name, data)) for name, data in bad_payloads]

        script = runpy.run_path(str(BIN_PATH))
        read_mid_fd = script['_read_machine_id_fd']
        real_read_mid_raw = script['_read_machine_id_raw']
        cmd_recovery = script['cmd_writer_recovery']
        parser = script['build_parser']()

        self.assertEqual(read_mid_fd(os.open(valid_nl, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)), id_1)
        self.assertEqual(read_mid_fd(os.open(valid_no_nl, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)), id_2)

        real_os_read = os.read
        with patch('os.read', side_effect=lambda fd, n: real_os_read(fd, min(n, 7))):
            self.assertEqual(read_mid_fd(os.open(valid_nl, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)), id_1)
            with self.assertRaisesRegex(script['CliError'], 'exceeded 128 bytes'):
                read_mid_fd(os.open(overflow_ws_second, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC))

        with self.assertRaisesRegex(script['CliError'], 'exceeded 128 bytes'):
            read_mid_fd(os.open(overflow_ws_second, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC))
        with self.assertRaisesRegex(script['CliError'], 'invalid or zero /etc/machine-id'):
            read_mid_fd(os.open(within_cap_ws_second, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC))
        with self.assertRaisesRegex(script['CliError'], 'not valid UTF-8'):
            read_mid_fd(os.open(non_utf8, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC))
        for name, bad_path in bad_files:
            with self.subTest(bad_machine_id=name):
                with self.assertRaisesRegex(script['CliError'], 'invalid or zero /etc/machine-id'):
                    read_mid_fd(os.open(bad_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC))

        r_fd, w_fd = os.pipe()
        try:
            with self.assertRaisesRegex(script['CliError'], 'regular file'):
                read_mid_fd(r_fd)
        finally:
            os.close(w_fd)

        for invalid_val in ('0' * 32, id_1 + '\n', '1' * 31, 123):
            with self.assertRaisesRegex(script['CliError'], 'invalid or zero /etc/machine-id'):
                script['_validate_machine_id'](invalid_val)
            with self.assertRaisesRegex(script['CliError'], 'invalid or zero /etc/machine-id'):
                script['_hash_machine_id'](invalid_val)

        boot_1 = '11111111-1111-4111-8111-111111111111'
        boot_2 = '22222222-2222-4222-8222-222222222222'
        arm_args = parser.parse_args([
            'writer-recovery', 'arm', att_id, '--cwd', a, '--issue', 'repo-1',
            '--unbound', '--confirm-local-ledger',
        ])
        retire_args = parser.parse_args([
            'writer-recovery', 'retire', att_id, '--cwd', a, '--issue', 'repo-1',
            '--unbound', '--confirm-local-ledger',
        ])

        def open_temp_mid(path: Path):
            return lambda: os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)

        with self._recovery_host_patches(cmd_recovery, db, boot_id=boot_1):
            for bad_path in (overflow_ws_second, within_cap_ws_second, bad_files[1][1]):
                with patch.dict(cmd_recovery.__globals__, {
                    '_read_machine_id_raw': real_read_mid_raw,
                    '_open_machine_id_fd': open_temp_mid(bad_path),
                }):
                    with self.assertRaises(script['CliError']):
                        cmd_recovery(arm_args, db)

            with closing(sqlite3.connect(f'{db.resolve().as_uri()}?mode=ro', uri=True)) as conn:
                self.assertIsNone(
                    conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='writer_recovery_events'").fetchone()
                )
                self.assertEqual(
                    conn.execute('SELECT status, exit_code, closed_at FROM writer_attempts WHERE attempt_id = ?', (att_id,)).fetchone()[:],
                    ('open', None, None),
                )

            with patch.dict(cmd_recovery.__globals__, {
                '_read_machine_id_raw': real_read_mid_raw,
                '_open_machine_id_fd': open_temp_mid(valid_nl),
            }):
                with patch('os.read', side_effect=lambda fd, n: real_os_read(fd, min(n, 7))):
                    code_arm, armed = cmd_recovery(arm_args, db)
            self.assertEqual((code_arm, armed['action']), (0, 'arm'))

        with self._recovery_host_patches(cmd_recovery, db, boot_id=boot_2):
            for bad_path in (overflow_ws_second, within_cap_ws_second, bad_files[4][1]):
                with patch.dict(cmd_recovery.__globals__, {
                    '_read_machine_id_raw': real_read_mid_raw,
                    '_open_machine_id_fd': open_temp_mid(bad_path),
                }):
                    with self.assertRaises(script['CliError']):
                        cmd_recovery(retire_args, db)

            with closing(sqlite3.connect(f'{db.resolve().as_uri()}?mode=ro', uri=True)) as conn:
                self.assertEqual(
                    conn.execute('SELECT status, exit_code, closed_at FROM writer_attempts WHERE attempt_id = ?', (att_id,)).fetchone()[:],
                    ('open', None, None),
                )
                self.assertEqual(
                    [r[0] for r in conn.execute('SELECT action FROM writer_recovery_events WHERE attempt_id = ?', (att_id,)).fetchall()],
                    ['arm'],
                )

            with patch.dict(cmd_recovery.__globals__, {
                '_read_machine_id_raw': real_read_mid_raw,
                '_open_machine_id_fd': open_temp_mid(valid_nl),
            }):
                code_retire, retired = cmd_recovery(retire_args, db)
            self.assertEqual((code_retire, retired['status'], retired['disposition']), (0, 'closed', 'interrupted'))
            self.assertIsNone(retired['exit_code'])

    def test_v3_writer_recovery_transactions_and_status_preserve_schema(self) -> None:
        db = self.xdg_state / 'pi-team-run' / 'state.db'
        db.parent.mkdir(parents=True)
        script = runpy.run_path(str(BIN_PATH))
        attempt_id = 'wa-' + '31' * 16
        with closing(sqlite3.connect(db)) as conn, conn:
            for stmt in (*script['V1_SCHEMA'], *script['V2_MIGRATION'], *script['V3_MIGRATION']):
                conn.execute(stmt)
            conn.execute('PRAGMA user_version = 3')
            conn.execute(
                "INSERT INTO writer_attempts(attempt_id,repo_key,worktree,issue,bound,run_id,status,created_at) "
                "VALUES (?, '/repo/.git', '/repo/.git/worktrees/task', 'repo-1', 0, NULL, 'open', 'now')",
                (attempt_id,),
            )
        db.chmod(0o600)
        recovery_tx = script['_open_recovery_write_tx']
        with patch.dict(recovery_tx.__wrapped__.__globals__, {'_verify_pinned_ledger_under_tx': lambda *_: None}):
            with recovery_tx(db, {'ledger_path': str(db)}) as conn:
                self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0], 3)
                self.assertEqual(conn.execute('SELECT status FROM writer_attempts').fetchone()[0], 'open')
        status = script['cmd_writer_recovery_status']
        args = script['build_parser']().parse_args(['writer-recovery', 'status', attempt_id])
        with patch.dict(status.__globals__, {'_validate_recovery_xdg_state_home': lambda: None}):
            code, result = status(args, db)
        self.assertEqual((code, result['status']), (0, 'open'))
        with closing(sqlite3.connect(db)) as conn:
            self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0], 3)
            self.assertNotIn('local_only', {row[1] for row in conn.execute('PRAGMA table_info(runs)')})

    def test_v3_read_only_stays_v3_preserves_legacy_ids_and_migrates_to_v4_on_write(self) -> None:
        a, b = self.linked_pair()
        repo_key = str((self.repo_dir / '.git').resolve())
        wt_a_admin = str((self.repo_dir / '.git' / 'worktrees' / 'task-a').resolve())
        db = self.xdg_state / 'pi-team-run' / 'state.db'
        db.parent.mkdir(parents=True)
        script = runpy.run_path(str(BIN_PATH))
        with closing(sqlite3.connect(db)) as conn, conn:
            for stmt in (*script['V1_SCHEMA'], *script['V2_MIGRATION'], *script['V3_MIGRATION']):
                conn.execute(stmt)
            conn.execute('PRAGMA user_version = 3')
            conn.execute(
                "INSERT INTO runs(run_id,repo_key,issue,worktree,status,current_stage,created_at,updated_at) "
                "VALUES ('_legacy:id/1', ?, 'repo-1', ?, 'active', 'implement', 'now', 'now')",
                (repo_key, wt_a_admin),
            )
            conn.execute(
                "INSERT INTO checkpoints(run_id,stage,disposition,evidence,rev,note,created_at) "
                "VALUES ('_legacy:id/1', 'admit', 'completed', 'ev:admit', NULL, NULL, 'now')"
            )
            conn.execute(
                "INSERT INTO writer_attempts(attempt_id,repo_key,worktree,issue,bound,run_id,status,exit_code,created_at,closed_at) "
                "VALUES ('wa-hist-1', ?, ?, 'repo-1', 1, '_legacy:id/1', 'closed', 0, 'now', 'now')",
                (repo_key, wt_a_admin),
            )

        status_before = self.run_json('status', '_legacy:id/1')
        self.assertEqual(status_before['run_id'], '_legacy:id/1')
        self.assertFalse(status_before['local_only'])
        self.assertEqual(status_before['last_writer_attempt']['attempt_id'], 'wa-hist-1')
        self.assertEqual(self.run_json('resume', '_legacy:id/1')['action'], 'checkpoint')
        self.assertEqual(self.run_json('discover', b)[0]['run_id'], '_legacy:id/1')
        with closing(sqlite3.connect(db)) as conn:
            self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0], 3)
            cols = {row[1] for row in conn.execute('PRAGMA table_info(runs)').fetchall()}
            self.assertNotIn('local_only', cols)

        second = self.run_json('start', b, '--issue', 'repo-2')
        self.assertFalse(second['local_only'])
        with closing(sqlite3.connect(db)) as conn:
            self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0], 4)
            row = conn.execute("SELECT local_only FROM runs WHERE run_id = '_legacy:id/1'").fetchone()
            self.assertEqual(row[0], 0)
            ckpt = conn.execute(
                "SELECT writer_attempt_id, check_checkpoint_id FROM checkpoints WHERE run_id = '_legacy:id/1'"
            ).fetchone()
            self.assertEqual(tuple(ckpt), (None, None))

    def test_run_id_grammar_and_local_only_start_validation(self) -> None:
        a, b = self.linked_pair()
        validate_run_id = runpy.run_path(str(BIN_PATH))['validate_run_id']
        bad_ids = [
            '',
            ' ',
            ' run-1',
            'run-1 ',
            'run-1\n',
            'run-1\t',
            'run-\u00e9',
            '-run',
            '.run',
            '_run',
            'a' * 129,
        ]
        for bad_id in bad_ids:
            with self.assertRaisesRegex(Exception, 'run ID must be 1-128 ASCII'):
                validate_run_id(bad_id)

        for bad_id in bad_ids:
            proc = self.run_cli('start', a, '--issue', 'repo-1', f'--run-id={bad_id}')
            self.assertNotEqual(proc.returncode, 0, msg=f'unexpectedly accepted run_id={bad_id!r}')
            self.assertIn('run id must be 1-128 ascii', proc.stderr.lower())

        for bad_id in bad_ids:
            proc = self.run_cli(
                'writer-exec', '--cwd', a, '--issue', 'repo-1', f'--run-id={bad_id}', '--',
                '/usr/bin/bwrap', '--unshare-pid', '--die-with-parent', '--ro-bind', '/', '/',
                '--bind', a, a, '--dev', '/dev', '--proc', '/proc', '--', '/bin/true',
            )
            self.assertNotEqual(proc.returncode, 0, msg=f'writer-exec accepted run_id={bad_id!r}')
            self.assertIn('run id must be 1-128 ascii', proc.stderr.lower())

        self.assertNotEqual(self.run_cli('start', a, '--local-only').returncode, 0)
        self.assertNotEqual(self.run_cli('start', str(self.repo_dir), '--local-only', '--issue', 'repo-1').returncode, 0)
        for bad_flag in ('--commit-only', '--no-ci', '--with-deploy', '--with-honcho', '--with-wiki'):
            bad = self.run_cli('start', a, '--local-only', '--issue', 'repo-1', bad_flag)
            self.assertNotEqual(bad.returncode, 0, msg=f'unexpectedly accepted {bad_flag} with --local-only')
            self.assertIn('--local-only', bad.stderr)

        max_id = 'A' + '0._-' * 31 + 'abc'
        self.assertEqual(len(max_id), 128)
        self.assertEqual(validate_run_id(max_id), max_id)
        self.assertEqual(validate_run_id('z'), 'z')
        started = self.run_json('start', a, '--local-only', '--issue', 'repo-1', '--run-id', max_id)
        self.assertTrue(started['local_only'])
        self.assertEqual(started['run_id'], max_id)
        self.assertEqual(started['active_stages'], ['admit', 'implement', 'check', 'review'])
        self.assertEqual(self.run_json('status', max_id)['local_only'], True)

        min_id_run = self.run_json('start', b, '--local-only', '--issue', 'repo-2', '--run-id', 'z')
        self.assertEqual(min_id_run['run_id'], 'z')

    def test_local_only_check_and_review_negative_controls_and_terminal_completion(self) -> None:
        a, b = self.linked_pair()
        repo_key = str((self.repo_dir / '.git').resolve())
        wt_a_admin = str((self.repo_dir / '.git' / 'worktrees' / 'task-a').resolve())
        wt_b_admin = str((self.repo_dir / '.git' / 'worktrees' / 'task-b').resolve())
        digest_a = 'A' * 64
        digest_b = 'b' * 64
        sha40 = 'c' * 40

        run_id = 'local-only-run-1'
        self.run_json('start', a, '--local-only', '--issue', 'repo-1', '--run-id', run_id)
        parallel = self.run_json('start', b, '--local-only', '--issue', 'repo-2', '--run-id', 'local-only-run-2')
        self.assertEqual(parallel['status'], 'active')

        self.run_json('checkpoint', run_id, 'admit', '--evidence', 'ev:admit')
        self.run_json('checkpoint', run_id, 'implement', '--evidence', 'ev:impl')
        self.assertEqual(self.run_json('resume', run_id)['action'], 'checkpoint')

        self.assertNotEqual(self.run_cli('checkpoint', run_id, 'check', '--evidence', 'ev:check').returncode, 0)
        self.assertNotEqual(self.run_cli('checkpoint', run_id, 'check', '--rev', sha40, '--evidence', 'ev:check').returncode, 0)
        self.assertNotEqual(self.run_cli('checkpoint', run_id, 'check', '--rev', digest_a, '--evidence', 'ev:check').returncode, 0)

        db = self.xdg_state / 'pi-team-run' / 'state.db'
        with closing(sqlite3.connect(str(db))) as conn, conn:
            conn.execute(
                "INSERT INTO writer_attempts(attempt_id,repo_key,worktree,issue,bound,run_id,status,exit_code,created_at,closed_at) "
                "VALUES ('wa-open-1', ?, ?, 'repo-1', 1, ?, 'open', NULL, '2026-01-01T00:00:00Z', NULL)",
                (repo_key, wt_a_admin, run_id),
            )
            conn.execute(
                "INSERT INTO writer_attempts(attempt_id,repo_key,worktree,issue,bound,run_id,status,exit_code,created_at,closed_at) "
                "VALUES ('wa-parallel-open', ?, ?, 'repo-2', 1, 'local-only-run-2', 'open', NULL, '2026-01-01T00:00:00Z', NULL)",
                (repo_key, wt_b_admin),
            )
        self.assertIn('open writer attempt', self.run_cli('checkpoint', run_id, 'check', '--rev', digest_a, '--evidence', 'ev:check').stderr.lower())

        with closing(sqlite3.connect(str(db))) as conn, conn:
            conn.execute(
                "UPDATE writer_attempts SET status = 'closed', exit_code = 1, closed_at = '2026-01-01T00:00:05Z' "
                "WHERE attempt_id = 'wa-open-1'"
            )
        self.assertIn('expected 0', self.run_cli('checkpoint', run_id, 'check', '--rev', digest_a, '--evidence', 'ev:check').stderr.lower())

        with closing(sqlite3.connect(str(db))) as conn, conn:
            conn.execute(
                "INSERT INTO writer_attempts(attempt_id,repo_key,worktree,issue,bound,run_id,status,exit_code,created_at,closed_at) "
                "VALUES ('wa-11111111111111111111111111111111', ?, ?, 'repo-1', 1, ?, 'closed', 0, '2026-01-01T00:01:00Z', '2026-01-01T00:01:05Z')",
                (repo_key, wt_a_admin, run_id),
            )

        self.assertIn('--writer-attempt', self.run_json('resume', run_id)['message'])
        self.assertNotEqual(self.run_cli('checkpoint', run_id, 'check', '--rev', digest_a, '--writer-attempt', 'bad-id', '--evidence', 'check:pass:1').returncode, 0)
        checked = self.run_json('checkpoint', run_id, 'check', '--rev', digest_a, '--writer-attempt', 'wa-11111111111111111111111111111111', '--evidence', 'check:pass:1')
        self.assertEqual(checked['current_stage'], 'review')
        self.assertEqual(checked['checkpoints'][-1]['rev'], digest_a.lower())
        self.assertEqual(checked['checkpoints'][-1]['writer_attempt_id'], 'wa-11111111111111111111111111111111')
        self.assertEqual(checked['last_writer_attempt']['attempt_id'], 'wa-11111111111111111111111111111111')

        self.run_json('reserve', run_id, 'review')
        self.run_json('wait', run_id, 'review', '--target', 'coordinator', '--reason', 'independent review')
        self.assertIn('review:pass:<locator>', self.run_json('resume', run_id)['message'])

        for bad_args in (
            ['--evidence', 'review:pass:loc-1'],
            ['--rev', sha40, '--evidence', 'review:pass:loc-1'],
            ['--rev', digest_b, '--evidence', 'review:pass:loc-1'],
            ['--rev', digest_a.lower(), '--evidence', 'ev:review'],
            ['--rev', digest_a.lower(), '--evidence', 'review:pass:'],
            ['--rev', digest_a.lower(), '--evidence', 'review:pass:   '],
            ['--rev', digest_a.lower(), '--evidence', 'review:fail:loc-1'],
        ):
            bad = self.run_cli('checkpoint', run_id, 'review', *bad_args)
            self.assertNotEqual(bad.returncode, 0, msg=f'unexpectedly accepted review args={bad_args}')
            still = self.run_json('status', run_id)
            self.assertEqual(still['status'], 'waiting')
            self.assertTrue(still['reserved'])
            self.assertIsNotNone(still['active_wait'])

        with closing(sqlite3.connect(str(db))) as conn, conn:
            conn.execute(
                "INSERT INTO writer_attempts(attempt_id,repo_key,worktree,issue,bound,run_id,status,exit_code,created_at,closed_at) "
                "VALUES ('wa-22222222222222222222222222222222', ?, ?, 'repo-1', 1, ?, 'closed', 0, '2026-01-01T00:02:00Z', '2026-01-01T00:02:05Z')",
                (repo_key, wt_a_admin, run_id),
            )
        stale_review = self.run_cli('checkpoint', run_id, 'review', '--rev', digest_a.lower(), '--evidence', 'review:pass:loc-1')
        self.assertNotEqual(stale_review.returncode, 0)
        self.assertIn('stale check checkpoint', stale_review.stderr.lower())
        still_after_newer = self.run_json('status', run_id)
        self.assertEqual(still_after_newer['status'], 'waiting')
        self.assertTrue(still_after_newer['reserved'])
        self.assertIsNotNone(still_after_newer['active_wait'])

        with closing(sqlite3.connect(str(db))) as conn, conn:
            conn.execute("DELETE FROM writer_attempts WHERE attempt_id = 'wa-22222222222222222222222222222222'")

        done = self.run_json('checkpoint', run_id, 'review', '--rev', digest_a.lower(), '--evidence', 'review:pass:loc-1')
        self.assertEqual(done['status'], 'completed')
        self.assertIsNone(done['current_stage'])
        self.assertFalse(done['reserved'])
        self.assertIsNone(done['active_wait'])
        self.assertEqual(done['checkpoints'][-1]['writer_attempt_id'], 'wa-11111111111111111111111111111111')
        self.assertIsInstance(done['checkpoints'][-1]['check_checkpoint_id'], int)
        self.assertEqual(self.run_json('status', 'local-only-run-2')['status'], 'active')

        with closing(sqlite3.connect(str(db))) as conn, conn:
            conn.execute(
                "UPDATE writer_attempts SET status = 'closed', exit_code = 0, closed_at = 'now' "
                "WHERE attempt_id = 'wa-parallel-open'"
            )
        self.run_json('cancel', 'local-only-run-2', 'admit')


    def test_local_only_check_rejects_missing_or_stale_writer_attempt_race(self) -> None:
        a, _ = self.linked_pair()
        repo_key = str((self.repo_dir / '.git').resolve())
        wt_a_admin = str((self.repo_dir / '.git' / 'worktrees' / 'task-a').resolve())
        digest_a = 'a' * 64
        run_id = 'local-race-cli-1'

        self.run_json('start', a, '--local-only', '--issue', 'repo-1', '--run-id', run_id)
        self.run_json('checkpoint', run_id, 'admit', '--evidence', 'ev:admit')
        self.run_json('checkpoint', run_id, 'implement', '--evidence', 'ev:impl')

        db = self.xdg_state / 'pi-team-run' / 'state.db'
        with closing(sqlite3.connect(str(db))) as conn, conn:
            conn.execute(
                "INSERT INTO writer_attempts(attempt_id,repo_key,worktree,issue,bound,run_id,status,exit_code,created_at,closed_at) "
                "VALUES ('wa-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', ?, ?, 'repo-1', 1, ?, 'closed', 0, '2026-01-01T00:01:00Z', '2026-01-01T00:01:05Z')",
                (repo_key, wt_a_admin, run_id),
            )
            conn.execute(
                "INSERT INTO writer_attempts(attempt_id,repo_key,worktree,issue,bound,run_id,status,exit_code,created_at,closed_at) "
                "VALUES ('wa-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb', ?, ?, 'repo-1', 1, ?, 'closed', 0, '2026-01-01T00:02:00Z', '2026-01-01T00:02:05Z')",
                (repo_key, wt_a_admin, run_id),
            )

        missing = self.run_cli('checkpoint', run_id, 'check', '--rev', digest_a, '--evidence', 'check:pass:1')
        self.assertNotEqual(missing.returncode, 0)
        stale = self.run_cli(
            'checkpoint', run_id, 'check', '--rev', digest_a,
            '--writer-attempt', 'wa-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', '--evidence', 'check:pass:1',
        )
        self.assertNotEqual(stale.returncode, 0)
        self.assertIn('stale writer attempt', stale.stderr.lower())
        still = self.run_json('status', run_id)
        self.assertEqual(still['status'], 'active')
        self.assertEqual(still['current_stage'], 'check')
        self.assertNotIn('check', [c['stage'] for c in still['checkpoints']])


if __name__ == '__main__':
    unittest.main()
