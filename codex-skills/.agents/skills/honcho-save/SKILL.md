---
name: honcho-save
description: Save verified durable findings to Honcho when concluding authorized work, or save explicitly requested memory, using an exact grant and confirmed readback. Does not save ordinary chat, plans, status updates, or unverified drafts.
---

# Save verified Honcho memory

Use the existing Honcho publisher to preserve a useful, evidence-backed conclusion. This skill does not grant publication authority. Complete the user's authorized delivery stages before reporting task closure; do not introduce a commit, push, deployment, or CI requirement solely to save memory.

## Select an eligible fact and audience

Save a durable fact that will change a future decision: a verified repository constraint, established procedure, implemented behavior, or supported incident lesson. Omit routine activity, transient status, redundant facts, raw transcripts, credentials, and unverified explanations. Prefer one concise fact over a task narrative. No eligible fact means no write.

Use current primary evidence. Label local-only, committed, pushed, deployed, and runtime-verified outcomes accurately. A local edit is not a deployed behavior; passing historical recovery checks are not fresh deployment verification. An observed recovery does not prove a suspected root cause. Cite a checked immutable revision or a stable primary source, with the actual checks/results and separate review or independent verification. Do not invent evidence to fill required fields; hold an unsupported draft unsaved.

Only the top-level parent/coordinator publishes. Children and forks return a concise draft with source, checks, independent verification, and intended target to their parent; they must not manufacture a shell grant to bypass native thread restrictions.

A matching automatic parent-thread repository grant authorizes eligible repository findings at task completion under the standing policy for `~/code` and `~/ansible`; do not ask again for that authorized write. Outside that scope, require the user's explicit save authorization and a matching explicit grant. User preferences always require explicit save authorization and an explicit `linroot` grant. Repository authority never implies authority to publish preferences or widen the audience to project peers or `code-wide`.

## Publish through the live grant

Discover the Honcho tools by name if necessary. Prefer the native `get_grant`, `readback`, and `publish_verified` tools. Their availability does not establish write authorization.

1. Call `get_grant` with `{}`. Parse its returned JSON text and inspect the current authorization against this task and intended audience. Copy its exact five scope keys: `workspace_id`, `peer_id`, `target_peer_id`, `session_id`, `task`. Never infer IDs from the checkout name or reuse another task's grant. Missing or denied grants leave publication blocked.
2. Call `readback` with `{"scope": <exact grant>}` before appending. Read its returned JSON text and recent conclusion records; look for the same fact, source, task, checks, and verification. An already matching record needs no duplicate. An empty readback means no matching memory was returned, not that a peer is absent. An empty peer card is also not an existence check.
3. Prepare the exact payload and run the local [token preflight](references/token-preflight.md) before appending. Individual field limits are insufficient: the rendered conclusion plus the gateway evidence suffix must fit the deployed embedding token budget. Count the full note with the verified tokenizer; never estimate tokens from characters or send private payloads to a remote counting service. Compact the fact and evidence without dropping qualifications, then recheck if it exceeds the limit. No successful preflight means no append.
4. Call `publish_verified` with exactly `scope`, `candidate`, `checks`, `verification`, and `conclusion`. Supply nonempty, printable, single-line strings within the deployed limits: `candidate` 256 characters, `checks` 900, `verification` 600, `conclusion` 1000. `candidate` is the immutable revision or primary source; `checks` records checks and results; `verification` records separate review or independent evidence; `conclusion` states one durable supported fact. Do not truncate away qualifications to meet limits; narrow the fact instead.
5. Call `readback` again with the identical scope. Parse the returned conclusion records and confirm the exact stored content, including evidence and task. The gateway appends this suffix to the supplied conclusion: ` [Task: <task>; Candidate/source: <candidate>; Checks: <checks>; Verification: <verification>]`. Confirm that full record in the exact granted session and observer/target binding. Neither an append acknowledgment nor tool availability proves persistence. If the returned schema cannot be interpreted confidently, do not claim a saved memory.

Keep workspace, observer, target, session, and task unchanged throughout. Do not publish the same fact to additional peers. Existing peers must already exist; the gateway can create only its granted metadata-only task session. Missing resources require a separately authorized provisioning workflow, not a publisher workaround.

## Handle failures and report accurately

On an ambiguous timeout or network result, read back before any retry. If the exact record is present, report confirmed success and stop. If absence is established and the failure was transient, allow at most one retry, then read back again; otherwise stop unsaved. A structured rejection such as HTTP 422 needs diagnosis or a corrected validated request, not a blind retry. For a proven token-limit rejection, locally validate a compact corrected payload, recheck the grant and exact readback, and allow at most one corrected append followed by readback. Auth, scope, missing-peer, or grant denial stays denied: never switch credentials/endpoints, provision resources, widen scope, or use direct REST to evade it.

For a genuine explicitly authorized save using an approved exact grant when native publishing is unavailable, read [references/explicit-cli.md](references/explicit-cli.md). That route is not a workaround for a failed automatic grant or denied write.

Report the task's delivery and memory outcome separately. Say saved only after exact readback; otherwise say unsaved or unconfirmed and give the concrete failure. Preserve the concise evidence-backed draft in the parent handoff or response when useful, without creating an ad hoc tracker. Memory failure does not erase verified task delivery, and completed delivery does not prove memory publication.
