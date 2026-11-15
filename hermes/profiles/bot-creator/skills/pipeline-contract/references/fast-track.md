# FAST TRACK — stage selection, not reduced assurance

Canonical non-worker Orchestrator uses this intake/acceptance rubric for simple fixes and docs. It is a recommendation procedure, not a worker, new bot, scheduler, model choice or native enforcement. Existing [foundations](workflow-foundations.md), [admission preflight](admission-preflight.md), [review guard](review-loop-guard.md), [reviewer binding](explicit-reviewer-binding.md), [delivery](delivery-factory.md) and [outcome continuation](outcome-continuation.md) remain authoritative. Load the applicable maintained sources; this packet supplements, never replaces, their evidence schemas.

## Decision rubric

Choose **fast** only when ALL hold: known cause supported by evidence; bounded owned scope; small reversible delta with a clear rollback; focused acceptance checks; no unresolved material unknowns; no excluded risk. Size is semantic/blast-radius based, never an arbitrary LOC cutoff.

Eligible examples: a spelling typo in nonexecutable prose, a broken documentation link with known replacement, or an isolated causal fix with a focused regression. Docs must not change executable instructions, operational runbooks or security behavior. An executable example is not automatically prose.

Choose **standard** for auth, RBAC, credentials, approval, model routing, CI, installer, migration, dependency, production, hook/core changes, schema changes, operations runbooks, security docs, unknown automation or auto-deploying publication. A deployment runbook, schema/installer fix or docs push that deploys is not fast merely because its diff is small. Inspect publishing/build triggers before selecting; unknown publishing is not safe. The standard track still chooses the smallest justified stages; it does not mandate a planning chain.

## Minimal path and packet

One existing card: author + targeted tests -> independent same-card reviewer -> Orchestrator acceptance -> separately authorized delivery when requested. The packet's three required stages encode the worker/delivery path; acceptance is non-worker coordination, not another worker/card. No separate planner, researcher, scout or tester by default; add only a demonstrated necessary capability under maintained admission rules. Docs get lightweight independent review (accuracy, link/format checks as applicable), never no review. Repository-required tests/gates remain mandatory at final candidate boundaries.

Record all packet fields below. `author` and `reviewer` must resolve to distinct verified native profiles, not just different labels/sessions; bind the exact candidate and existing card in maintained admission evidence. `required_stages` order is fixed. `delivery_mode=local_only` means local acceptance only; `delivery_mode=gated` retains the requested external outcome and delivery_pending until exact publication/integration/deployment acceptance evidence. Never infer publication authority from local acceptance, tests, reviewer approval or the selection packet. Auto-deploying publication is excluded from fast selection, not authorized by it.

Synthetic example only (not task identity, runtime evidence or authority):
```json
{
  "track": "fast",
  "reason": "Known replacement for a broken prose link; bounded reversible edit",
  "kind": "broken_link",
  "known_cause": true,
  "bounded": true,
  "reversible": true,
  "risks": [],
  "unknowns": [],
  "required_stages": ["author_targeted_tests", "independent_same_card_review", "authorized_delivery"],
  "same_card": true,
  "author": "fixture-author",
  "reviewer": "fixture-reviewer",
  "tests": ["check replacement target and changed Markdown; repository-required gates"],
  "delivery_mode": "local_only",
  "authority": "fixture standing local scope only; no publication authority",
  "estimate": "Role-sized author/reviewer/coordination estimates and remaining cumulative budget in admission evidence; not a deadline guarantee",
  "fallback": "Unexpected scope/test/security finding: reclassify standard on retained card/history; stop for authority, denial or exhausted allowance",
  "scope_expansion_rule": "Record delta and affected tests/review; no budget/history reset; obtain new authority only for genuinely expanded scope"
}
```

User-facing recommendation is concise: “FAST — known broken prose link; author/checks + independent same-card review; local-only acceptance. Estimated effort: [task-sized range]. External delivery: [gate if requested].” Proceed under verified standing local authority without per-stage permission prompts. Standard recommendation names the specific exclusion/unknown and next necessary evidence, not an automatic research chain.

## Budget and fallback

Record role/task-sized author, reviewer and coordination allowances, native persisted limits and actual admission metadata under maintained preflight. Align procedural allowances to supported native caps; no universal microdeadline. Reserve first review, one permitted correction/rereview and receipt/verdict writing within the cumulative allowance. Save an early candidate receipt/checkpoint with scope, changed/tested/remaining and exact evidence before expensive work. Record elapsed/wait and actual usage separately; unknown usage is not zero. Configured limits are not proof of exercised enforcement. Reuse unchanged evidence by exact digest/policy version, recheck fresh boundaries, keep models unchanged.

Unexpected scope, failed/unexpected tests or security findings suspend fast eligibility: preserve the candidate and append reclassification/reason and affected evidence; use standard only within remaining authority and budget. Reclassification does NOT reset stage_started_at, consumption, verdicts, rejection limits or recovery limits. Follow the maintained review guard (including the pending verdict), stop on authority gap, denial, explicit stop or exhaustion, and use only its authorized recovery contract. Do not turn a stopped fast task into a new standard attempt. Local acceptance, integrated publication and deployed outcome remain distinct.

## Offline checks

`python -m unittest discover -s scripts -p 'test_fast_track.py' -v` checks the representative packet, omitted fields, risk selection and review/delivery bypasses. `fast_track_packet.py` is a small stdlib selection/packet checker only; it neither authenticates facts/authority nor validates native execution. It is distinct from stage admission: run the existing maintained `review_loop_guard.py` and applicable `validate_gate.py` against genuine full evidence before release. Their PASS is not independent review or delivery authority. No new framework or duplicated stage validator is introduced.
