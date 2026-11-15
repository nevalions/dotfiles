"""Offline policy tests; no board or network writes."""
import copy
import unittest
try:
    import review_loop_guard as guard
except ModuleNotFoundError:
    from types import SimpleNamespace
    guard = SimpleNamespace()


def fixture():
    return {'task': 't_example', 'candidate': '/owned/candidate', 'scope': 'diagnostics',
            'models': {'author': 'unchanged-author', 'reviewer': 'unchanged-reviewer'},
            'stage_started_at': 0, 'now': 30, 'history_complete': True,
            'expected_records': 3, 'stopped': False,
            'policy': {'stage_wall_seconds': 3600, 'no_progress_limit': 2,
                       'required_tests': ['offline'], 'role': 'implementation'},
            'history': [
                {'seq': 1, 'run_id': 1, 'role': 'reviewer', 'at': 10, 'outcome': 'changes_requested'},
                {'seq': 2, 'run_id': 2, 'role': 'author', 'at': 20, 'outcome': 'correction'},
                {'seq': 3, 'run_id': 3, 'role': 'reviewer', 'at': 30, 'outcome': 'changes_requested'}]}


class ReviewLoopTests(unittest.TestCase):
    def test_default_two_rejections_escalate_not_approve(self):
        self.assertTrue(hasattr(guard, 'evaluate'), 'offline evaluator is missing')
        result = guard.evaluate(fixture())
        self.assertEqual(result['decision'], 'ESCALATE')
        self.assertIn('REVIEW_LIMIT', result['reasons'])
        self.assertFalse(result['review_approved'])
        self.assertEqual(result['route'], 'Orchestrator')


    def test_high_severity_after_correction_requires_architecture(self):
        d = fixture()
        d['policy']['review_rejection_limit'] = 9
        for i in (0, 2):
            d['history'][i]['issues'] = [{'code': 'PRIVACY_LEAK', 'severity': 'high'}]
        self.assertIn('ARCHITECTURE_REVIEW', guard.evaluate(d)['reasons'])
        d['history'][1]['outcome'] = 'checkpoint'
        self.assertEqual(guard.evaluate(d)['decision'], 'CONTINUE')

    def test_total_stage_wall_not_per_run(self):
        d = fixture()
        d['history'] = d['history'][:1]; d['expected_records'] = 1
        d['now'] = 3600
        self.assertEqual(guard.evaluate(d)['decision'], 'STOP')
        self.assertIn('STAGE_WALL_BUDGET', guard.evaluate(d)['reasons'])

    def test_identical_evidence_and_diff_not_activity(self):
        d = fixture(); d['policy']['review_rejection_limit'] = 9
        for r in d['history']:
            r.update(evidence_digest='a'*64, diff_digest='b'*64)
        self.assertIn('NO_PROGRESS', guard.evaluate(d)['reasons'])
        for i, r in enumerate(d['history']): r['diff_digest'] = str(i)*64
        self.assertEqual(guard.evaluate(d)['decision'], 'CONTINUE')

    def test_capability_denial_stops_first_blind_retry(self):
        for outcome in ('command_denied', 'capability_mismatch'):
            d = fixture(); d['history'][1]['outcome'] = outcome
            self.assertIn('CAPABILITY_REPLAN', guard.evaluate(d)['reasons'])

    def test_required_tests_bound_to_review_handoff(self):
        d = fixture(); d['history'] = d['history'][:1]; d['expected_records'] = 1
        d['history'][0].update(role='author', outcome='review_requested', diff_digest='b'*64)
        self.assertIn('REQUIRED_TESTS', guard.evaluate(d)['reasons'])
        d['history'][0]['tests'] = {'offline': {'status': 'PASS', 'exit_code': 0, 'diff_digest': 'b'*64}}
        self.assertEqual(guard.evaluate(d)['decision'], 'CONTINUE')
        d['history'][0]['tests']['offline']['diff_digest'] = 'c'*64
        self.assertIn('REQUIRED_TESTS', guard.evaluate(d)['reasons'])


    def test_stop_and_history_integrity_are_not_new_run_scoped(self):
        d = fixture(); d['stopped'] = True
        d['history'][-1]['run_id'] = 999
        self.assertIn('EXPLICIT_STOP', guard.evaluate(d)['reasons'])
        self.assertEqual(guard.evaluate(d)['decision'], 'STOP')
        for field, value in [('history_complete', False), ('expected_records', 9)]:
            d = fixture(); d[field] = value
            self.assertIn('INVALID_INPUT', guard.evaluate(d)['reasons'])

    def test_invalid_policy_fails_closed_without_echo(self):
        for value in (0, -1, True, 'token-secret'):
            d = fixture(); d['policy']['stage_wall_seconds'] = value
            result = guard.evaluate(d)
            self.assertEqual(result['decision'], 'STOP')
            self.assertNotIn('token-secret', str(result))

    def test_manual_decision_exact_binding_and_finite_allowance(self):
        d = fixture()
        self.assertTrue(hasattr(guard, 'history_digest'), 'history binding helper missing')
        d['decision'] = {'actor': 'Orchestrator', 'authorization_ref': 'user-message-1',
            'design_ref': 'structured-replacement-v1', 'after_seq': 3,
            'history_digest': guard.history_digest(d['history']),
            'binding': {k: copy.deepcopy(d[k]) for k in ('task', 'candidate', 'scope', 'models', 'stage_started_at', 'policy')},
            'remaining_corrections': 1,
            'acknowledged_reasons': ['REVIEW_LIMIT']}
        self.assertEqual(guard.evaluate(d)['decision'], 'CONTINUE')
        invalid = copy.deepcopy(d); invalid['models']['author'] = 'different'
        self.assertIn('INVALID_DECISION', guard.evaluate(invalid)['reasons'])
        invalid = copy.deepcopy(d); invalid['decision']['remaining_corrections'] = -1
        self.assertEqual(guard.evaluate(invalid)['decision'], 'STOP')
        d['history'].append({'seq': 4, 'run_id': 4, 'role': 'author', 'at': 30, 'outcome': 'correction'})
        d['expected_records'] = 4
        self.assertIn('CORRECTION_ALLOWANCE', guard.evaluate(d)['reasons'])
        d['next_action'] = 'review'
        self.assertEqual(guard.evaluate(d)['decision'], 'CONTINUE')
        d['history'].append({'seq': 5, 'run_id': 5, 'role': 'reviewer', 'at': 30, 'outcome': 'changes_requested'})
        d['expected_records'] = 5; d['next_action'] = 'author'
        self.assertEqual(guard.evaluate(d)['decision'], 'STOP')


    def test_cycle_and_token_budgets_include_review(self):
        d = fixture(); d['policy']['cycle_wall_seconds'] = 25
        self.assertIn('CYCLE_WALL_BUDGET', guard.evaluate(d)['reasons'])
        d = fixture(); d['policy']['total_token_budget'] = 100
        for r in d['history']: r['tokens_delta'] = 40
        self.assertIn('TOKEN_BUDGET', guard.evaluate(d)['reasons'])
        self.assertEqual(guard.evaluate(d)['usage']['measured_tokens'], 120)
        del d['history'][0]['tokens_delta']
        self.assertEqual(guard.evaluate(d)['usage']['coverage'], 'UNKNOWN')
        self.assertIsNone(guard.evaluate(d)['usage']['measured_tokens'])
        self.assertEqual(guard.evaluate(d)['usage']['known_token_subtotal'], 80)

    def test_provider_window_is_not_task_token_attribution(self):
        d = fixture(); d['policy']['provider_window_ceiling_percent'] = 70
        d['provider_window'] = {'reported_percent': 75, 'source': 'user-report'}
        self.assertIn('PROVIDER_WINDOW_BUDGET', guard.evaluate(d)['reasons'])
        self.assertEqual(guard.evaluate(d)['usage']['coverage'], 'UNKNOWN')
        self.assertIsNone(guard.evaluate(d)['usage']['measured_tokens'])
        d['before_expensive_phase'] = True; d['fresh_checkpoint'] = False
        self.assertIn('CHECKPOINT_REQUIRED', guard.evaluate(d)['reasons'])


    def test_role_task_budgets_and_tools_are_generic(self):
        for task_type, budget in [('bugfix', 300), ('feature', 900), ('deployment', 1800)]:
            d = fixture(); d['scope'] = task_type; d['policy']['role'] = task_type
            d['policy']['stage_wall_seconds'] = budget
            d['policy']['total_tool_budget'] = 10
            self.assertIsNone(guard.evaluate(d)['usage']['measured_tools'])
            for r in d['history']: r['tools_delta'] = 4
            self.assertIn('TOOL_BUDGET', guard.evaluate(d)['reasons'])
            self.assertEqual(guard.evaluate(d)['usage']['stage_elapsed_seconds'], 30)
            d['history'] = d['history'][:1]; d['expected_records'] = 1
            self.assertEqual(guard.evaluate(d)['decision'], 'CONTINUE')
            self.assertFalse(guard.evaluate(d)['review_approved'])


    def test_saved_real_sequence_read_only(self):
        import json
        import os
        from pathlib import Path
        path = os.environ.get('REVIEW_GUARD_REAL_FIXTURE')
        if not path:
            self.skipTest('set REVIEW_GUARD_REAL_FIXTURE to separately retained sanitized evidence')
        d = json.loads(Path(path).read_text())
        self.assertEqual(sum(r['outcome'] == 'changes_requested' for r in d['history']), 5)
        self.assertIn('REVIEW_LIMIT', guard.evaluate(d)['reasons'])
        prefix = copy.deepcopy(d); prefix['history'] = prefix['history'][:4]
        prefix['expected_records'] = 4; prefix['stopped'] = False
        self.assertIn('REVIEW_LIMIT', guard.evaluate(prefix)['reasons'])
        self.assertFalse(guard.evaluate(d)['review_approved'])

    def test_cli_invalid_input_and_optimized_mode_fail_closed(self):
        import subprocess
        import sys
        from pathlib import Path
        script = str(Path(guard.__file__).resolve())
        result = subprocess.run([sys.executable, script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 3)
        self.assertIn('INVALID_INPUT', result.stdout)
        result = subprocess.run([sys.executable, '-O', '-c',
            'import review_loop_guard as g; from test_review_loop_guard import fixture; d=fixture(); d["history_complete"]=False; print(g.evaluate(d))'],
            cwd=str(Path(script).parent), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn('INVALID_INPUT', result.stdout)


if __name__ == '__main__':
    unittest.main()
