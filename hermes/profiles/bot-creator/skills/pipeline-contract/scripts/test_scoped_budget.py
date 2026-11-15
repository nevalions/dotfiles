import unittest
from validate_gate import validate
from test_research_budget import evidence


class ScopedBudgetTests(unittest.TestCase):
    def test_task_scope_allows_sized_diagnostic_without_new_read_approval(self):
        data = evidence()
        data['research'].update(
            phase='diagnostic', budget_seconds=1200, max_runtime_seconds=1200,
            tool_call_limit=40, authorization_ref='user/task-implementation-scope',
            budget_limits={'seconds': 1200, 'calls': 40,
                           'scope_ref': 'user/task-implementation-scope',
                           'rationale': 'Two-repository selected-field discovery and evidence handoff'})
        self.assertEqual(validate(data, 'research'), [])

    def test_scoped_budget_still_fails_closed(self):
        data = evidence()
        r = data['research']
        r.update(phase='diagnostic', budget_seconds=1200, max_runtime_seconds=1200,
                 tool_call_limit=40, authorization_ref='user/task-scope',
                 budget_limits={'seconds': 1200, 'calls': 40,
                                'scope_ref': 'user/task-scope', 'rationale': 'bounded discovery'})
        from copy import deepcopy
        for key, values in {'seconds': [None, 0, -1, True, '1200', 1199],
                            'calls': [None, 0, -1, True, '40', 39],
                            'scope_ref': [None, '', ' '], 'rationale': [None, '', ' ']}.items():
            for value in values:
                with self.subTest(key=key, value=value):
                    bad = deepcopy(data)
                    bad['research']['budget_limits'][key] = value
                    self.assertTrue(validate(bad, 'research'))
            bad = deepcopy(data)
            del bad['research']['budget_limits'][key]
            self.assertTrue(validate(bad, 'research'))
        for value in [None, [], 'unlimited']:
            bad = deepcopy(data)
            bad['research']['budget_limits'] = value
            self.assertTrue(validate(bad, 'research'))
        for key, value in [('max_runtime_seconds', 1201), ('max_retries', 2),
                           ('auto_extend', True), ('authorization_ref', ''),
                           ('production_execution', True), ('phase', 'implementation')]:
            bad = deepcopy(data)
            bad['research'][key] = value
            self.assertTrue(validate(bad, 'research'), key)

    def test_sized_budget_does_not_relax_production_command_limits(self):
        data = evidence()
        r = data['research']
        r.update(phase='diagnostic', budget_seconds=1200, max_runtime_seconds=1200,
                 tool_call_limit=40, authorization_ref='human/exact-execution',
                 budget_limits={'seconds': 1200, 'calls': 40,
                                'scope_ref': 'human/exact-execution', 'rationale': 'evidence overhead'},
                 production_execution=True, owner='cluster-operator',
                 commands_ref='reviewed/exact-commands', command_timeout_seconds=60,
                 commands_per_test=3, max_attempts=2)
        self.assertEqual(validate(data, 'research'), [])
        for key, value in [('command_timeout_seconds', 61), ('commands_per_test', 4),
                           ('max_attempts', 3), ('commands_ref', '')]:
            old = r[key]
            r[key] = value
            self.assertTrue(validate(data, 'research'), key)
            r[key] = old


if __name__ == '__main__':
    unittest.main()
