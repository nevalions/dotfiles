"""Signed epoch-only proposal fixtures; no services or persistent keys."""
import base64
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

SOURCE = Path(__file__).resolve().parents[1] / 'pi/.pi/agent/yt-maintenance/proposal_signing.py'
spec = importlib.util.spec_from_file_location('yt_signing', SOURCE)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


CLOCK = 1795435200


def protection(base='1'*40, issued=CLOCK):
    return {'repository':'nevalions/yt-downloader','branch':'main','base_sha':base,'checked_at':issued,
            'apply_to_admins':True,'block_on_outdated_branch':True,'enable_status_check':True,
            'status_check_contexts':sorted(m.REQUIRED_CONTEXTS)}


def qualification():
    value = {'deployed_image': 'registry.example/library/app:old', 'runtime_manifest_digest': 'sha256:' + 'a' * 64, 'manifest_digest': 'sha256:' + 'a' * 64,
             'platform_manifest_digest': 'sha256:' + 'b' * 64, 'platform': 'linux/amd64',
             'source_sha': 'c' * 40, 'source_blob': 'd' * 40, 'branch': 'v3.24', 'package': 'libxml2',
             'scan_report_id': 'report1', 'scan_generated_at': CLOCK - 60, 'scan_end_time': CLOCK - 59,
             'fixes': [{'id': 'CVE-2026-86144', 'installed': '2.13.9-r2', 'fixed': '2.13.9-r3', 'available': ['2.13.9-r3']}],
             'apk_index': {'architecture': 'x86_64', 'versions': ['2.13.9-r3'], 'url': 'https://dl-cdn.alpinelinux.org/alpine/v3.24/main/x86_64/APKINDEX.tar.gz', 'sha256': 'e' * 64, 'fetched_at': CLOCK - 10},
             'secdb': {'url': 'https://secdb.alpinelinux.org/v3.24/main.json', 'sha256': 'f' * 64, 'fetched_at': CLOCK - 10}}
    value['qualification_id'] = hashlib.sha256(json.dumps({k: value[k] for k in ('runtime_manifest_digest', 'platform', 'branch', 'package', 'fixes')},sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return value


class SigningTests(unittest.TestCase):
    def setUp(self):
        self.before = 'ARG APK_PATCH_EPOCH=2026-11-22\nRUN echo unchanged\n'
        self.after = self.before.replace('2026-11-22', '2026-11-23')
        self.q = qualification()
        self.branch = 'maintenance/apk-' + self.q['qualification_id'][:20]

    def payload(self):
        return m.bound_payload(self.q, self.branch, '1' * 40, '2' * 40, 123, self.before, self.after, issued=CLOCK, lifetime=900, protection=protection())

    def test_signed_raw_bytes_verify_and_expiry_is_bounded(self):
        key = Ed25519PrivateKey.generate()
        payload = self.payload()
        body = m.signed_comment(payload, key)
        decoded = m.verify_comment(body, key.public_key(), at=CLOCK+200)
        self.assertEqual(decoded, payload)
        with self.assertRaises(m.SigningError):
            m.verify_comment(body, key.public_key(), at=CLOCK+901)
        with self.assertRaises(m.SigningError):
            m.verify_comment(body, Ed25519PrivateKey.generate().public_key(), at=CLOCK+200)

    def test_arbitrary_diff_wrong_branch_or_stale_evidence_rejected(self):
        cases = [lambda: setattr(self, 'after', self.after + 'RUN extra\n'),
                 lambda: setattr(self, 'branch', 'feature/human-change'),
                 lambda: self.q['apk_index'].update(fetched_at=1),
                 lambda: self.q.update(platform='linux/arm64'),
                 lambda: self.q.update(qualification_id='0' * 64),
                 lambda: self.q.update(platform_manifest_digest='bad'),
                 lambda: self.q['secdb'].update(url='https://untrusted.example/main.json')]
        for mutate in cases:
            self.setUp()
            mutate()
            with self.subTest(mutate=mutate), self.assertRaises(m.SigningError):
                self.payload()

    def test_payload_binding_and_comment_tampering_rejected(self):
        key = Ed25519PrivateKey.generate()
        payload = self.payload()
        body = m.signed_comment(payload, key)
        envelope = json.loads(body.split('\n')[1])
        raw = json.loads(base64.b64decode(envelope['payload']))
        raw['head_sha'] = '9' * 40
        envelope['payload'] = base64.b64encode(json.dumps(raw).encode()).decode()
        tampered = '<!-- yt-os-refresh-v1\n' + json.dumps(envelope) + '\n-->'
        with self.assertRaises(m.SigningError):
            m.verify_comment(tampered, key.public_key(), at=CLOCK+200)
        with self.assertRaises(m.SigningError):
            m.bound_payload(self.q,self.branch,'1'*40,'2'*40,123,self.before,self.after,issued=CLOCK,lifetime=901,protection=protection())

    def test_private_key_permissions_and_fingerprint_required(self):
        key = Ed25519PrivateKey.generate()
        public = key.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)
        fingerprint = hashlib.sha256(public).hexdigest()
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'key.pem'
            p.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
            p.chmod(0o600)
            m.load_private(p,fingerprint)
            p.chmod(0o644)
            with self.assertRaises(m.SigningError):
                m.load_private(p,fingerprint)
            p.chmod(0o600)
            with self.assertRaises(m.SigningError):
                m.load_private(p,'0'*64)

    def test_future_and_unchanged_epochs_remain_forbidden(self):
        for after in (self.before, self.after.replace('2026-11-23','2026-11-24')):
            with self.subTest(after=after), self.assertRaises(m.SigningError):
                m.bound_payload(self.q,self.branch,'1'*40,'2'*40,123,self.before,after,issued=CLOCK,protection=protection())


class ControllerSigningTests(unittest.TestCase):
    def setUp(self):
        from unittest.mock import Mock
        path = SOURCE.parent / 'controller.py'
        spec = importlib.util.spec_from_file_location('signing_controller', path)
        self.c = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.c)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.key = Ed25519PrivateKey.generate()
        p = Path(self.tmp.name) / 'key.pem'
        p.write_bytes(self.key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
        p.chmod(0o600)
        public = self.key.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)
        self.config = {'signing_enabled': True, 'proposal_enabled': True, 'source': {
            'repo': 'nevalions/yt-downloader', 'branch': 'main', 'dockerfile': 'Dockerfile',
            'proposal_actor': 'yt-proposer', 'signing_key_file': str(p),
            'signing_public_key_sha256': hashlib.sha256(public).hexdigest()}}
        self.q = qualification()
        self.branch = 'maintenance/apk-' + self.q['qualification_id'][:20]
        self.base, self.head = '1' * 40, '2' * 40
        self.before = '''ARG PYTHON_BASE_IMAGE=library/python:3.14-alpine3.24
ARG APK_PATCH_EPOCH=2026-11-22
RUN test "${VERSION_ID%.*}" = "3.24" && apk list --installed libxml2
RUN apk version -t "${installed#libxml2-}" 2.13.9-r3
'''
        self.after = self.before.replace('2026-11-22','2026-11-23')
        self.record = {'owned': True, 'pr': 123, 'branch': self.branch, 'base_sha': self.base, 'head_sha': self.head}
        self.pr = {'number': 123, 'state': 'open', 'merged': False, 'user': {'login': 'yt-proposer'},
                   'html_url': 'https://git.example/pulls/123', 'base': {'ref': 'main', 'sha': self.base, 'repo': {'full_name': 'nevalions/yt-downloader'}},
                   'head': {'ref': self.branch, 'sha': self.head, 'repo': {'full_name': 'nevalions/yt-downloader'}}}
        self.api = Mock()
        self.comments = {}
        self.mutations = []
        self.api.forge.side_effect = self.forge
        self.api.contents.side_effect = lambda repo,path,ref: (self.before if ref == self.base else self.after,'f'*40)
        self.api.pages.return_value = [{'filename': 'Dockerfile', 'status': 'modified'}]
        self.observation = {'observation': {'flux': {}, 'deployment': {}, 'digests': ['sha256:'+'a'*64]}}

    def forge(self,repo,suffix,body=None,method='GET'):
        if method != 'GET':
            self.mutations.append((method,suffix,body))
        if suffix == '/branches/main':
            return {'name':'main','commit': {'id': self.base},'protected':True,'enable_status_check':True,
                    'effective_branch_protection_name':'main','status_check_contexts':list(m.REQUIRED_CONTEXTS)}
        if suffix == '/branch_protections/main':
            return {'branch_name':'main','rule_name':'main','apply_to_admins':True,'block_on_outdated_branch':True,
                    'enable_status_check':True,'status_check_contexts':list(m.REQUIRED_CONTEXTS)}
        if suffix == '/pulls/123':
            return copy.deepcopy(self.pr)
        if suffix == '/issues/123/comments' and method == 'GET':
            return list(self.comments.values())
        if suffix == '/issues/123/comments' and method == 'POST':
            value = {'id': 99, 'body': body['body'], 'user': {'login': 'yt-proposer'}}
            self.comments[99] = value
            return value
        if suffix == '/issues/comments/99':
            if method == 'PATCH':
                self.comments[99] = {'id': 99, 'body': body['body'], 'user': {'login': 'yt-proposer'}}
            return self.comments[99]
        self.fail((method,suffix))

    def refresh(self, checkpoint=None, at=CLOCK):
        with patch.object(self.c,'now',return_value=at), patch.object(self.c,'signing_module',return_value=m), \
             patch.object(self.c,'git_prepare',return_value=['git']), patch.object(self.c,'only_source_file'), \
             patch.object(self.c,'observe',return_value=self.observation) as observe, \
             patch.object(self.c,'qualify',return_value=self.q) as qualify:
            result = self.c.refresh_proof(self.api,self.config,self.q,self.record,checkpoint or (lambda:None))
            self.assertEqual(qualify.call_count,1)
            self.assertEqual(observe.call_count,2)
            return result

    def test_owned_current_pr_gets_issue_comment_then_refresh_without_ci_body_edits(self):
        result = self.refresh()
        self.assertTrue(result['signed'])
        proof = m.verify_comment(self.comments[99]['body'],self.key.public_key(),at=CLOCK)
        self.assertEqual(proof['base_sha'],self.base)
        self.assertEqual(proof['head_sha'],self.head)
        self.assertEqual(proof['pr_number'],123)
        self.refresh()
        self.assertEqual([x[:2] for x in self.mutations], [('POST','/issues/123/comments'),('PATCH','/issues/comments/99')])

    def test_human_unowned_changed_head_or_other_file_never_signed(self):
        cases = [lambda: self.record.update(owned=False), lambda:self.pr['user'].update(login='human'),
                 lambda:self.pr['head'].update(sha='9'*40),
                 lambda:self.api.pages.return_value.append({'filename':'other','status':'modified'})]
        for mutate in cases:
            self.setUp()
            mutate()
            with self.subTest(mutate=mutate), self.assertRaises(self.c.Rejected):
                self.refresh()
            self.assertEqual(self.mutations,[])

    def test_refresh_requalifies_and_rejects_changed_production_fix(self):
        other = qualification()
        other['qualification_id'] = '0'*64
        with patch.object(self.c,'signing_module',return_value=m), patch.object(self.c,'git_prepare',return_value=['git']), \
             patch.object(self.c,'only_source_file'), patch.object(self.c,'observe',return_value=self.observation), \
             patch.object(self.c,'qualify',return_value=other):
            with self.assertRaises(self.c.Rejected):
                self.c.refresh_proof(self.api,self.config,self.q,self.record,lambda:None)
        self.assertEqual(self.mutations,[])

    def test_base_drift_rebases_only_owned_valid_diff_and_binds_actual_new_head(self):
        old_base, old_head = self.base, self.head
        current_base, rebased_head = '3'*40, '4'*40
        current_before = self.before + 'RUN echo updated-main\n'
        current_after = current_before.replace('2026-11-22','2026-11-23')
        original_forge = self.forge
        def forge(repo,suffix,body=None,method='GET'):
            if suffix == '/branches/main':
                return {'name':'main','commit': {'id':current_base},'protected':True,'enable_status_check':True,
                        'effective_branch_protection_name':'main','status_check_contexts':list(m.REQUIRED_CONTEXTS)}
            if suffix == '/pulls/123/update?style=rebase':
                self.mutations.append((method,suffix,body))
                self.pr['head']['sha'] = rebased_head
                return None
            return original_forge(repo,suffix,body,method)
        self.api.forge.side_effect = forge
        content = {old_base:self.before,old_head:self.after,current_base:current_before,rebased_head:current_after}
        self.api.contents.side_effect = lambda repo,path,ref:(content[ref],'f'*40)
        with patch.object(self.c,'git_ancestor',return_value='ahead'):
            result = self.refresh()
        self.assertEqual(result['head_sha'],rebased_head)
        self.assertEqual(result['base_sha'],current_base)
        proof = m.verify_comment(self.comments[99]['body'],self.key.public_key(),at=CLOCK)
        self.assertEqual(proof['head_sha'],rebased_head)
        self.assertEqual(proof['before_sha256'],hashlib.sha256(current_before.encode()).hexdigest())
        self.assertEqual([x[:2] for x in self.mutations],[('POST','/pulls/123/update?style=rebase'),('POST','/issues/123/comments')])

    def test_executable_or_symlink_git_file_cannot_be_signed(self):
        for mode in ('100755','120000'):
            with patch.object(self.c,'run',side_effect=['Dockerfile\n',mode+' blob '+'f'*40+'\tDockerfile\n']):
                with self.assertRaises(self.c.Rejected):
                    self.c.only_source_file(['git'],self.base,self.head,'Dockerfile')

    def test_crash_after_pr_post_recovers_only_persisted_exact_creation_intent(self):
        class Crash(RuntimeError):
            pass
        self.config['signing_enabled'] = False
        self.config['source'].update(proposal_auth_command=['private-helper'],commit_author={'name':'Operator','email':'operator@example.com'})
        state = {'proposals': {}}
        durable = {}
        created = False
        original = self.forge
        def forge(repo,suffix,body=None,method='GET'):
            nonlocal created
            if method == 'POST' and suffix == '/branches':
                self.mutations.append((method,suffix,body))
                return {}
            if method == 'PUT' and suffix == '/contents/Dockerfile':
                self.mutations.append((method,suffix,body))
                return {'commit': {'sha':self.head}}
            if method == 'POST' and suffix == '/pulls':
                self.mutations.append((method,suffix,body))
                created = True
                return copy.deepcopy(self.pr)
            return original(repo,suffix,body,method)
        self.api.forge.side_effect = forge
        self.api.pages.side_effect = lambda repo,suffix: ([copy.deepcopy(self.pr)] if created else []) if suffix == '/pulls?state=open' else ([] if suffix == '/branches' else [{'filename':'Dockerfile','status':'modified'}])
        def checkpoint():
            nonlocal durable
            if state['proposals'].get(self.q['qualification_id'],{}).get('owned'):
                raise Crash('PR succeeded; owned checkpoint interrupted')
            durable = copy.deepcopy(state)
        with patch.object(self.c,'datetime') as clock, patch.object(self.c,'git_prepare',return_value=['git']), patch.object(self.c,'only_source_file'):
            clock.now.return_value.date.return_value.isoformat.return_value = '2026-11-23'
            with self.assertRaises(Crash):
                self.c.propose(self.api,self.config,self.q,state,write=True,checkpoint=checkpoint)
        intent = durable['proposals'][self.q['qualification_id']]
        self.assertTrue(intent['post_ready'])
        self.assertEqual(intent['head_sha'],self.head)
        self.assertFalse(intent.get('owned',False))
        self.config['signing_enabled'] = True
        with patch.object(self.c,'now',return_value=CLOCK), patch.object(self.c,'signing_module',return_value=m), \
             patch.object(self.c,'git_prepare',return_value=['git']), patch.object(self.c,'only_source_file'), \
             patch.object(self.c,'observe',return_value=self.observation) as observe, patch.object(self.c,'qualify',return_value=self.q) as qualify:
            result = self.c.propose(self.api,self.config,self.q,durable,write=True,checkpoint=lambda:None)
        self.assertTrue(result['owned'])
        self.assertTrue(result['signed'])
        self.assertEqual(qualify.call_count,2)
        self.assertEqual(observe.call_count,4)
        self.assertEqual(sum(method=='POST' and path=='/pulls' for method,path,_ in self.mutations),1)
        self.assertEqual(durable['proposals'][self.q['qualification_id']]['pr'],123)

    def test_recovery_rejects_intent_head_actor_base_or_bytes_mismatch(self):
        valid = {'intent':True,'post_ready':True,'repository':'nevalions/yt-downloader',
                 'proposal_actor':'yt-proposer','branch':self.branch,'base_sha':self.base,'head_sha':self.head,
                 'proposed_sha256':hashlib.sha256(self.after.encode()).hexdigest()}
        for field,value in [('head_sha','9'*40),('base_sha','9'*40),('proposal_actor','human'),
                            ('proposed_sha256','0'*64),('post_ready',False)]:
            intent = dict(valid,**{field:value})
            with self.subTest(field=field), patch.object(self.c,'git_prepare',return_value=['git']), \
                 patch.object(self.c,'only_source_file'), self.assertRaises(self.c.Rejected):
                self.c.recover_proposal(self.api,self.config,self.q,intent,self.pr,lambda:None)
        self.assertEqual(self.mutations,[])

    def test_crash_after_comment_post_adopts_authentic_proof_without_duplicate_post(self):
        class Crash(RuntimeError):
            pass
        durable = {}
        def checkpoint():
            nonlocal durable
            if self.record.get('signed'):
                raise Crash('comment exists; signed checkpoint interrupted')
            durable = copy.deepcopy(self.record)
        with self.assertRaises(Crash):
            self.refresh(checkpoint)
        self.assertNotIn('comment_id',durable)
        self.assertIn('pending_comment_body',durable)
        self.assertEqual(len(self.comments),1)
        self.record = durable
        result = self.refresh()
        self.assertTrue(result['signed'])
        self.assertEqual(result['comment_id'],99)
        self.assertEqual([x[:2] for x in self.mutations],[('POST','/issues/123/comments'),('PATCH','/issues/comments/99')])

    def test_comment_recovery_rejects_wrong_key_and_other_head(self):
        payload = m.bound_payload(self.q,self.branch,self.base,self.head,123,self.before,self.after,issued=CLOCK,protection=protection())
        comment = {'id':88,'user':{'login':'yt-proposer'},'body':m.signed_comment(payload,Ed25519PrivateKey.generate())}
        self.assertFalse(self.c.matching_signed_comment(m,self.key,comment,payload,'yt-proposer'))
        wrong = dict(payload,head_sha='9'*40)
        comment['body'] = m.signed_comment(wrong,self.key)
        self.assertFalse(self.c.matching_signed_comment(m,self.key,comment,payload,'yt-proposer'))


    def test_owned_prior_day_patch_refreshes_with_fresh_overnight_qualification(self):
        self.refresh()
        overnight = CLOCK + 86400
        for field in ('apk_index','secdb'):
            self.q[field]['fetched_at'] = overnight - 10
        result = self.refresh(at=overnight)
        proof = m.verify_comment(self.comments[99]['body'],self.key.public_key(),at=overnight)
        self.assertTrue(result['signed'])
        self.assertEqual(proof['new_epoch'],'2026-11-23')
        self.assertEqual(proof['issued_at'],overnight)
        self.assertEqual(proof['head_sha'],self.head)
        self.assertEqual(proof['after_sha256'],hashlib.sha256(self.after.encode()).hexdigest())
        self.assertEqual([x[:2] for x in self.mutations],[('POST','/issues/123/comments'),('PATCH','/issues/comments/99')])

    def test_signed_protection_rejects_bad_flags_stale_identity_or_extra_fields(self):
        invalid = [dict(protection(),apply_to_admins=False), dict(protection(),block_on_outdated_branch=1),
                   dict(protection(),enable_status_check=False), dict(protection(),repository='other/repo'),
                   dict(protection(),branch='other'),dict(protection(),base_sha='9'*40),
                   dict(protection(),checked_at=CLOCK-901),dict(protection(),checked_at=CLOCK+1),
                   dict(protection(),checked_at='2026-11-23T12:00:00Z'),dict(protection(),extra='unexpected'),
                   dict(protection(),status_check_contexts=sorted(m.REQUIRED_CONTEXTS)[:-1]),
                   dict(protection(),status_check_contexts=sorted(m.REQUIRED_CONTEXTS)+[m.REQUIRED_CONTEXTS[0]])]
        missing = protection()
        missing.pop('apply_to_admins')
        invalid.append(missing)
        for value in invalid:
            with self.subTest(value=value),self.assertRaises(m.SigningError):
                m.bound_payload(self.q,self.branch,self.base,self.head,123,self.before,self.after,issued=CLOCK,protection=value)

    def test_protection_collector_uses_live_effective_exact_rule_and_rechecks_base(self):
        with patch.object(self.c,'now',return_value=CLOCK),patch.object(self.c,'signing_module',return_value=m):
            result = self.c.protection_snapshot(self.api,self.config,self.base)
        self.assertEqual(result,protection(self.base,CLOCK))
        paths=[call.args[1] for call in self.api.forge.call_args_list]
        self.assertEqual(paths,['/branches/main','/branch_protections/main','/branches/main'])
        original = self.forge
        def hidden(repo,path,body=None,method='GET'):
            value = original(repo,path,body,method)
            if path == '/branches/main':
                value['effective_branch_protection_name']=''
            return value
        self.api.forge.side_effect=hidden
        with patch.object(self.c,'signing_module',return_value=m),self.assertRaises(self.c.Rejected):
            self.c.protection_snapshot(self.api,self.config,self.base)
        self.assertEqual(self.mutations,[])

    def test_fresh_signature_cannot_hide_stale_or_wrong_protection(self):
        payload=m.bound_payload(self.q,self.branch,self.base,self.head,123,self.before,self.after,issued=CLOCK,protection=protection())
        for field,value in [('checked_at',CLOCK-901),('base_sha','9'*40),('apply_to_admins',False)]:
            bad=copy.deepcopy(payload)
            bad['protection'][field]=value
            body=m.signed_comment(bad,self.key)
            with self.subTest(field=field),self.assertRaises(m.SigningError):
                m.verify_comment(body,self.key.public_key(),at=CLOCK)

class SiteSigningTests(SigningTests):
    def test_site_proofs_bind_repository_image_master_and_exact_ci(self):
        key = Ed25519PrivateKey.generate()
        for repo, (branch, app) in m.SITE_POLICIES.items():
            q = qualification()
            q['deployed_image'] = 'registry.example/library/' + app + '-frontend:old'
            proof = protection()
            proof.update(repository=repo, branch=branch, status_check_contexts=['CI / build (pull_request)'])
            payload = m.bound_payload(q, self.branch, '1'*40, '2'*40, 123, self.before, self.after,
                                      issued=CLOCK, protection=proof, repository=repo)
            body = m.signed_comment(payload, key)
            self.assertEqual(m.verify_comment(body, key.public_key(), at=CLOCK+1, repository=repo), payload)
            for other in set(m.SITE_POLICIES) - {repo}:
                with self.assertRaises(m.SigningError):
                    m.verify_comment(body, key.public_key(), at=CLOCK+1, repository=other)
            with self.assertRaises(m.SigningError):
                m.verify_comment(body, key.public_key(), at=CLOCK+1)
            proof['status_check_contexts'] = []
            with self.assertRaises(m.SigningError):
                m.bound_payload(q, self.branch, '1'*40, '2'*40, 123, self.before, self.after,
                                issued=CLOCK, protection=proof, repository=repo)
