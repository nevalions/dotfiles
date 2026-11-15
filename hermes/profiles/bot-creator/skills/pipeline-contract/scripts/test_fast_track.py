"""Offline selection/packet checks only, not native admission or authority."""
import copy
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class FastTrack(unittest.TestCase):
    def test_representative_packet_and_risk_matrix(self):
        self.assertTrue((ROOT / 'references/fast-track.md').exists(), 'selection contract missing')
        ref = (ROOT / 'references/fast-track.md').read_text()
        packet = json.loads(ref.split('```json\n', 1)[1].split('\n```', 1)[0])
        from fast_track_packet import validate, select
        self.assertEqual([], validate(packet))
        for key in packet:
            changed = copy.deepcopy(packet)
            del changed[key]
            self.assertTrue(validate(changed), key)
        for kind in ('typo', 'broken_link', 'isolated_fix'):
            with self.subTest(kind=kind):
                self.assertEqual('fast', select(kind, True, True, True, [], []))
        for risk in ('auth', 'rbac', 'credentials', 'approval', 'model_routing', 'ci',
                     'installer', 'migration', 'dependency', 'production', 'hook',
                     'core', 'ops_runbook', 'security_docs', 'schema',
                     'unknown_automation', 'auto_deploy_publication'):
            with self.subTest(risk=risk):
                self.assertEqual('standard', select('typo', True, True, True, [risk], []))
        for args in [('isolated_fix', False, True, True, [], []),
                     ('typo', True, False, True, [], []),
                     ('typo', True, True, False, [], []),
                     ('typo', True, True, True, [], ['publishing unknown'])]:
            self.assertEqual('standard', select(*args))
        for key, value in [('required_stages', ['author_targeted_tests', 'authorized_delivery']),
                           ('reviewer', packet['author']), ('same_card', False),
                           ('delivery_mode', 'deployed'), ('reason', ''),
                           ('track', 'fast'), ('unknowns', ['cause unknown'])]:
            changed = copy.deepcopy(packet)
            changed[key] = value
            if key == 'track':
                changed['risks'] = ['ci']
            self.assertTrue(validate(changed), key)

if __name__ == '__main__':
    unittest.main(verbosity=2)
