from datetime import datetime, timedelta, timezone
from pathlib import Path
import runpy
import unittest

module = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'pi/.pi/agent/bin/pi_team_delivery.py'))
advance = module['advance']
DeliveryError = module['DeliveryError']
HEAD, BASE, MERGED = 'a' * 40, 'b' * 40, 'c' * 40


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now(timezone.utc)
        self.grant = dict(host='git.butakov.su', repo='owner/pilot', pr=4, head_sha=HEAD,
                          base_sha=BASE, base_ref='main', pr_checks=['test'],
                          post_merge_checks=['publish'], expires_at=(self.now + timedelta(minutes=30)).isoformat())
        self.pr = dict(number=4, state='open', merged=False, draft=False,
                       head={'sha': HEAD}, base={'ref': 'main', 'sha': BASE})
        self.branch = {'name': 'main', 'protected': True, 'commit': {'id': BASE}}
        self.head_status = 'success'
        self.merged_status = 'pending'
        self.parents = [{'sha': BASE}]
        self.merges = []

    def get(self, route):
        if route == f'commits/{HEAD}/status':
            return {'sha': HEAD, 'statuses': [{'context': 'test', 'status': self.head_status}]}
        if route == f'commits/{MERGED}/status':
            return {'sha': MERGED, 'statuses': [{'context': 'publish', 'status': self.merged_status}]}
        return {'pulls/4': self.pr, 'branches/main': self.branch,
                f'git/commits/{MERGED}': {'sha': MERGED, 'parents': self.parents}}[route]

    def merge(self, route, data):
        self.merges.append((route, data))
        self.pr.update(state='closed', merged=True, merge_commit_sha=MERGED)

    def step(self):
        return advance(self.grant, self.get, self.merge, self.now)

    def test_pending_then_merge_once_then_verify_on_restart(self):
        self.head_status = 'pending'
        self.assertEqual(self.step()['status'], 'pending')
        self.assertFalse(self.merges)
        self.head_status = 'success'
        self.assertEqual(self.step()['status'], 'pending')
        self.assertEqual(self.merges, [('pulls/4/merge', {
            'Do': 'squash', 'head_commit_id': HEAD, 'delete_branch_after_merge': False,
        })])
        self.merged_status = 'success'
        self.assertEqual(self.step()['status'], 'verified')
        self.assertEqual(len(self.merges), 1)

    def test_stale_head_base_failed_check_and_expiry_do_not_merge(self):
        self.pr['head']['sha'] = MERGED
        self.assertEqual(self.step()['reason'], 'head_sha_mismatch')
        self.pr['head']['sha'] = HEAD
        self.branch['commit']['id'] = MERGED
        self.assertEqual(self.step()['reason'], 'base_tip_mismatch')
        self.branch['commit']['id'] = BASE
        self.head_status = 'failure'
        self.assertEqual(self.step()['reason'], 'pr_checks_failed')
        self.grant['expires_at'] = self.now.isoformat()
        self.assertEqual(self.step()['reason'], 'grant_expired')
        self.assertFalse(self.merges)

    def test_unprotected_branch_and_unapproved_squash_parent_fail_closed(self):
        self.branch['protected'] = False
        with self.assertRaisesRegex(DeliveryError, 'server-protected'):
            self.step()
        self.assertFalse(self.merges)
        self.branch['protected'] = True
        self.parents = [{'sha': HEAD}]
        with self.assertRaisesRegex(DeliveryError, 'squash parent'):
            self.step()
        with self.assertRaisesRegex(DeliveryError, 'squash parent'):
            self.step()
        self.assertEqual(len(self.merges), 1)

    def test_check_regression_before_post_blocks_merge(self):
        def get(route):
            result = self.get(route)
            if route == f'commits/{HEAD}/status':
                self.head_status = 'failure'
            return result

        result = advance(self.grant, get, self.merge, self.now)
        self.assertEqual(result['reason'], 'pr_checks_changed_before_merge')
        self.assertFalse(self.merges)


if __name__ == '__main__':
    unittest.main()
