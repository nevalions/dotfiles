"""Synthetic recovery evidence, not real authority or task admission."""
import copy
import unittest
import review_loop_guard as g
from test_review_loop_guard import fixture


from typing import Any


def packet() -> tuple[dict[str, Any], dict[str, Any]]:
    old = fixture()
    old['history'][1]['outcome'] = 'review_requested'  # missing historical tests
    phase = fixture()
    phase.update(stage_started_at=40, now=40, history=[], expected_records=0,
                 next_action='author', candidate_digest='b'*64)
    phase['policy'].update(stage_wall_seconds=480, cycle_wall_seconds=480,
                           review_rejection_limit=1)
    old['recovery_phase'] = phase
    authority = dict(actor='Orchestrator', actor_kind='human-authorized-owner',
        action='corrective-author-phase', decision='APPROVED', revoked=False,
        authorization_ref='synthetic-owner-message', reason='Correct retained test binding findings',
        historical_digest=g.history_digest({k:v for k,v in old.items() if k != 'recovery_phase'}),
        binding={k:copy.deepcopy(phase[k]) for k in g.BINDING_KEYS},
        candidate_digest='b'*64, issued_at=40, expires_at=520,
        author_profile='implementer', reviewer_profile='reviewer',
        acknowledged_reasons=g.evaluate({k:v for k,v in old.items() if k != 'recovery_phase'})['reasons'])
    phase['authorization_ref'] = authority['authorization_ref']
    return old, authority


class RecoveryBudgetTests(unittest.TestCase):
    def test_explicit_3900_seconds_authorizes_whole_phase_not_approval(self):
        d, a = packet()
        p = d['recovery_phase']
        p['policy'].update(stage_wall_seconds=3900, cycle_wall_seconds=3900)
        a.update(max_phase_seconds=3900, expires_at=a['issued_at']+3900,
                 binding={k:copy.deepcopy(p[k]) for k in g.BINDING_KEYS})
        original = copy.deepcopy(d)
        result = g.evaluate(d, recovery_authority=a)
        self.assertEqual(result['decision'], 'CONTINUE')
        self.assertFalse(result['review_approved'])
        self.assertFalse(result['phase_ready_for_acceptance'])
        self.assertEqual(d, original)


    def test_missing_budget_keeps_legacy_480_ceiling(self):
        d, a = packet()
        self.assertNotIn('max_phase_seconds', a)
        self.assertEqual(g.evaluate(d, recovery_authority=a)['decision'], 'CONTINUE')
        for target in ('expiry', 'stage'):
            x, owner = copy.deepcopy(d), copy.deepcopy(a)
            if target == 'expiry':
                owner['expires_at'] = owner['issued_at']+481
            else:
                x['recovery_phase']['policy']['stage_wall_seconds'] = 481
                owner['binding']['policy']['stage_wall_seconds'] = 481
            self.assertEqual(g.evaluate(x, recovery_authority=owner)['reasons'],
                             ['INVALID_RECOVERY'], target)

    def test_invalid_explicit_budget_is_not_ignored(self):
        for value in (True, False, -1, 0, 480.0, 3900.0, 3901, None, '3900'):
            with self.subTest(value=value):
                d, a = packet(); a['max_phase_seconds'] = value
                self.assertEqual(g.evaluate(d, recovery_authority=a)['reasons'],
                                 ['INVALID_RECOVERY'])

    def test_expiry_and_phase_fit_explicit_authority_ceiling(self):
        for target in ('expiry', 'stage', 'expired'):
            with self.subTest(target=target):
                d, a = packet(); a['max_phase_seconds'] = 479
                if target == 'expiry':
                    d['recovery_phase']['policy']['stage_wall_seconds'] = 479
                    a['binding']['policy']['stage_wall_seconds'] = 479
                else:
                    a['expires_at'] = a['issued_at']+479
                if target == 'expired':
                    d['recovery_phase']['now'] = a['expires_at']
                self.assertEqual(g.evaluate(d, recovery_authority=a)['reasons'],
                                 ['INVALID_RECOVERY'])

    def test_3900_phase_preserves_rejection_tests_and_independence(self):
        d, a = packet(); p = d['recovery_phase']
        p['policy'].update(stage_wall_seconds=3900, cycle_wall_seconds=3900)
        a.update(max_phase_seconds=3900, expires_at=a['issued_at']+3900,
                 binding={k:copy.deepcopy(p[k]) for k in g.BINDING_KEYS})
        completed(d)
        p['now'] = a['issued_at']+3899
        self.assertTrue(g.evaluate(d, recovery_authority=a)['phase_ready_for_acceptance'])
        for mutation in ('rejected', 'tests', 'self_review', 'expired', 'limit'):
            x, owner = copy.deepcopy(d), copy.deepcopy(a)
            phase = x['recovery_phase']
            if mutation == 'rejected': phase['history'][-1]['outcome'] = 'changes_requested'
            if mutation == 'tests': phase['history'][1].pop('tests')
            if mutation == 'self_review': phase['history'][-1]['profile'] = 'implementer'
            if mutation == 'expired': phase['now'] = owner['expires_at']
            if mutation == 'limit':
                phase['policy']['review_rejection_limit'] = 2
                owner['binding']['policy']['review_rejection_limit'] = 2
            self.assertNotEqual(g.evaluate(x, recovery_authority=owner)['decision'],
                                'CONTINUE', mutation)

    def test_dotfiles_3900_with_sanitized_s1_history_test_only_authority(self):
        import json
        import os
        from pathlib import Path
        path = os.environ.get('REVIEW_GUARD_RECOVERY_FIXTURE')
        if not path:
            self.skipTest('supply separately retained sanitized S1 history')
        old = json.loads(Path(path).read_text())
        original = copy.deepcopy(old)
        self.assertTrue(old['task'].startswith('dotfiles/'))
        historical = g.evaluate(old)
        self.assertEqual(historical['reasons'],
                         ['CAPABILITY_REPLAN', 'REQUIRED_TESTS', 'REVIEW_LIMIT'])
        d, a = packet(); p = d['recovery_phase']
        for key in ('task', 'candidate', 'scope', 'models'):
            p[key] = copy.deepcopy(old[key])
        p.update(stage_started_at=old['now']+1, now=old['now']+1)
        p['policy'].update(stage_wall_seconds=3900, cycle_wall_seconds=3900,
                           required_tests=old['policy']['required_tests'][:])
        a.update(max_phase_seconds=3900, issued_at=p['now'], expires_at=p['now']+3900,
                 binding={k:copy.deepcopy(p[k]) for k in g.BINDING_KEYS},
                 historical_digest=g.history_digest(old),
                 acknowledged_reasons=historical['reasons'])
        old['recovery_phase'] = p
        for elapsed in (0, 1800, 3600, 3899):
            p['now'] = p['stage_started_at']+elapsed
            r = g.evaluate(old, recovery_authority=a)
            self.assertEqual(r['decision'], 'CONTINUE')
            self.assertEqual(r['historical']['result'], historical)
            self.assertFalse(r['review_approved'])
            self.assertFalse(r['phase_ready_for_acceptance'])
        p['now'] = a['expires_at']
        self.assertEqual(g.evaluate(old, recovery_authority=a)['decision'], 'STOP')
        self.assertEqual({k:v for k,v in old.items() if k != 'recovery_phase'}, original)


class RecoveryTests(unittest.TestCase):
    def test_author_admission_retains_nonpass_history_without_approval(self):
        d, a = packet()
        import inspect
        self.assertIn('recovery_authority', inspect.signature(g.evaluate).parameters)
        r = g.evaluate(d, recovery_authority=a)
        self.assertEqual(r['decision'], 'CONTINUE')
        self.assertFalse(r['review_approved'])
        self.assertEqual(r['historical']['disposition'], 'STOP')
        self.assertIn('REQUIRED_TESTS', r['historical']['result']['reasons'])
        self.assertFalse(r['phase_ready_for_acceptance'])


def completed(d):
    p = d['recovery_phase']; p['next_action'] = 'handoff'; p['now'] = 44
    p['history'] = [
        dict(seq=1, run_id=10, role='author', profile='implementer', at=41,
             outcome='correction', diff_digest='b'*64),
        dict(seq=2, run_id=10, role='author', profile='implementer', at=42,
             outcome='review_requested', diff_digest='b'*64,
             tests={'offline': dict(status='PASS', exit_code=0, diff_digest='b'*64)}),
        dict(seq=3, run_id=11, role='reviewer', profile='reviewer', at=43,
             outcome='approved', diff_digest='b'*64,
             tests={'offline': dict(status='PASS', exit_code=0, diff_digest='b'*64)})]
    p['expected_records'] = 3
    return d


class RecoveryBoundaryTests(unittest.TestCase):
    def test_no_final_acceptance_without_new_tests_and_independent_review(self):
        d, a = packet(); d['recovery_phase']['next_action'] = 'handoff'
        self.assertNotEqual(g.evaluate(d, recovery_authority=a)['decision'], 'CONTINUE')
        d = completed(d)
        self.assertTrue(g.evaluate(d, recovery_authority=a)['phase_ready_for_acceptance'])
        self.assertIn('REQUIRED_TESTS', g.evaluate(d, recovery_authority=a)['historical']['result']['reasons'])
        for mutation in ('tests', 'profile', 'run', 'stale'):
            x = copy.deepcopy(d); r = x['recovery_phase']['history'][-1]
            if mutation == 'tests': r.pop('tests')
            if mutation == 'profile': r['profile'] = 'implementer'
            if mutation == 'run': r['run_id'] = 10
            if mutation == 'stale': r['tests']['offline']['diff_digest'] = 'c'*64
            self.assertNotEqual(g.evaluate(x, recovery_authority=a)['decision'], 'CONTINUE', mutation)

    def test_one_correction_no_author_redispatch_and_new_rejection_stops(self):
        d, a = packet(); completed(d)
        d['recovery_phase']['next_action'] = 'author'
        self.assertEqual(g.evaluate(d, recovery_authority=a)['decision'], 'STOP')
        d['recovery_phase']['next_action'] = 'review'
        d['recovery_phase']['history'][-1]['outcome'] = 'changes_requested'
        self.assertEqual(g.evaluate(d, recovery_authority=a)['decision'], 'STOP')

    def test_authority_invalid_variants_fail_closed(self):
        for mutation in ('missing', 'ref', 'expired', 'trimmed', 'raise', 'candidate', 'generic', 'reason'):
            d, a = packet()
            if mutation == 'missing': a = None
            if mutation == 'ref': a['authorization_ref'] = 'other'
            if mutation == 'expired': d['recovery_phase']['now'] = 520
            if mutation == 'trimmed': d['history'].pop(); d['expected_records'] -= 1
            if mutation == 'raise': d['policy']['review_rejection_limit'] = 9
            if mutation == 'candidate': d['recovery_phase']['candidate_digest'] = 'c'*64
            if mutation == 'generic': a = {'approved': True}
            if mutation == 'reason': a['reason'] = ' '
            self.assertEqual(g.evaluate(d, recovery_authority=a)['decision'], 'STOP', mutation)

    def test_corrected_candidate_new_digest_and_old_results_remain_immutable(self):
        d, a = packet(); completed(d)
        original = copy.deepcopy(d)
        d['recovery_phase']['initial_candidate_digest'] = 'b'*64
        d['recovery_phase']['candidate_digest'] = 'c'*64
        for r in d['recovery_phase']['history']:
            r['diff_digest'] = 'c'*64
            for t in r.get('tests', {}).values(): t['diff_digest'] = 'c'*64
        self.assertEqual(g.evaluate(d, recovery_authority=a)['decision'], 'CONTINUE')
        self.assertEqual({k:v for k,v in d.items() if k != 'recovery_phase'},
                         {k:v for k,v in original.items() if k != 'recovery_phase'})

    def test_cumulative_configured_usage_never_resets(self):
        d, a = packet(); d['policy']['total_tool_budget'] = 10
        d['recovery_phase']['policy']['total_tool_budget'] = 10
        for r in d['history']: r['tools_delta'] = 4
        a['historical_digest'] = g.history_digest({k:v for k,v in d.items() if k != 'recovery_phase'})
        a['acknowledged_reasons'] = g.evaluate({k:v for k,v in d.items() if k != 'recovery_phase'})['reasons']
        a['binding']['policy'] = copy.deepcopy(d['recovery_phase']['policy'])
        self.assertEqual(g.evaluate(d, recovery_authority=a)['decision'], 'STOP')

    def test_missing_test_on_new_handoff_does_not_use_old_evidence(self):
        d, a = packet(); completed(d)
        d['recovery_phase']['history'][1].pop('tests')
        self.assertNotEqual(g.evaluate(d, recovery_authority=a)['decision'], 'CONTINUE')

    def test_real_sanitized_history_if_supplied(self):
        import json
        import os
        from pathlib import Path
        path = os.environ.get('REVIEW_GUARD_RECOVERY_FIXTURE')
        if not path:
            self.skipTest('supply separately retained sanitized history for read-only regression')
        old = json.loads(Path(path).read_text())
        self.assertEqual(g.evaluate(old)['reasons'],
                         ['CAPABILITY_REPLAN', 'REQUIRED_TESTS', 'REVIEW_LIMIT'])
        d, a = packet(); phase = d['recovery_phase']
        for k in ('task', 'candidate', 'scope', 'models'):
            phase[k] = copy.deepcopy(old[k])
        phase.update(stage_started_at=old['now']+1, now=old['now']+1)
        phase['policy']['required_tests'] = old['policy']['required_tests'][:]
        a.update(binding={k:copy.deepcopy(phase[k]) for k in g.BINDING_KEYS},
                 historical_digest=g.history_digest(old), issued_at=phase['now'],
                 expires_at=phase['now']+480, acknowledged_reasons=g.evaluate(old)['reasons'])
        old['recovery_phase'] = phase
        result = g.evaluate(old, recovery_authority=a)
        self.assertEqual(result['decision'], 'CONTINUE')
        self.assertEqual(result['historical']['result']['reasons'], a['acknowledged_reasons'])
        self.assertFalse(result['review_approved'])

    def test_revoked_or_wrong_action_authority_stops(self):
        for key, value in (('revoked', True), ('decision', 'DENIED'), ('action', 'publish')):
            d, a = packet(); a[key] = value
            self.assertEqual(g.evaluate(d, recovery_authority=a)['decision'], 'STOP')

    def test_cli_separate_owner_authority_required(self):
        import json
        import subprocess
        import sys
        import tempfile
        from pathlib import Path
        d, a = packet()
        with tempfile.TemporaryDirectory() as td:
            evidence = Path(td)/'evidence.json'; authority = Path(td)/'owner.json'
            evidence.write_text(json.dumps(d)); authority.write_text(json.dumps(a))
            command = [sys.executable, g.__file__, str(evidence)]
            self.assertEqual(subprocess.run(command, capture_output=True).returncode, 3)
            run = subprocess.run(command + [str(authority)], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stdout)
            self.assertFalse(json.loads(run.stdout)['review_approved'])

    def test_fake_waiver_and_ordinary_second_rejection_unchanged(self):
        d = fixture()
        self.assertEqual(g.evaluate(d)['decision'], 'ESCALATE')
        d['waive_tests'] = True
        d['history'][1]['outcome'] = 'review_requested'
        self.assertIn('REQUIRED_TESTS', g.evaluate(d)['reasons'])
        d, a = packet(); d['recovery_authority'] = a
        self.assertEqual(g.evaluate(d)['decision'], 'STOP')


if __name__ == '__main__':
    unittest.main()
