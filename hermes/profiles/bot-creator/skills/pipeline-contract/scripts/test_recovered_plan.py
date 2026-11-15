"""Synthetic evidence only; never a live review or authorization."""
import copy
import unittest
from test_validate_gate import fixture
from validate_gate import validate


def recovered_fixture():
    data = fixture()
    def evidence(**fields):
        return dict(binding=copy.deepcopy(data['identity']), evidence_ref='synthetic:only', **fields)
    data['reviews']['plan'].update(native=False, mode='recovered-artifact-review',
        source_card='synthetic-author-card', recovery=dict(
            source=evidence(card='synthetic-author-card', run='synthetic-author-run',
                            profile='planner', status='timed_out', verified=True),
            artifact=evidence(path='/synthetic/plan.md', sha256='c'*64,
                              current_sha256='c'*64, complete=True, preserved=True, verified=True),
            reviewer=evidence(card='synthetic-review-card', run='synthetic-review-run',
                              profile='independent-reviewer', status='completed', verdict='APPROVED',
                              artifact_sha256='c'*64, verified=True),
            idle=evidence(card='synthetic-author-card', run='synthetic-author-run',
                          profile='planner', session='synthetic-session', state='idle',
                          active_worker=False, verified=True),
            decision=evidence(actor='Orchestrator', actor_kind='orchestrator',
                              action='recover-plan-review', decision='APPROVED',
                              source_card='synthetic-author-card', source_run='synthetic-author-run',
                              review_card='synthetic-review-card', review_run='synthetic-review-run',
                              artifact_sha256='c'*64, authorization_ref='synthetic:user-message',
                              verified=True),
            authorization=evidence(actor='user', actor_kind='human', action='workflow-recovery',
                                   decision='APPROVED', verified=True,
                                   source_card='synthetic-author-card', source_run='synthetic-author-run')))
    data['reviews']['plan']['recovery']['authorization']['evidence_ref'] = 'synthetic:user-message'
    return data


class RecoveredPlan(unittest.TestCase):
    def test_independent_saved_plan_admitted_without_native_provenance(self):
        for stage in ('implement', 'deliver', 'close', 'cleanup'):
            self.assertEqual(validate(recovered_fixture(), stage), [])

    def test_every_recovery_field_required(self):
        recovery = recovered_fixture()['reviews']['plan']['recovery']
        for section, record in recovery.items():
            for field in record:
                with self.subTest(section=section, field=field):
                    data = recovered_fixture()
                    del data['reviews']['plan']['recovery'][section][field]
                    self.assertTrue(validate(data, 'implement'))

    def test_fail_closed_mutations(self):
        cases = {
            'native': True, 'mode': 'ordinary-review', 'verdict': 'UNKNOWN', 'source_card': 'wrong',
            'recovery.source.status': 'completed', 'recovery.source.verified': False,
            'recovery.source.profile': '', 'recovery.source.run': '',
            'recovery.artifact.sha256': 'x'*64, 'recovery.artifact.current_sha256': 'a'*64,
            'recovery.artifact.path': 'relative', 'recovery.artifact.complete': False,
            'recovery.artifact.preserved': False, 'recovery.artifact.verified': False,
            'recovery.reviewer.profile': 'planner', 'recovery.reviewer.card': 'synthetic-author-card',
            'recovery.reviewer.run': 'synthetic-author-run', 'recovery.reviewer.status': 'running',
            'recovery.reviewer.verdict': 'REQUEST_CHANGES', 'recovery.reviewer.verified': False,
            'recovery.reviewer.artifact_sha256': 'a'*64,
            'recovery.idle.card': 'wrong', 'recovery.idle.run': 'wrong', 'recovery.idle.profile': 'wrong',
            'recovery.idle.session': '', 'recovery.idle.state': 'busy',
            'recovery.idle.active_worker': True, 'recovery.idle.verified': False,
            'recovery.decision.actor_kind': 'worker', 'recovery.decision.actor': '',
            'recovery.decision.action': 'deploy', 'recovery.decision.decision': 'UNKNOWN',
            'recovery.decision.source_card': 'wrong', 'recovery.decision.source_run': 'wrong',
            'recovery.decision.review_card': 'wrong', 'recovery.decision.review_run': 'wrong',
            'recovery.decision.artifact_sha256': 'a'*64,
            'recovery.decision.authorization_ref': 'wrong', 'recovery.decision.verified': False,
            'recovery.authorization.actor_kind': 'bot', 'recovery.authorization.actor': '',
            'recovery.authorization.action': 'deploy', 'recovery.authorization.decision': 'UNKNOWN',
            'recovery.authorization.source_card': 'wrong', 'recovery.authorization.source_run': 'wrong',
            'recovery.authorization.verified': False,
        }
        for section in recovered_fixture()['reviews']['plan']['recovery']:
            cases['recovery.'+section+'.binding.candidate_digest'] = 'a'*64
            cases['recovery.'+section+'.evidence_ref'] = ' '
        for path, value in cases.items():
            with self.subTest(path=path):
                data = recovered_fixture()
                target = data['reviews']['plan']
                keys = path.split('.')
                for key in keys[:-1]:
                    target = target[key]
                target[keys[-1]] = value
                self.assertTrue(validate(data, 'implement'))

    def test_no_generic_bypass_or_implementation_recovery(self):
        data = fixture()
        data['reviews']['plan']['native'] = False
        self.assertTrue(validate(data, 'implement'))
        data = recovered_fixture()
        data['reviews']['implementation'] = copy.deepcopy(data['reviews']['plan'])
        self.assertTrue(validate(data, 'deliver'))


if __name__ == '__main__':
    unittest.main()
