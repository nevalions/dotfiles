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
    def run_observer(self, fixture, *, second=None, fail=False):
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
            result = subprocess.run([sys.executable, str(BIN), '--once', '--context', 'bay', '--state-dir', str(root/'state')], env=env, capture_output=True, text=True, timeout=10)
            self.assertTrue((root/'state/latest.json').exists(), result.stderr)
            receipt = json.loads(result.stdout)
            self.assertEqual(receipt, json.loads((root/'state/latest.json').read_text()))
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
