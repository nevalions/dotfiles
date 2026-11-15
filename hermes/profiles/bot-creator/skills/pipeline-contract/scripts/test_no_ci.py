"""Synthetic policy tests: no fixture is a real user authorization."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from test_validate_gate import fixture
from validate_gate import validate


def exempt_fixture():
    data = fixture()
    data['ci'] = dict(status='EXEMPT', sha=data['final_sha'],
                      binding=copy.deepcopy(data['identity']), evidence_ref='fixture:no-ci',
                      required_checks=[], checks=[])
    approval = copy.deepcopy(data['approvals']['deliver'])
    approval.update(action='ci-exemption', repository='/repo', target='refs/heads/main',
                    scope='no-ci', sha=data['final_sha'], policy_ref='fixture:existing-user-policy')
    data['approvals']['ci-exemption'] = approval
    data['delivery']['target'] = 'refs/heads/main'
    data['ci']['target'] = 'refs/heads/main'
    return data


class NoCI(unittest.TestCase):
    def test_explicit_approved_exemption(self):
        for stage in ('close', 'cleanup'):
            self.assertEqual(validate(exempt_fixture(), stage), [])

    def test_exemption_fail_closed(self):
        mutations = {
            'approvals.ci-exemption': None,
            'approvals.ci-exemption.actor_kind': 'bot',
            'approvals.ci-exemption.decision': 'PENDING',
            'approvals.ci-exemption.action': 'deliver',
            'approvals.ci-exemption.repository': '/wrong',
            'approvals.ci-exemption.scope': 'all',
            'approvals.ci-exemption.target': 'refs/heads/other',
            'approvals.ci-exemption.sha': '0'*40,
            'approvals.ci-exemption.policy_ref': ' ',
            'approvals.ci-exemption.evidence_ref': '',
            'ci.sha': '0'*40,
            'ci.target': 'refs/heads/other',
            'ci.evidence_ref': '',
            'ci.status': 'MISSING',
            'ci.required_checks': ['tests'],
            'ci.checks': [{'name': 'tests', 'status': 'FAIL'}],
            'delivery.target': 'refs/heads/other',
        }
        for obj in ('ci', 'approvals.ci-exemption'):
            for key, value in fixture()['identity'].items():
                mutations[f'{obj}.binding.{key}'] = '/wrong' if key in ('repo', 'worktree') else '0'*len(value)
        for path, value in mutations.items():
            with self.subTest(path=path):
                data = exempt_fixture()
                target = data
                parts = path.split('.')
                for part in parts[:-1]:
                    target = target[part]
                target[parts[-1]] = value
                self.assertTrue(validate(data, 'close'))
        for key in exempt_fixture()['approvals']['ci-exemption']:
            data = exempt_fixture()
            del data['approvals']['ci-exemption'][key]
            # targets is unrelated inherited cleanup metadata, not authorization.
            if key != 'targets':
                with self.subTest(missing=key):
                    self.assertTrue(validate(data, 'close'))

    def test_no_implicit_exemption_or_bypass(self):
        for stage in ('close', 'cleanup'):
            for key in ('ci', 'approvals'):
                data = exempt_fixture()
                del data[key]
                self.assertTrue(validate(data, stage))
            for path in ('approvals.deliver', 'reviews.implementation', 'tests.tester', 'delivery'):
                data = exempt_fixture()
                parts = path.split('.')
                target = data if len(parts) == 1 else data[parts[0]]
                del target[parts[-1]]
                self.assertTrue(validate(data, stage))
        data = exempt_fixture()
        del data['approvals']['cleanup']
        self.assertTrue(validate(data, 'cleanup'))

    def test_cli_reports_exempt_not_ci_pass(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'evidence.json'
            path.write_text(json.dumps(exempt_fixture()))
            result = subprocess.run([sys.executable, str(Path(__file__).with_name('validate_gate.py')),
                                     str(path), 'close'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report.get('ci_status'), 'EXEMPT')
        self.assertEqual(report.get('status'), 'EXEMPT')


if __name__ == '__main__':
    unittest.main()
