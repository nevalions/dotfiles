"""Executable characterization of existing offline evaluators, NOT orchestration.

No scheduler, network, board, publication, or native notification replay.
PIPELINE_SCRIPTS permits checking this test against a reviewed staged tree.
"""
import copy
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import unittest

SCRIPTS = Path(os.environ.get('PIPELINE_SCRIPTS',
    '/home/linroot/.hermes/profiles/bot-creator/skills/pipeline-contract/scripts'))
sys.path.insert(0, str(SCRIPTS))
from validate_gate import validate
from review_loop_guard import evaluate, history_digest, BINDING_KEYS
from test_validate_gate import fixture as gate_fixture
from test_review_loop_guard import fixture as guard_fixture


def single_history(outcome='checkpoint'):
    d = guard_fixture()
    d['history'] = [dict(seq=1, run_id=1, role='author', at=10, outcome=outcome)]
    d['expected_records'] = 1
    return d


def recovery_fixture():
    d = guard_fixture()
    d['decision'] = dict(actor='Orchestrator', authorization_ref='fixture:authorization',
        design_ref='fixture:changed-design', after_seq=3,
        history_digest=history_digest(d['history']),
        binding={k: copy.deepcopy(d[k]) for k in BINDING_KEYS},
        remaining_corrections=1, acknowledged_reasons=['REVIEW_LIMIT'])
    return d


class EvidenceReuse(unittest.TestCase):
    def test_unchanged_evidence_reusable_without_mutation(self):
        d = gate_fixture(); before = copy.deepcopy(d)
        self.assertEqual(validate(d, 'deliver'), [])
        self.assertEqual(validate(d, 'deliver'), [])
        self.assertEqual(d, before)

    def test_candidate_scope_policy_plan_or_base_change_blocks_old_evidence(self):
        for key in ('candidate_digest', 'scope_digest', 'policy_digest', 'plan_digest', 'base_sha'):
            with self.subTest(key=key):
                d = gate_fixture(); d['identity'][key] = '9' * len(d['identity'][key])
                self.assertTrue(validate(d, 'deliver'))

    def test_refreshing_review_only_does_not_refresh_old_tests(self):
        d = gate_fixture(); d['identity']['candidate_digest'] = '9' * 64
        for record in d['reviews'].values():
            record['binding'] = copy.deepcopy(d['identity'])
        self.assertIn('tester: stale binding', validate(d, 'deliver'))

    def test_immutable_evidence_does_not_override_observed_stale_preflight(self):
        d = gate_fixture(); d['preflight']['base_sha'] = '9' * 40
        self.assertIn('preflight missing or stale', validate(d, 'deliver'))

    def test_required_test_evidence_matches_changed_review_diff(self):
        d = single_history('review_requested')
        r = d['history'][0]; r['diff_digest'] = 'a' * 64
        r['tests'] = {'offline': dict(status='PASS', exit_code=0, diff_digest='a' * 64)}
        self.assertEqual(evaluate(d)['decision'], 'CONTINUE')
        r['diff_digest'] = 'b' * 64
        self.assertIn('REQUIRED_TESTS', evaluate(d)['reasons'])


class AdmissionAndDependencyGates(unittest.TestCase):
    def test_missing_plan_review_blocks_implementation(self):
        d = gate_fixture(); del d['reviews']['plan']
        self.assertTrue(validate(d, 'implement'))

    def test_pending_implementation_review_blocks_delivery(self):
        d = gate_fixture(); d['reviews']['implementation']['verdict'] = 'PENDING'
        self.assertIn('implementation: native review not approved', validate(d, 'deliver'))

    def test_missing_human_delivery_approval_blocks_even_if_checks_pass(self):
        d = gate_fixture(); del d['approvals']['deliver']
        self.assertTrue(validate(d, 'deliver'))

    def test_ci_final_sha_required_context_and_failed_context_block_close(self):
        mutations = [('sha', '0'*40), ('required_checks', ['missing-context']),
                     ('checks', [dict(name='tests', status='FAIL')])]
        for key, value in mutations:
            with self.subTest(key=key):
                d = gate_fixture(); d['ci'][key] = value
                self.assertTrue(validate(d, 'close'))

    def test_independent_evaluations_overlap_and_preserve_owned_inputs(self):
        # Barrier proves actual overlapping TEST threads, not native scheduler behavior.
        barrier = threading.Barrier(2, timeout=5)
        inputs = [gate_fixture(), single_history()]
        before = copy.deepcopy(inputs)
        def gate_read():
            barrier.wait(); return threading.get_ident(), validate(inputs[0], 'deliver')
        def guard_read():
            barrier.wait(); return threading.get_ident(), evaluate(inputs[1])
        with ThreadPoolExecutor(max_workers=2) as pool:
            a, b = pool.submit(gate_read), pool.submit(guard_read)
            aid, av = a.result(timeout=10); bid, bv = b.result(timeout=10)
        self.assertNotEqual(aid, bid)
        self.assertEqual(av, []); self.assertEqual(bv['decision'], 'CONTINUE')
        self.assertEqual(inputs, before)


class ExplicitEnforcementGaps(unittest.TestCase):
    """Passing these tests documents a LIMIT, not desirable enforced admission."""
    def test_whole_stage_preflight_is_not_an_executable_schema(self):
        # These extra fields do not belong to validate_gate's enforced schema.
        for field in ('authentication', 'protection', 'required_ci', 'deploy_triggers',
                      'tool_path', 'reviewer_identity', 'worker_idle', 'authority_window'):
            with self.subTest(document_only_field=field):
                d = gate_fixture(); d['preflight'][field] = 'UNKNOWN'
                self.assertEqual(validate(d, 'deliver'), [])

    def test_schema_version_and_approval_expiry_are_not_checked(self):
        d = gate_fixture()
        d['schema_version'] = 'unknown-version'
        d['approvals']['deliver']['expires_at'] = 0
        self.assertEqual(validate(d, 'deliver'), [])

    def test_repeated_evaluator_call_is_pure_not_event_deduplication(self):
        d = single_history('command_denied'); before = copy.deepcopy(d)
        self.assertEqual(evaluate(d), evaluate(d))
        self.assertEqual(d, before)
        self.assertFalse(evaluate(d)['native_enforcement'])

    def test_repeated_verdict_is_not_deduplicated_by_run_id(self):
        d = single_history(); r = d['history'][0]
        r.update(role='reviewer', outcome='changes_requested')
        d['history'].append(dict(r, seq=2)); d['expected_records'] = 2
        self.assertIn('REVIEW_LIMIT', evaluate(d)['reasons'])

    def test_ambiguous_side_effect_has_no_evaluator_event_type(self):
        d = single_history('ambiguous_write')
        self.assertEqual(evaluate(d)['decision'], 'STOP')
        self.assertIn('INVALID_INPUT', evaluate(d)['reasons'])


class BoundedRecovery(unittest.TestCase):
    def test_missing_history_and_out_of_order_history_fail_closed(self):
        d = guard_fixture(); d['history_complete'] = False
        self.assertIn('INVALID_INPUT', evaluate(d)['reasons'])
        d = guard_fixture(); d['history'][2]['at'] = 5
        self.assertIn('INVALID_INPUT', evaluate(d)['reasons'])

    def test_denial_requires_replan_not_permission_or_approval(self):
        d = single_history('command_denied'); result = evaluate(d)
        self.assertEqual(result['decision'], 'ESCALATE')
        self.assertIn('CAPABILITY_REPLAN', result['reasons'])
        self.assertFalse(result['review_approved'])

    def test_one_recovery_consumes_allowance_but_permits_final_review(self):
        d = recovery_fixture(); self.assertEqual(evaluate(d)['decision'], 'CONTINUE')
        d['history'].append(dict(seq=4, run_id=4, role='author', at=30, outcome='correction'))
        d['expected_records'] = 4
        self.assertIn('CORRECTION_ALLOWANCE', evaluate(d)['reasons'])
        d['next_action'] = 'review'
        self.assertEqual(evaluate(d)['decision'], 'CONTINUE')

    def test_recovery_does_not_reset_original_budget_or_explicit_stop(self):
        for mutation in ('time', 'stop', 'tools'):
            with self.subTest(mutation=mutation):
                d = recovery_fixture()
                if mutation == 'time': d['now'] = d['policy']['stage_wall_seconds']
                if mutation == 'stop': d['stopped'] = True
                if mutation == 'tools':
                    d['policy']['total_tool_budget'] = 3
                    d['decision']['binding']['policy'] = copy.deepcopy(d['policy'])
                    for r in d['history']: r['tools_delta'] = 1
                    d['decision']['history_digest'] = history_digest(d['history'])
                self.assertEqual(evaluate(d)['decision'], 'STOP')

    def test_new_run_does_not_erase_unchanged_evidence_no_progress(self):
        d = guard_fixture(); d['policy']['review_rejection_limit'] = 9
        for i, r in enumerate(d['history']):
            r.update(outcome='checkpoint', run_id=100+i, diff_digest='a'*64, evidence_digest='b'*64)
        self.assertIn('NO_PROGRESS', evaluate(d)['reasons'])

    def test_unknown_usage_is_not_reported_as_zero(self):
        d = single_history(); result = evaluate(d)
        self.assertEqual(result['usage']['coverage'], 'UNKNOWN')
        self.assertIsNone(result['usage']['measured_tokens'])
        self.assertIsNone(result['usage']['measured_tools'])

    def test_cli_interfaces_preserved(self):
        # stdin is not a supported evidence interface; no fabricated invocation success.
        for name, code in [('review_loop_guard.py', 3), ('validate_gate.py', 2)]:
            p = subprocess.run([sys.executable, str(SCRIPTS/name)], capture_output=True, text=True, timeout=10)
            self.assertEqual(p.returncode, code)
        p = subprocess.run([sys.executable, str(SCRIPTS/'review_loop_guard.py')],
                           capture_output=True, text=True, timeout=10)
        self.assertEqual(json.loads(p.stdout)['decision'], 'STOP')


if __name__ == '__main__':
    unittest.main(verbosity=2)
