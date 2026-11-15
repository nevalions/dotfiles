import copy
import unittest
from typing import Any
from validate_gate import validate


def fixture() -> dict[str, Any]:
    identity = dict(repo='/repo', worktree='/candidate', base_sha='a'*40,
                    scope_digest='b'*64, plan_digest='c'*64,
                    candidate_digest='d'*64, policy_digest='e'*64)
    def evidence(**kwargs):
        return dict(binding=copy.deepcopy(identity), evidence_ref='fixture:only', **kwargs)
    return dict(identity=identity, risk='high', browser_required=True,
                preflight=dict(status='PASS', repo='/repo', base_sha='a'*40),
                approvals={k: evidence(decision='APPROVED', actor_kind='human', actor='user', action=k, targets=['/candidate'] if k == 'cleanup' else [])
                           for k in ['plan', 'implement', 'deliver', 'cleanup']},
                reviews={k: evidence(verdict='APPROVED', source_card=k, native=True)
                         for k in ['plan', 'implementation']},
                tests={k: evidence(status='PASS', exit_code=0) for k in ['tester', 'browser-tester']},
                docs=evidence(status='PASS'), acceptance=evidence(status='PASS'),
                wiki=evidence(status='PASS', authorized=True, scope='RW/task-summary'),
                delivery_policy=evidence(actions=['commit', 'push'], repository='/repo'),
                requested_actions=['commit', 'push'],
                delivery=evidence(status='PASS', delivered_sha='f'*40, result_sha='f'*40),
                final_sha='f'*40,
                ci=dict(status='PASS', sha='f'*40, provider='forgejo', evidence_ref='fixture:run',
                        checks=[dict(name='tests', status='PASS')], required_checks=['tests']),
                beads=dict(exists=True, actor='hermes:beads-coordinator:session', owner='hermes:beads-coordinator:session', handoff='fixture:owned'),
                cleanup=evidence(dry_run=True, clean=True, integrated=True, targets=['/candidate'], approved_targets=['/candidate']))


class Gates(unittest.TestCase):
    def test_cleanup_cannot_self_authorize_targets(self):
        data = fixture()
        data['cleanup']['targets'] = ['/unrelated']
        data['cleanup']['approved_targets'] = ['/unrelated']
        self.assertTrue(validate(data, 'cleanup'))

    def test_valid_pipeline(self):
        for stage in ['plan', 'implement', 'deliver', 'close', 'cleanup']:
            with self.subTest(stage=stage):
                self.assertEqual(validate(fixture(), stage), [])

    def test_fail_closed_mutations(self):
        cases = [
            ('plan', 'approvals.plan.binding.scope_digest', '9'*64),
            ('plan', 'approvals.plan.binding.plan_digest', '9'*64),
            ('plan', 'approvals.plan.binding.candidate_digest', '9'*64),
            ('plan', 'approvals.plan.binding.policy_digest', '9'*64),
            ('plan', 'approvals.plan.actor_kind', 'bot'),
            ('plan', 'approvals.plan.evidence_ref', ''),
            ('plan', 'preflight.status', 'FAIL'),
            ('plan', 'risk', 'unknown'),
            ('implement', 'reviews.plan.verdict', 'REQUEST_CHANGES'),
            ('deliver', 'reviews.implementation.native', False),
            ('deliver', 'tests.tester.status', 'FAIL'),
            ('deliver', 'tests.tester.exit_code', 1),
            ('deliver', 'tests.browser-tester.status', 'SKIPPED'),
            ('deliver', 'docs.binding.candidate_digest', '9'*64),
            ('deliver', 'acceptance.status', 'UNKNOWN'),
            ('deliver', 'wiki.authorized', False),
            ('deliver', 'requested_actions', ['merge']),
            ('close', 'ci.sha', '0'*40),
            ('close', 'ci.status', 'SKIPPED'),
            ('close', 'ci.status', 'MISSING'),
            ('close', 'ci.checks', []),
            ('close', 'ci.checks', [{'name':'tests', 'status':'SKIPPED'}]),
            ('close', 'final_sha', '0'*40),
            ('close', 'delivery.result_sha', '0'*40),
            ('close', 'beads.owner', 'someone-else'),
            ('cleanup', 'cleanup.dry_run', False),
            ('cleanup', 'cleanup.clean', False),
            ('cleanup', 'cleanup.integrated', False),
            ('cleanup', 'cleanup.approved_targets', ['/unrelated']),
            ('cleanup', 'approvals.cleanup.binding.candidate_digest', '9'*64),
        ]
        for stage, path, value in cases:
            with self.subTest(stage=stage, mutation=path):
                data = fixture()
                target = data
                keys = path.split('.')
                for key in keys[:-1]:
                    target = target[key]
                target[keys[-1]] = value
                self.assertTrue(validate(data, stage))

    def test_unknown_or_malformed_rejected(self):
        for data, stage in [(fixture(), 'unknown'), ({}, 'close'), ([], 'plan')]:
            with self.subTest(stage=stage, data=type(data)):
                self.assertTrue(validate(data, stage))

    def test_missing_required_objects(self):
        for key in fixture():
            with self.subTest(key=key):
                data = fixture()
                del data[key]
                self.assertTrue(validate(data, 'cleanup'))

    def test_optional_browser_and_absent_beads(self):
        data = fixture()
        data['browser_required'] = False
        del data['tests']['browser-tester']
        data['beads'] = {'exists': False}
        self.assertEqual(validate(data, 'close'), [])

    def test_low_risk_waives_only_design_approvals(self):
        data = fixture()
        data['risk'] = 'low'
        del data['approvals']['plan']
        del data['approvals']['implement']
        self.assertEqual(validate(data, 'deliver'), [])
        del data['approvals']['deliver']
        self.assertTrue(validate(data, 'deliver'))

    def test_missing_approval_blocks(self):
        data = fixture()
        del data['approvals']['plan']
        self.assertTrue(validate(data, 'plan'))


if __name__ == '__main__':
    unittest.main()
