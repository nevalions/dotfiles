"""Fail-closed policy and durable handoff tests; no live services."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / 'pi/.pi/agent/yt-maintenance/controller.py'
spec = importlib.util.spec_from_file_location('yt_controller', SOURCE)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class PolicyTests(unittest.TestCase):
    def test_epoch_is_only_permitted_change(self):
        old = 'FROM alpine:3.24\nARG APK_PATCH_EPOCH=2026-11-22\nRUN echo ok\n'
        new = m.advance_epoch(old, '2026-11-23')
        self.assertEqual(new, old.replace('2026-11-22', '2026-11-23'))
        self.assertTrue(m.epoch_only(old, new))
        for bad in [new + '\n', new.replace('echo ok', 'echo no'), old,
                    new.replace('2026-11-23', '2026-02-30')]:
            with self.assertRaises(m.Rejected):
                m.epoch_only(old, bad)
        with self.assertRaises(m.Rejected):
            m.advance_epoch(old + 'ARG APK_PATCH_EPOCH=2020-01-01\n', '2026-11-23')

    def test_apk_index_exact_package_and_architecture(self):
        data = 'P:libxml2\nV:2.13.9-r3\nA:x86_64\n\nP:other\nV:9\nA:x86_64\n'
        self.assertEqual(m.apk_versions(data, 'libxml2', 'x86_64'), ['2.13.9-r3'])
        self.assertEqual(m.apk_versions(data, 'libxml2', 'aarch64'), [])

    def test_native_apk_comparator_is_mandatory(self):
        with patch.object(m, 'run', return_value='<\n') as run:
            self.assertTrue(m.apk_less('2.13.9-r2', '2.13.9-r3', ['apk']))
            run.assert_called_once_with(['apk', 'version', '-t', '2.13.9-r2', '2.13.9-r3'])
        with patch.object(m, 'run', return_value='unknown'):
            with self.assertRaises(m.Rejected):
                m.apk_less('1', '2', ['apk'])

    def test_freshness_rejects_future_and_old_evidence(self):
        with patch.object(m, 'now', return_value=1000):
            m.fresh(900, 200)
            for stamp in [0, 1100, 700]:
                with self.assertRaises(m.Rejected):
                    m.fresh(stamp, 200)

    def test_durable_state_deduplicates_and_retains_failed_retries(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'state.json'
            state = {'proposals': {'fix': {'branch': 'maintenance/test'}}, 'pending': {'merge_sha': 'a' * 40}}
            m.atomic_json(p, state)
            self.assertEqual(json.loads(p.read_text()), state)
            self.assertEqual(p.stat().st_mode & 0o777, 0o600)

    def test_receipt_must_bind_exact_candidate_and_current_invocation(self):
        candidate = {'target': {'context': 'bay'}, 'schema_version': 1}
        receipt = {'verified_release': True, 'status': 'verified', 'candidate': candidate,
                   'candidate_id': m.identity(candidate), 'observed_at': '2026-11-23T12:00:00+00:00'}
        m.verify_receipt(receipt, candidate, 1795435200)
        for field, value in [('verified_release', False), ('candidate_id', 'wrong'), ('candidate', {})]:
            bad = copy.deepcopy(receipt)
            bad[field] = value
            with self.assertRaises(m.Rejected):
                m.verify_receipt(bad, candidate, 1795435200)


if __name__ == '__main__':
    unittest.main()

class QualificationTests(unittest.TestCase):
    def setUp(self):
        self.digest = 'sha256:' + 'a' * 64
        self.config = {'platform': 'linux/amd64', 'image_repository': 'registry.example/library/app',
                       'package': 'libxml2', 'alpine_branch': 'v3.24', 'apk_command': ['apk'],
                       'harbor': {'url': 'https://registry.example'},
                       'source': {'repo': 'owner/app', 'dockerfile': 'Dockerfile'},
                       'legacy_baseline': {'runtime_manifest_digest': self.digest, 'source_sha': 'b' * 40,
                                           'alpine_version': '3.24.4', 'evidence_url': 'https://example/baseline'}}
        self.summary = {'scan_status': 'Success', 'report_id': 'report', 'complete_percent': 100,
                        'start_time': 900, 'end_time': 950}
        self.artifact = {'digest': self.digest, 'scan_overview': {'mime': self.summary}}
        self.row = {'id': 'CVE-2026-123', 'package': 'libxml2', 'version': '2.13.9-r2',
                    'fix_version': '2.13.9-r3', 'severity': 'High', 'artifact_digests': [self.digest]}
        self.report = {'generated_at': 940, 'scanner': {'name': 'Trivy'}, 'vulnerabilities': [self.row]}
        self.receipt = {'observation': {'deployment': {'image': 'registry.example/library/app:old'},
                                       'digests': [self.digest], 'pods': [{'image_id': 'registry.example/library/app@' + self.digest}]}}

    def execute(self, mutation=None):
        from unittest.mock import Mock
        api = Mock()
        api.contents.return_value = ('legacy Dockerfile', 'c' * 40)
        api.request.return_value = {'application/vnd.security.vulnerability.report; version=1.1': self.report}
        if mutation:
            mutation()
        with patch.object(m, 'now', return_value=1000), \
             patch.object(m, 'platform_artifact', return_value=(self.artifact, self.artifact, '/artifact')), \
             patch.object(m, 'harbor_artifact', return_value=(self.artifact, '/artifact')), \
             patch.object(m, 'read_apk_index', return_value={'versions': ['2.13.9-r3']}), \
             patch.object(m, 'official_secdb', return_value=({'2.13.9-r3': ['CVE-2026-123']}, {})), \
             patch.object(m, 'apk_less', side_effect=lambda a, b, cmd: a == '2.13.9-r2' and b == '2.13.9-r3'):
            return m.qualify(api, self.config, self.receipt)

    def test_exact_fresh_successful_os_fix_qualifies(self):
        value = self.execute()
        self.assertEqual(value['runtime_manifest_digest'], self.digest)
        self.assertEqual(value['fixes'][0]['fixed'], '2.13.9-r3')
        self.assertEqual(value['branch'], 'v3.24')

    def test_stale_failed_wrong_digest_or_unavailable_fix_rejected(self):
        mutations = [lambda: self.summary.update(scan_status='Error'),
                     lambda: self.summary.update(end_time=10),
                     lambda: self.row.update(artifact_digests=['sha256:' + 'd' * 64]),
                     lambda: self.report.update(generated_at=899),
                     lambda: self.report.update(scanner={'name': 'other'}),
                     lambda: self.row.update(fix_version='9.9-r0')]
        for mutate in mutations:
            self.setUp()
            with self.subTest(mutate=mutate), self.assertRaises(m.Rejected):
                self.execute(mutate)

    def test_empty_fix_queue_has_no_proposal(self):
        value = self.execute(lambda: self.report.update(vulnerabilities=[]))
        self.assertIsNone(value)

class RegistryAndGatesTests(unittest.TestCase):
    def test_single_platform_index_proves_runtime_parent_and_scan_child(self):
        digest = 'sha256:' + 'a' * 64
        child = 'sha256:' + 'b' * 64
        manifest = {'mediaType': 'application/vnd.oci.image.index.v1+json', 'manifests': [
            {'digest': child, 'platform': {'os': 'linux', 'architecture': 'amd64'}},
            {'digest': 'sha256:' + 'c' * 64, 'platform': {'os': 'unknown', 'architecture': 'unknown'},
             'annotations': {'vnd.docker.reference.type': 'attestation-manifest', 'vnd.docker.reference.digest': child}}]}
        from unittest.mock import Mock
        api = Mock()
        config = {'platform': 'linux/amd64'}
        def check():
            with patch.object(m, 'harbor_artifact', side_effect=[({'digest': digest}, '/parent'), ({'digest': child}, '/child')]), \
                 patch.object(m, 'registry_document', return_value=manifest), \
                 patch.object(m, 'registry_config', return_value={'os': 'linux', 'architecture': 'amd64'}):
                return m.platform_artifact(api, config, digest)
        parent, platform, path = check()
        self.assertEqual((parent['digest'], platform['digest'], path), (digest, child, '/child'))
        manifest['manifests'].append({'digest': child, 'platform': {'os': 'linux', 'architecture': 'arm64'}})
        with self.assertRaises(m.Rejected):
            check()
        manifest['manifests'].pop()
        manifest['manifests'][1]['annotations']['vnd.docker.reference.type'] = 'unknown'
        with self.assertRaises(m.Rejected):
            check()

    def test_registry_bytes_are_hashed_not_trusted_metadata(self):
        from unittest.mock import Mock
        api = Mock()
        api.request.return_value = b'{}'
        with patch.object(m, 'registry_headers', return_value={}):
            with self.assertRaises(m.Rejected):
                m.registry_document(api, {'harbor': {'repository': 'library/app'}}, 'sha256:' + 'a' * 64)

    def test_missing_or_new_failed_ci_blocks(self):
        from unittest.mock import Mock
        api = Mock()
        sha = 'a' * 40
        api.pages.return_value = [dict(commit_sha=sha, event='push', workflow_id='ci.yml', id=1, status='success', html_url='https://forgejo/run/1')]
        self.assertEqual(m.success_runs(api, 'owner/app', sha, 'push', ['ci.yml'])[0]['sha'], sha)
        api.pages.return_value.append(dict(commit_sha=sha, event='push', workflow_id='ci.yml', id=2, status='failure'))
        with self.assertRaises(m.Rejected):
            m.success_runs(api, 'owner/app', sha, 'push', ['ci.yml'])
        api.pages.return_value = []
        with self.assertRaises(m.Rejected):
            m.success_runs(api, 'owner/app', sha, 'push', ['ci.yml'])

    def test_read_auth_never_falls_back_for_write(self):
        api = m.HTTP({'proposal_enabled': True, 'source': {'repo': 'owner/app', 'dockerfile': 'Dockerfile'},
                      'forgejo': {'url': 'https://git.example', 'auth_command': ['broad-read-token']}})
        with patch.object(m, 'run') as run, patch.object(api, 'request') as request:
            with self.assertRaises(m.Rejected):
                api.forge('owner/app', '/pulls', {}, 'POST')
            with self.assertRaises(m.Rejected):
                api.forge('owner/app', '/pulls/1/merge', {}, 'POST')
            run.assert_not_called()
            request.assert_not_called()

    def test_empty_queue_and_verified_release_restart_do_not_retransmit(self):
        from unittest.mock import Mock
        candidate = {'expected_revision': 'master@sha1:' + 'a' * 40, 'desired_image': 'registry/app:tag',
                     'registry_evidence': {'runtime_manifest_digest': 'sha256:' + 'c' * 64}, 'producer_evidence': {'revision_sha': 'b' * 40}}
        key = m.identity({'revision': candidate['expected_revision'], 'image': candidate['desired_image'],
                          'registry': candidate['registry_evidence'], 'source': 'b' * 40})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'state.json'
            m.atomic_json(path, {'schema_version': 1, 'proposals': {}, 'verified': {key: {'receipt': 'retained'}}})
            with patch.object(m, 'observe', return_value={'observation': {'flux': {'revision': candidate['expected_revision']}, 'deployment': {'image': candidate['desired_image']}, 'digests': ['sha256:' + 'c' * 64]}}) as observe, \
                 patch.object(m, 'qualify', return_value=None), \
                 patch.object(m, 'propose') as propose, \
                 patch.object(m, 'release_candidate', return_value=candidate):
                value = m.tick({}, path)
                self.assertEqual(value['handoff'], 'already-verified')
                observe.assert_called_once_with({})
                propose.assert_not_called()

class ReleaseBindingTests(unittest.TestCase):
    def test_unrelated_later_commit_is_not_substituted_for_pin_release(self):
        from unittest.mock import Mock
        tip, merge, previous, source, producer = [letter * 40 for letter in 'abcde']
        image = 'registry.example/library/app:new'
        config = {'target': {}, 'forgejo': {'url': 'https://git.example'}, 'harbor': {'url': 'https://registry.example'},
                  'gitops': {'repo': 'owner/cluster', 'branch': 'master', 'image_file': 'app/kustomization.yaml',
                             'pr_status_contexts': ['check'], 'pr_workflows': ['ci.yml'], 'post_workflows': ['ci.yml']},
                  'source': {'repo': 'owner/app', 'branch': 'main', 'pr_status_contexts': ['check'],
                             'pr_workflows': ['ci.yml'], 'post_workflows': ['ci.yml'], 'post_status_contexts': ['publish-image']}}
        pr = {'merged': True, 'number': 7, 'merge_commit_sha': merge, 'base': {'ref': 'master'}, 'head': {'sha': source}}
        producer_pr = {'merged': True, 'number': 8, 'merge_commit_sha': producer, 'base': {'ref': 'main'}, 'head': {'sha': source}}
        api = Mock()
        def forge(repo, suffix):
            if suffix.startswith('/branches/'):
                return {'commit': {'id': tip}}
            if suffix.startswith('/git/commits/'):
                return {'parents': [{'sha': merge if suffix.endswith(tip) else previous}]}
            if suffix.endswith('/pull'):
                return pr if repo == 'owner/cluster' else producer_pr
            if suffix.startswith('/pulls/'):
                return pr
            if suffix.startswith('/branch_protections/'):
                return {'enable_status_check': True, 'status_check_contexts': ['check']}
            self.fail(suffix)
        api.forge.side_effect = forge
        def pages(repo, suffix):
            if suffix.startswith('/commits?'):
                return [{'sha': tip}, {'sha': merge}]
            return [pr] if repo == 'owner/cluster' else [producer_pr]
        api.pages.side_effect = pages
        api.iter_pages.side_effect = pages
        receipt = {'observation': {'flux': {'revision': 'master@sha1:' + tip}, 'digests': ['sha256:' + 'f' * 64]}}
        with patch.object(m, 'pin', side_effect=lambda api, cfg, ref: (image if ref != previous else image + '-old', 'f' * 40)), \
             patch.object(m, 'git_prepare', return_value=['git']), patch.object(m, 'git_ancestor', return_value='ahead'), \
             patch.object(m, 'workflow_policy'), patch.object(m, 'success_statuses', return_value=[]), \
             patch.object(m, 'success_runs', return_value=[{'status': 'success'}]), \
             patch.object(m, 'source_revision', return_value=producer), \
             patch.object(m, 'platform_artifact', return_value=({'digest': 'sha256:' + 'f' * 64}, {'digest': 'sha256:' + '0' * 64}, '/artifact')):
            value = m.release_candidate(api, config, receipt)
        self.assertEqual(value['release']['merge_sha'], merge)
        self.assertEqual(value['release']['gitops_revision_sha'], tip)
        self.assertEqual(value['expected_revision'], 'master@sha1:' + tip)
        self.assertEqual(value['producer_evidence']['revision_sha'], producer)
        self.assertEqual(value['registry_evidence']['runtime_manifest_digest'], 'sha256:' + 'f' * 64)

class ReplayTests(unittest.TestCase):
    def test_merged_bootstrap_waits_for_rollout_without_epoch_or_write(self):
        from unittest.mock import Mock
        contents = '''ARG PYTHON_BASE_IMAGE=library/python:3.14-alpine3.24
ARG APK_PATCH_EPOCH=2026-11-23
RUN test "${VERSION_ID%.*}" = "3.24" && apk list --installed libxml2
RUN apk version -t "${installed#libxml2-}" 2.13.9-r3
'''
        api = Mock()
        pr = {'merged': True, 'state': 'closed', 'base': {'ref': 'main'},
              'head': {'sha': 'b' * 40}, 'html_url': 'https://forgejo/pulls/10'}
        api.forge.side_effect = [{'commit': {'id': 'a' * 40}}, pr]
        api.contents.return_value = (contents, 'c' * 40)
        config = {'source': {'repo': 'owner/app', 'branch': 'main', 'dockerfile': 'Dockerfile'},
                  'legacy_baseline': {'producer_pr': 10, 'runtime_manifest_digest': 'sha256:' + 'd' * 64}}
        value = m.propose(api, config, {'platform_manifest_digest': 'sha256:' + 'd' * 64}, {'proposals': {}}, write=True)
        self.assertEqual(value['status'], 'bootstrap-merged-awaiting-rollout')
        self.assertEqual(api.forge.call_count, 2)
        self.assertTrue(all(len(call.args) == 2 for call in api.forge.call_args_list))

    def test_new_failed_status_supersedes_old_success(self):
        from unittest.mock import Mock
        api = Mock()
        sha = 'a' * 40
        api.forge.return_value = {'sha': sha}
        api.pages.return_value = [{'id': 1, 'sha': sha, 'context': 'publish-image', 'status': 'success', 'target_url': 'https://git/run/1'},
                                  {'id': 2, 'sha': sha, 'context': 'publish-image', 'status': 'failure', 'target_url': 'https://git/run/2'}]
        with self.assertRaises(m.Rejected):
            m.success_statuses(api, 'owner/app', sha, ['publish-image'])

    def test_stale_current_state_does_not_reuse_prior_verified_success(self):
        candidate = {'expected_revision': 'master@sha1:' + 'a' * 40, 'desired_image': 'registry/app:new',
                     'registry_evidence': {'runtime_manifest_digest': 'sha256:' + 'c' * 64},
                     'producer_evidence': {'revision_sha': 'b' * 40}}
        key = m.identity({'revision': candidate['expected_revision'], 'image': candidate['desired_image'],
                          'registry': candidate['registry_evidence'], 'source': 'b' * 40})
        old = {'observation': {'flux': {'revision': candidate['expected_revision']}, 'deployment': {'image': 'registry/app:old'}, 'digests': ['sha256:' + 'c' * 64]}}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'state.json'
            m.atomic_json(path, {'schema_version': 1, 'proposals': {}, 'verified': {key: {'receipt': 'historic'}}})
            with patch.object(m, 'observe', side_effect=[old, {'verified_release': False, 'status': 'failed'}]) as observe, \
                 patch.object(m, 'qualify', return_value=None), patch.object(m, 'release_candidate', return_value=candidate), \
                 patch.object(m, 'registry_unchanged'):
                value = m.tick({}, path)
        self.assertEqual(value['handoff'], 'pending')
        self.assertEqual(value['status'], 'blocked')
        self.assertEqual(observe.call_count, 2)
