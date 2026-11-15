"""Document-contract checks ONLY. Passing is not runtime enforcement."""
import os
from pathlib import Path
import unittest

SKILL = Path(os.environ.get('PIPELINE_SCRIPTS',
    '/home/linroot/.hermes/profiles/bot-creator/skills/pipeline-contract/scripts')).parent

CONTRACTS = {
    'full_admission_auth_ci_protection_deploy': ('admission-preflight.md', [
        'non-secret authentication capability', 'live protection', 'actual required CI contexts',
        'auto-deploy triggers', 'precede ANY publication', 'EVERY current-stage critical row',
        'Required stage inputs cannot be deferred']),
    'exact_evidence_reuse_and_fresh_boundary': ('admission-preflight.md', [
        'digest AND schema/policy version', 'Revalidate only affected evidence',
        'authority/revocation/window', 'worker idleness', 'target state/protection/CI',
        'Final required candidate gates remain mandatory']),
    'independent_parallel_vs_dependent_order': ('admission-preflight.md', [
        'Batch independent read-only prerequisites', 'disjoint ownership', 'no shared writes',
        'authorized fan-out', 'approval-then-execution', 'candidate mutation-then-review',
        'remain ordered']),
    'duplicate_and_ambiguous_side_effects': ('outcome-continuation.md', [
        'duplicate/out-of-order', 'Stable action identity', 'Event ID alone is not a dispatch key',
        'in-flight or verified action is reconciled, not repeated',
        'Ambiguous release/send/write => uncertain', 'inspect exact target before any retry',
        'Do not repeat an entire script', 'own-comment observations need no new comment',
        'Comments are not CAS or leases']),
    'bounded_recovery': ('outcome-continuation.md', [
        'One evidence-changing local recovery per blocker', 'after verified idle',
        'unchanged/exhausted blocker stays parked', 'no replacement-card or renamed-phase reset',
        'Actual denial => stop', 'owner and resume condition']),
    'complete_input_primary_and_separate_fault': ('coordinator-management.md', [
        'Never admit the primary chain with a missing mandatory input',
        'separately authorized as a post-admission fault', 'one injected fault',
        'Permit at most one bounded recovery', 'not primary-chain acceptance']),
}

class DocumentContract(unittest.TestCase):
    def test_required_clauses_are_retained_NOT_behavior(self):
        for name, (reference, clauses) in CONTRACTS.items():
            text = (SKILL/'references'/reference).read_text()
            for clause in clauses:
                with self.subTest(contract=name, clause=clause):
                    self.assertIn(clause, text)

if __name__ == '__main__': unittest.main(verbosity=2)
