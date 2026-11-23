#!/usr/bin/env python3
"""Canary observation CLI tests with a read-only fake kubectl."""
import copy
import json
import os
import runpy
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

BIN = Path(__file__).resolve().parents[1] / 'pi/.pi/agent/bin/pi-kube-maintenance'
DIGEST = 'sha256:' + 'a' * 64


def resources():
    template = {'metadata': {'labels': {'app': 'canary'}}, 'spec': {'containers': [{'name': 'canary', 'image': 'registry/canary:latest'}]}}
    dep = {'metadata': {'uid': 'dep', 'generation': 2, 'resourceVersion': '20', 'annotations': {'deployment.kubernetes.io/revision': '3'}}, 'spec': {'replicas': 1, 'template': template}, 'status': {'observedGeneration': 2, 'replicas': 1, 'updatedReplicas': 1, 'readyReplicas': 1, 'availableReplicas': 1, 'conditions': [{'type': 'Available', 'status': 'True'}, {'type': 'Progressing', 'status': 'True', 'reason': 'NewReplicaSetAvailable'}]}}
    rs_template = copy.deepcopy(template)
    rs_template['metadata']['labels']['pod-template-hash'] = 'abc'
    rs = {'metadata': {'name': 'canary-abc', 'uid': 'rs', 'generation': 1, 'resourceVersion': '30', 'ownerReferences': [{'uid': 'dep', 'kind': 'Deployment', 'controller': True}], 'annotations': {'deployment.kubernetes.io/revision': '3'}}, 'spec': {'replicas': 1, 'template': rs_template}, 'status': {'observedGeneration': 1, 'replicas': 1, 'readyReplicas': 1, 'availableReplicas': 1}}
    pod = {'metadata': {'name': 'canary-abc-123', 'uid': 'pod', 'resourceVersion': '40', 'ownerReferences': [{'uid': 'rs', 'kind': 'ReplicaSet', 'controller': True}]}, 'spec': {'containers': template['spec']['containers']}, 'status': {'phase': 'Running', 'conditions': [{'type': 'Ready', 'status': 'True'}, {'type': 'ContainersReady', 'status': 'True'}], 'containerStatuses': [{'name': 'canary', 'ready': True, 'imageID': 'containerd://' + DIGEST, 'state': {'running': {}}}]}}
    flux = {'metadata': {'uid': 'flux', 'generation': 4, 'resourceVersion': '10'}, 'status': {'observedGeneration': 4, 'lastAppliedRevision': 'main@sha1:' + 'b' * 40, 'lastAttemptedRevision': 'main@sha1:' + 'b' * 40, 'conditions': [{'type': 'Ready', 'status': 'True', 'observedGeneration': 4}]}}
    return [flux, dep, {'items': [rs]}, {'items': [pod]}]


class CanaryTests(unittest.TestCase):
    def run_observer(self, fixture, *, second=None, fail=False, candidate=None, candidate_mode=0o600):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'fixtures.json').write_text(json.dumps(fixture + (second or fixture)))
            executable = root / 'kubectl'
            executable.write_text('''#!/usr/bin/env python3
import json, os, pathlib, sys
p=pathlib.Path(os.environ['FAKE_ROOT'])
args=sys.argv[1:]
with (p/'calls').open('a') as f: f.write(json.dumps(args)+'\\n')
assert 'get' in args and not any(x in args for x in ['apply','patch','delete'])
assert '--context' in args and 'bay' in args and '--request-timeout=10s' in args
assert os.environ['KUBECONFIG']=='/private/kubeconfig'
if os.environ.get('FAKE_FAIL'): sys.stderr.write('connection refused'); sys.exit(1)
n=int((p/'count').read_text()) if (p/'count').exists() else 0
(p/'count').write_text(str(n+1))
print(json.dumps(json.loads((p/'fixtures.json').read_text())[n]))
''')
            executable.chmod(0o755)
            env = dict(os.environ, PATH=str(root) + os.pathsep + os.environ['PATH'], FAKE_ROOT=tmp, KUBECONFIG='/private/kubeconfig')
            if fail:
                env['FAKE_FAIL'] = '1'
            command = [sys.executable, str(BIN), '--once', '--context', 'bay', '--state-dir', str(root/'state')]
            if candidate is not None:
                candidate_path = root/'candidate.json'
                candidate_path.write_text(json.dumps(candidate))
                candidate_path.chmod(candidate_mode)
                command += ['--candidate-file', str(candidate_path)]
            result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=10)
            self.assertTrue((root/'state/latest.json').exists(), result.stderr)
            receipt = json.loads(result.stdout)
            self.assertEqual(receipt, json.loads((root/'state/latest.json').read_text()))
            if candidate is not None and receipt.get('candidate_id'):
                self.assertEqual(receipt, json.loads((root/'state/candidates'/ (receipt['candidate_id'] + '.json')).read_text()))
            return result, receipt

    def test_current_observation_is_not_release_verification(self):
        proc, receipt = self.run_observer(resources())
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(receipt['status'], 'observed')
        self.assertFalse(receipt['verified_release'])
        self.assertEqual(receipt['observation']['digests'], [DIGEST])
        self.assertEqual(receipt['observation']['deployment']['uid'], 'dep')

    def test_rejects_unready_stale_unowned_and_tag_only_evidence(self):
        changes = [
            lambda x: x[0]['metadata'].update(deletionTimestamp='now'),
            lambda x: x[1]['metadata'].update(deletionTimestamp='now'),
            lambda x: x[0]['status'].update(observedGeneration=3),
            lambda x: x[0]['status']['conditions'][0].update(observedGeneration=3),
            lambda x: x[0]['status'].update(lastAttemptedRevision='other'),
            lambda x: x[1]['status'].update(observedGeneration=1),
            lambda x: x[1]['status'].update(updatedReplicas=0),
            lambda x: x[2]['items'][0]['metadata']['ownerReferences'][0].update(uid='other'),
            lambda x: x[3]['items'][0]['status']['containerStatuses'][0].update(ready=False),
            lambda x: x[3]['items'][0]['status']['containerStatuses'][0].update(imageID='registry/canary:latest'),
            lambda x: x[3]['items'][0]['metadata'].update(deletionTimestamp='now'),
        ]
        for change in changes:
            with self.subTest(change=change):
                fixture = resources()
                change(fixture)
                proc, receipt = self.run_observer(fixture)
                self.assertNotEqual(proc.returncode, 0)
                self.assertEqual(receipt['status'], 'failed')
                self.assertTrue(receipt['error'])

    def test_rejects_racing_resource_version(self):
        second = resources()
        second[1]['metadata']['resourceVersion'] = '21'
        proc, receipt = self.run_observer(resources(), second=second)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn('changed', receipt['error'])

    def test_runtime_repository_digest_format(self):
        fixture = resources()
        fixture[3]['items'][0]['status']['containerStatuses'][0]['imageID'] = 'docker-pullable://registry/canary@' + DIGEST
        proc, receipt = self.run_observer(fixture)
        self.assertEqual(proc.returncode, 0, receipt)

    def test_malformed_and_extra_owned_pod_evidence_fails(self):
        for modify in (
            lambda x: x[3]['items'].append(copy.deepcopy(x[3]['items'][0])),
            lambda x: x[2]['items'][0]['spec']['template']['spec']['containers'][0].update(image='other'),
            lambda x: x[0]['status']['conditions'].append({'type': 'Reconciling', 'status': 'True'}),
            lambda x: x[1]['status'].update(unavailableReplicas=1),
        ):
            fixture = resources()
            modify(fixture)
            proc, receipt = self.run_observer(fixture)
            self.assertNotEqual(proc.returncode, 0)
            self.assertFalse(receipt['verified_release'])


    def candidate(self):
        return {'schema_version': 1,
                'target': {'context': 'bay', 'flux_namespace': 'flux-system', 'kustomization': 'autodeploy-canary', 'namespace': 'agent-school', 'deployment': 'autodeploy-canary', 'container': 'canary'},
                'expected_revision': 'master@sha1:' + 'b' * 40,
                'release': {'pr': 12, 'source_sha': 'c' * 40, 'merge_sha': 'b' * 40,
                            'required_ci': [{'context': 'validate', 'url': 'https://forgejo.test/run/1', 'sha': 'b' * 40, 'status': 'success'}]},
                'desired_image': 'registry/canary:latest',
                'registry_evidence': {'tag_ref': 'registry/canary:latest', 'manifest_digest': 'sha256:' + 'd' * 64, 'runtime_manifest_digest': DIGEST, 'url': 'https://registry.test/v2/canary/manifests/latest'}}

    def test_observe_only_bypasses_implicit_canary_candidate(self):
        script = runpy.run_path(str(BIN))
        fixture = self.candidate_resources()
        state = {'flux': fixture[0], 'deployment': fixture[1],
                 'replica_sets': fixture[2]['items'], 'pods': fixture[3]['items']}
        with tempfile.TemporaryDirectory() as tmp, patch.dict(script['main'].__globals__,
                load_candidate=unittest.mock.Mock(side_effect=AssertionError('must not load')),
                snapshot=unittest.mock.Mock(return_value=state)), patch.object(sys, 'argv',
                ['pi-kube-maintenance', '--once', '--observe-only', '--context', 'bay', '--state-dir', tmp]):
            with patch('builtins.print'):
                self.assertEqual(script['main'](), 0)
            receipt = json.loads((Path(tmp) / 'latest.json').read_text())
            self.assertFalse(receipt['verified_release'])
            self.assertEqual(receipt['mode'], 'current-observation')

    def test_descendant_revision_requires_bound_ancestry_evidence(self):
        candidate = self.candidate()
        revision = 'e' * 40
        candidate['release']['gitops_revision_sha'] = revision
        candidate['expected_revision'] = 'master@sha1:' + revision
        candidate['revision_evidence'] = {
            'release_merge_sha': 'b' * 40, 'revision_sha': revision,
            'relation': 'ahead', 'compare_url': 'https://forgejo.test/compare/b...e',
            'desired_image': candidate['desired_image'], 'file': 'app/kustomization.yaml',
            'blob_sha': 'f' * 40}
        fixture = self.candidate_resources()
        fixture[0]['status'].update(lastAppliedRevision=candidate['expected_revision'],
                                    lastAttemptedRevision=candidate['expected_revision'])
        proc, receipt = self.run_observer(fixture, candidate=candidate)
        self.assertEqual(proc.returncode, 0, receipt)
        self.assertTrue(receipt['verified_release'])
        for field in ('release_merge_sha', 'revision_sha', 'desired_image', 'blob_sha'):
            bad = copy.deepcopy(candidate)
            bad['revision_evidence'][field] = 'wrong'
            proc, receipt = self.run_observer(fixture, candidate=bad)
            self.assertNotEqual(proc.returncode, 0)
            self.assertFalse(receipt['verified_release'])

    def candidate_resources(self):
        fixture = resources()
        fixture[0]['status'].update(lastAppliedRevision='master@sha1:' + 'b' * 40, lastAttemptedRevision='master@sha1:' + 'b' * 40)
        fixture[3]['items'][0]['status']['containerStatuses'][0]['imageID'] = 'registry/canary@' + DIGEST
        return fixture

    def test_candidate_release_matches_registry_manifest_even_if_digest_unchanged(self):
        proc, receipt = self.run_observer(self.candidate_resources(), candidate=self.candidate())
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertTrue(receipt['verified_release'])
        self.assertEqual(receipt['mode'], 'candidate-verification')
        self.assertEqual(receipt['status'], 'verified')

    def test_candidate_rejects_false_pass_and_bad_receipts(self):
        cases = [
            ('revision', lambda c, f: f[0]['status'].update(lastAppliedRevision='master@sha1:'+'e'*40, lastAttemptedRevision='master@sha1:'+'e'*40)),
            ('image', lambda c, f: c.update(desired_image='registry/canary:other')),
            ('digest', lambda c, f: c['registry_evidence'].update(runtime_manifest_digest='sha256:'+'e'*64)),
            ('target', lambda c, f: c['target'].update(context='vas')),
            ('CI', lambda c, f: c['release']['required_ci'][0].update(status='pending')),
            ('CI', lambda c, f: c['release']['required_ci'][0].update(sha='e'*40)),
            ('revision', lambda c, f: c.update(expected_revision='master@sha1:'+'e'*40)),
        ]
        for reason, change in cases:
            with self.subTest(reason=reason):
                candidate, fixture = self.candidate(), self.candidate_resources()
                change(candidate, fixture)
                proc, receipt = self.run_observer(fixture, candidate=candidate)
                self.assertNotEqual(proc.returncode, 0)
                self.assertFalse(receipt['verified_release'])
                self.assertIn(reason.lower(), receipt['error'].lower())

    def test_broken_candidate_retains_attempted_revision_and_observed_tag(self):
        fixture = self.candidate_resources()
        fixture[0]['status'].update(lastAppliedRevision='master@sha1:'+'e'*40)
        fixture[0]['status']['conditions'][0].update(status='False', reason='HealthCheckFailed')
        fixture[1]['status'].update(readyReplicas=0, updatedReplicas=1)
        fixture[3]['items'][0]['status']['conditions'][0]['status'] = 'False'
        proc, receipt = self.run_observer(fixture, candidate=self.candidate())
        self.assertNotEqual(proc.returncode, 0)
        self.assertFalse(receipt['verified_release'])
        observed = receipt['observed']
        self.assertEqual(observed['flux']['lastAttemptedRevision'], self.candidate()['expected_revision'])
        self.assertEqual(observed['flux']['lastAppliedRevision'], 'master@sha1:'+'e'*40)
        self.assertEqual(observed['deployment']['image'], 'registry/canary:latest')
        self.assertIn('HealthCheckFailed', receipt['error'])
        self.assertIn('expected', receipt['error'])

    def test_candidate_rejects_writable_file(self):
        proc, receipt = self.run_observer(self.candidate_resources(), candidate=self.candidate(), candidate_mode=0o666)
        self.assertNotEqual(proc.returncode, 0)
        self.assertFalse(receipt['verified_release'])
        self.assertIn('writable', receipt['error'])
        self.assertEqual(receipt['mode'], 'candidate-verification')

    def test_candidate_opaque_runtime_digest_is_not_manifest_evidence(self):
        fixture = self.candidate_resources()
        fixture[3]['items'][0]['status']['containerStatuses'][0]['imageID'] = 'containerd://' + DIGEST
        proc, receipt = self.run_observer(fixture, candidate=self.candidate())
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn('opaque', receipt['error'])

    def test_candidate_inputs_race_and_removal_fail_closed(self):
        script = runpy.run_path(str(BIN))
        state = {'flux': self.candidate_resources()[0], 'deployment': self.candidate_resources()[1], 'replica_sets': self.candidate_resources()[2]['items'], 'pods': self.candidate_resources()[3]['items']}
        for changed in (None, dict(self.candidate(), desired_image='registry/canary:other')):
            with tempfile.TemporaryDirectory() as tmp, patch.dict(script['main'].__globals__, load_candidate=unittest.mock.Mock(side_effect=[self.candidate(), changed]), snapshot=unittest.mock.Mock(return_value=state)):
                with patch.object(sys, 'argv', ['pi-kube-maintenance', '--once', '--context', 'bay', '--state-dir', tmp]), patch('builtins.print'):
                    self.assertEqual(script['main'](), 1)
                receipt = json.loads((Path(tmp)/'latest.json').read_text())
                self.assertFalse(receipt['verified_release'])
                self.assertIn('candidate changed', receipt['error'])

    def test_indexed_candidate_outcome_survives_recovery_and_observation_mode(self):
        script = runpy.run_path(str(BIN))
        fixture = self.candidate_resources()
        state = {'flux': fixture[0], 'deployment': fixture[1], 'replica_sets': fixture[2]['items'], 'pods': fixture[3]['items']}
        with tempfile.TemporaryDirectory() as tmp:
            candidate = self.candidate()
            def run(value, error=False):
                with patch.dict(script['main'].__globals__, load_candidate=unittest.mock.Mock(return_value=value), snapshot=unittest.mock.Mock(side_effect=script['ObservationError']('temporary read error')) if error else unittest.mock.Mock(return_value=state)):
                    with patch.object(sys, 'argv', ['pi-kube-maintenance', '--once', '--context', 'bay', '--state-dir', tmp]), patch('builtins.print'):
                        code = script['main']()
                return code, json.loads((Path(tmp)/'latest.json').read_text())
            self.assertEqual(run(candidate, True)[0], 1)
            code, recovered = run(candidate)
            self.assertEqual(code, 0)
            self.assertTrue(recovered['verified_release'])
            proof = Path(tmp)/'verified'/(recovered['candidate_id']+'.json')
            self.assertEqual(json.loads(proof.read_text()), recovered)
            code, failed = run(candidate, True)
            self.assertEqual(code, 1)
            self.assertFalse(failed['verified_release'])
            indexed = Path(tmp)/'candidates'/(recovered['candidate_id']+'.json')
            self.assertEqual(json.loads(indexed.read_text()), failed)
            self.assertEqual(json.loads(proof.read_text()), recovered)
            self.assertEqual(run(None)[1]['mode'], 'current-observation')
            self.assertEqual(json.loads(indexed.read_text()), failed)

    def test_missing_malformed_symlink_and_unauthorized_candidate(self):
        script = runpy.run_path(str(BIN))
        args = type('Args', (), self.candidate()['target'])()
        load = script['load_candidate']
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'candidate.json'
            self.assertIsNone(load(path, args))
            with self.assertRaisesRegex(script['ObservationError'], 'missing'):
                load(path, args, explicit=True)
            path.write_text('{broken')
            path.chmod(0o600)
            with self.assertRaisesRegex(script['ObservationError'], 'invalid'):
                load(path, args, explicit=True)
            path.write_text(json.dumps(self.candidate()))
            link = Path(tmp)/'link'
            link.symlink_to(path)
            with self.assertRaisesRegex(script['ObservationError'], 'safely'):
                load(link, args, explicit=True)
            with self.assertRaisesRegex(script['ObservationError'], 'owner'):
                load(path, args)

    def test_duplicate_candidate_fields_and_unsafe_default_parent_rejected(self):
        script = runpy.run_path(str(BIN))
        args = type('Args', (), self.candidate()['target'])()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'candidate.json'
            path.write_text(json.dumps(self.candidate())[:-1] + ', "schema_version": 1}')
            path.chmod(0o600)
            with self.assertRaisesRegex(script['ObservationError'], 'duplicate'):
                script['load_candidate'](path, args, explicit=True)
            path.write_text(json.dumps(self.candidate()))
            real_stat = os.fstat
            def fake_stat(descriptor):
                metadata = list(real_stat(descriptor))
                metadata[4] = 0
                return os.stat_result(metadata)
            with patch('os.fstat', side_effect=fake_stat):
                with self.assertRaisesRegex(script['ObservationError'], 'directory'):
                    script['load_candidate'](path, args)

    def test_observed_failure_excludes_condition_messages_and_termination_logs(self):
        fixture = self.candidate_resources()
        fixture[0]['status']['conditions'][0].update(status='False', reason='HealthCheckFailed', message='PRIVATE_APPLICATION_LOG')
        fixture[3]['items'][0]['status']['containerStatuses'][0]['state'] = {'terminated': {'reason': 'Error', 'message': 'PRIVATE_APPLICATION_LOG', 'exitCode': 1}}
        proc, receipt = self.run_observer(fixture, candidate=self.candidate())
        self.assertNotEqual(proc.returncode, 0)
        self.assertNotIn('PRIVATE_APPLICATION_LOG', json.dumps(receipt))
        self.assertIn('HealthCheckFailed', receipt['error'])
        self.assertEqual(receipt['observed']['pods'][0]['containers'][0]['state'], 'terminated')

    def test_candidate_filesystem_race_persists_failed_receipt(self):
        script = runpy.run_path(str(BIN))
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(script['main'].__globals__, load_candidate=unittest.mock.Mock(side_effect=OSError('candidate directory disappeared'))):
                with patch.object(sys, 'argv', ['pi-kube-maintenance', '--once', '--context', 'bay', '--state-dir', tmp]), patch('builtins.print'):
                    self.assertEqual(script['main'](), 1)
            receipt = json.loads((Path(tmp)/'latest.json').read_text())
            self.assertFalse(receipt['verified_release'])
            self.assertIn('directory disappeared', receipt['error'])

    def test_subprocess_timeout_is_bounded_and_reported(self):
        script = runpy.run_path(str(BIN))
        get = script['get']
        args = type('Args', (), {'context': 'bay'})()
        with patch('subprocess.run', side_effect=subprocess.TimeoutExpired('kubectl', 15)) as command:
            with self.assertRaisesRegex(script['ObservationError'], 'timed out'):
                get(args, 'flux-system', 'kustomizations', 'autodeploy-canary')
            self.assertEqual(command.call_args.kwargs['timeout'], 15)

    def test_kubectl_failure_persists_failed_receipt(self):
        proc, receipt = self.run_observer(resources(), fail=True)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn('connection refused', receipt['error'])


if __name__ == '__main__':
    unittest.main()
