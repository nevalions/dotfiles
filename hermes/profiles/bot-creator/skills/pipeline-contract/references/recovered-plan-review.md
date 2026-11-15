# Recovered plan artifact review (explicit opt-in)

Native same-card review remains the default. This exception admits only a complete preserved plan from an actually timed-out author attempt, approved by an independent reviewer on a separate ordinary card. It does not mark the author complete, create native review provenance, waive risk/human gates, authorize deployment, or support implementation-review recovery.

## Exact validator fields

`reviews.plan` retains exact `binding`, nonempty `evidence_ref`, `source_card` (original author card), `verdict="APPROVED"`; set `native=false`, `mode="recovered-artifact-review"`, and add `recovery` with the following six objects. **Every object** requires exact candidate `binding`, nonempty `evidence_ref`, and `verified=true`:

| Object | Additional required fields |
|---|---|
| `source` | nonempty `card`, `run`, `profile`; `status="timed_out"`; card equals outer source_card |
| `artifact` | absolute `path`; lowercase 64-hex `sha256`, `current_sha256`; `complete=true`, `preserved=true` |
| `reviewer` | nonempty `card`, `run`, `profile`, each distinct from source; `status="completed"`, `verdict="APPROVED"`, `artifact_sha256` |
| `idle` | `card`, `run`, `profile` equal source; nonempty `session`; `state="idle"`, `active_worker=false` |
| `decision` | nonempty actual Orchestrator `actor`; `actor_kind="orchestrator"`, `action="recover-plan-review"`, `decision="APPROVED"`; `source_card`, `source_run` equal source; `review_card`, `review_run` equal reviewer; `artifact_sha256`; `authorization_ref` equal authorization.evidence_ref |
| `authorization` | nonempty actual user `actor`; `actor_kind="human"`, `action="workflow-recovery"`, `decision="APPROVED"`; `source_card`, `source_run` equal source |

All artifact hashes must equal `identity.plan_digest`: preserved original bytes, current bytes, reviewed bytes, and Orchestrator decision bytes. A changed artifact or candidate invalidates this admission. Missing fields, unverified outcomes, non-approved verdicts, active source worker, self-review, hash mismatch, absent authorization or decision, and generic `native=false` all block. Explicit mode/recovery metadata cannot fall back to native approval, even if `native` is changed to true.

## Caller verification and lifecycle (not authenticated by JSON)

The validator checks supplied metadata only: it does not read artifact bytes, native records, identity directories, user messages, session status or evidence references. Boolean `verified` and actor names cannot authenticate themselves. Before release, the caller must independently read native author/reviewer card and exact run records, verify canonical profile identities (aliases must not conceal self-review), verify a completed actual APPROVED verdict covering this exact artifact/candidate, and read the referenced user authorization and Orchestrator decision. Preserve original failed-run status; never rewrite it to completed. Ordinary reviewer completion is not native source-card completion.

Hash actual saved bytes at preservation, at review and immediately before admission; preserve an immutable version and review output recording that hash. Verify the original worker/session is idle with no active source worker and no new writer/attempt; timeout alone is insufficient. Keep source parked against redispatch. If any observation cannot be verified or has become stale, block and refresh actual evidence, not asserted values. Recheck source idle and artifact bytes at release to reduce races; this offline validator is not an atomic lock.

Orchestrator must wire a separate recovery admission/downstream dependency through supported native lifecycle operations, leaving original failure history intact. An approved JSON gate does not unblock the DAG itself. Do not forge a native review or manually alter DB rows to release dependencies. Retain final production acceptance separately.

## Synthetic executable example

`scripts/test_recovered_plan.py:recovered_fixture()` is the complete exact example, extending `test_validate_gate.fixture()`. All identifiers and evidence references beginning `synthetic:` or `synthetic-`, `/synthetic/plan.md`, profiles and repeated-letter hashes there are **synthetic only**, never actual permission or production evidence. Use it to learn the schema, not to seed a live approval. Tests exercise positive downstream admission and fail-closed mutations; the unchanged original fixture exercises native default admission.
