"""Document admission/recovery contracts + real existing guard regressions.
Document checks are NOT live binding/admission enforcement.
"""
import copy
from pathlib import Path
import unittest
import review_loop_guard as guard
from test_review_loop_guard import fixture

ROOT = Path(__file__).resolve().parents[1]

class RecoveryContract(unittest.TestCase):
    def clauses(self, file, *clauses):
        text = (ROOT/'references'/file).read_text()
        for clause in clauses:
            with self.subTest(clause=clause):
                self.assertIn(clause, text)

    def test_missing_wrong_binding_rejection_contract(self):
        self.clauses('workspace-lifecycle.md',
            'BEFORE repo-edit admission', 'Missing binding => NOT ADMITTED',
            'Wrong binding => NOT ADMITTED', 'read back persisted workspace_kind',
            'must not silently create a divergent authoritative candidate')

    def test_replacement_history_and_duplicate_contract(self):
        self.clauses('worker-progress.md', 'same candidate exact digest',
            'old worker verified idle', 'old card parked', 'same-board',
            'source and replacement history', 'cumulative consumed budget',
            'Duplicate intent => reconcile', 'Ambiguous create/link/unlink => uncertain',
            'No reset', 'no cross-board edges', 'no fake completion')

    def test_budget_mapping_and_amendment_contract(self):
        self.clauses('review-loop-guard.md',
            'initial author + initial independent review + one correctable correction + independent rereview',
            'explicit no-retry/no-correction', 'review_rejection_limit=1',
            'separately bounded amendment', 'original stage_started_at',
            'Unknown required budget usage blocks admission', 'old expired snapshot remains STOP')

    def first(self):
        d = fixture()
        d['history'] = d['history'][:1]
        d['expected_records'] = 1
        return d

    def test_first_correctable_then_independent_rereview_allowed(self):
        d = self.first()
        self.assertEqual(guard.evaluate(d)['decision'], 'CONTINUE')
        d['history'].append(copy.deepcopy(fixture()['history'][1]))
        d['expected_records'] = 2
        d['next_action'] = 'review'
        self.assertEqual(guard.evaluate(d)['decision'], 'CONTINUE')

    def test_no_correction_exhaustion_and_second_rejection_block(self):
        d = self.first(); d['policy']['review_rejection_limit'] = 1
        self.assertIn('REVIEW_LIMIT', guard.evaluate(d)['reasons'])
        d = self.first(); d['stopped'] = True
        self.assertIn('EXPLICIT_STOP', guard.evaluate(d)['reasons'])
        d = self.first(); d['now'] = d['policy']['stage_wall_seconds']
        self.assertIn('STAGE_WALL_BUDGET', guard.evaluate(d)['reasons'])
        self.assertIn('REVIEW_LIMIT', guard.evaluate(fixture())['reasons'])

    def test_replacement_does_not_reset_usage_or_history(self):
        d = fixture()
        d['task'] = 'replacement_execution'
        for r in d['history']:
            r['tokens_delta'] = 4
            r['tools_delta'] = 2
        d['policy']['total_token_budget'] = 12
        result = guard.evaluate(d)
        self.assertIn('REVIEW_LIMIT', result['reasons'])
        self.assertIn('TOKEN_BUDGET', result['reasons'])
        self.assertEqual(result['usage']['measured_tokens'], 12)
        self.assertEqual(result['usage']['measured_tools'], 6)
        self.assertEqual(result['usage']['stage_elapsed_seconds'], 30)
        d['expected_records'] += 1
        self.assertIn('INVALID_INPUT', guard.evaluate(d)['reasons'])

    def test_decision_cannot_waive_expired_stage(self):
        d = fixture(); d['now'] = 3600
        d['decision'] = dict(actor='Orchestrator', authorization_ref='synthetic-user',
            design_ref='synthetic-amendment', after_seq=3,
            history_digest=guard.history_digest(d['history']),
            binding={k: copy.deepcopy(d[k]) for k in guard.BINDING_KEYS},
            remaining_corrections=1, acknowledged_reasons=['REVIEW_LIMIT'])
        self.assertIn('STAGE_WALL_BUDGET', guard.evaluate(d)['reasons'])
        self.assertEqual(guard.evaluate(d)['decision'], 'STOP')

if __name__ == '__main__':
    unittest.main()
