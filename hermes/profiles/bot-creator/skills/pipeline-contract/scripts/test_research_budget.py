import unittest
from validate_gate import validate


def evidence():
    return {'research': {'phase': 'triage', 'budget_seconds': 300,
        'max_runtime_seconds': 300, 'max_retries': 1, 'tool_call_limit': 12,
        'update_interval_seconds': 120, 'wrapup_reserve_seconds': 60,
        'runtime_evidence_ref': 'isolated-test/readback',
        'checkpoint_ref': 'task-comment/start', 'prior_evidence_ref': 'report/or-none-checked',
        'stop_criteria': 'alternatives discriminated or unknown',
        'owner': 'researcher', 'production_execution': False,
        'final_acceptance_card': 'acceptance-card', 'auto_extend': False}}


class ResearchBudgetTests(unittest.TestCase):
    def test_bounded_triage_admitted(self):
        self.assertEqual(validate(evidence(), 'research'), [])

    def test_invalid_budgets_and_missing_evidence_block(self):
        for key, values in {
            'budget_seconds': [None, 0, -1, True, '300', 301],
            'max_runtime_seconds': [None, 0, True, 301],
            'max_retries': [None, 0, 2, True],
            'tool_call_limit': [0, 13, True],
            'update_interval_seconds': [0, 121, True],
            'wrapup_reserve_seconds': [0, 59, 300, True],
            'auto_extend': [True, None], 'production_execution': [True, None],
            'phase': ['endless', None],
        }.items():
            for value in values:
                with self.subTest(key=key, value=value):
                    data = evidence()
                    data['research'][key] = value
                    self.assertTrue(validate(data, 'research'))
        for key in evidence()['research']:
            data = evidence()
            del data['research'][key]
            self.assertTrue(validate(data, 'research'), key)

    def test_separately_authorized_diagnostic_and_executor_limits(self):
        data = evidence()
        r = data['research']
        r.update(phase='diagnostic', budget_seconds=600, max_runtime_seconds=600,
                 tool_call_limit=20)
        self.assertTrue(validate(data, 'research'))
        r['authorization_ref'] = 'human/scoped-approval'
        self.assertEqual(validate(data, 'research'), [])
        r.update(production_execution=True, commands_ref='approved/commands',
                 command_timeout_seconds=60, commands_per_test=3, max_attempts=2)
        self.assertTrue(validate(data, 'research'))
        r['owner'] = 'diagnostic-executor'
        self.assertEqual(validate(data, 'research'), [])
        for key, value in [('command_timeout_seconds', 61), ('commands_per_test', 4),
                           ('max_attempts', 3), ('commands_ref', ''),
                           ('authorization_ref', ''), ('budget_seconds', 601)]:
            old = r[key]
            r[key] = value
            self.assertTrue(validate(data, 'research'), key)
            r[key] = old

    def test_malformed_input_blocks(self):
        for data in (None, [], {}, {'research': None}, {'research': []}):
            self.assertTrue(validate(data, 'research'))


if __name__ == '__main__':
    unittest.main()
