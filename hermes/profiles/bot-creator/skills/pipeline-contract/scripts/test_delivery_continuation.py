"""Offline instruction/fixture checks, NOT runtime or model enforcement."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class DeliveryContinuation(unittest.TestCase):
    def test_terminal_checklist_and_synthetic_dispositions(self):
        text = (ROOT / 'references/outcome-continuation.md').read_text()
        self.assertIn('## Accepted-local terminal checklist (before actual turn exit)', text)
        fixtures = {
            'source Done; original mode unmet': 'delivery_pending; prepare and present, not outcome closed',
            'packet saved; gate silent': 'delivery_pending; present in this turn, not presentation complete',
            'gate sent; receipt absent': 'delivery_pending; presentation unverified, retain pending receipt',
            'gate presented; no approval': 'delivery_pending; await authentic scoped approval',
            'approved exact execution; prerequisites valid': 'delivery_pending; admit authorized execution and verify requested level',
            'requested level verified; no higher original requirement': 'outcome may close with exact acceptance evidence',
            'user explicitly requests local-only final outcome': 'local closure allowed after exact local acceptance',
            'source stage local-only; original delivery intent retained': 'delivery_pending; stage restriction is not final-outcome waiver',
            'auto-deploy triggers UNKNOWN': 'delivery_pending; visible bounded prerequisite, no runnable publication mode',
            'unchanged gate already presented; duplicate event': 'verified no-op; reuse receipt, no resend or admission',
            'unchanged silent gate; duplicate event': 'delivery_pending; missing presentation still due',
        }
        for state, disposition in fixtures.items():
            with self.subTest(state=state):
                self.assertIn(f'| {state} | {disposition} |', text)
        for clause in ['original user intent', 'mode/requested evidence level',
                       'real user-visible message/history reference',
                       'subscription readback before release',
                       'No acceptance-comment-only stop',
                       'No self-wake', 'actual denial', 'cumulative budget']:
            self.assertIn(clause, text)
        skill = (ROOT / 'SKILL.md').read_text()
        self.assertIn('accepted-local terminal checklist', skill)
        self.assertIn('delivery_pending', skill)

if __name__ == '__main__':
    unittest.main(verbosity=2)
