# Coordinator continuation — one outcome, one next action

Load on native blocked/triage/review/completion events and authorized outcome handoffs. Use [coordinator management](coordinator-management.md) for supported transport and identity, [admission preflight](admission-preflight.md) before release, and [outcome lessons](outcome-and-incident-lessons.md) for incident decisions. This is a procedural read/act/readback sequence, NOT an atomic transaction. It adds no framework, database, scheduler, bot or native hook.

## Reconcile before acting
Use existing outcome comments and task-owned artifacts. Preserve outcome identity and failed history. Read source/outcome, relevant runs, dependencies, accepted candidate/verdict, existing execution/human gates and latest next action. Coalesce duplicate/out-of-order observations against current state, not notification arrival order. Resolve event IDs from supported history or mark unavailable; never invent them. Keep stale dispatcher-owned coordination parked until its exact execution is verified idle; do not dispatch a routing-only worker.

Record only a compact next-action entry (link bulky evidence), not another mandatory card:
- Binding: board/outcome/source IDs; observed event/run/session/profile and author/reviewer provenance; exact candidate path/base/digest; prior comment/artifact reference.
- Authority and budget: actual authority reference/exclusions; original cumulative consumed/remaining wall time, active runtime, admissions, recoveries and rejections (UNKNOWN where unavailable, never zero by inference).
- Decision: phase, concrete next action, existing responsible actor and target task/gate, prerequisite evidence, status (planned/in_flight/verified/uncertain/blocked), actual target readback, next trigger or decision/resume condition.
- Stable action identity: board/outcome + immutable candidate/input digest + phase/action kind. Event ID alone is not a dispatch key. Reuse the identity across duplicate wakes.

Before any side effect re-read target/runs and the latest action entry. An in-flight or verified action is reconciled, not repeated. Record intent before admission and receipt after it. Ambiguous release/send/write => uncertain; inspect exact target before any retry. Earlier steps of a partly failed admission may have succeeded. Do not repeat an entire script. Unchanged duplicate/own-comment observations need no new comment. Comments are not CAS or leases: concurrent/manual ownership or unknown active execution requires park/reconciliation, not a claimed lock. Repair a missing record from retained evidence without resetting budgets.

## Durable knowledge at stage boundaries
On research, review (including failed/rejected verdicts), and final outcome events, load [shared Wiki factory](wiki-factory.md) and evaluate a concrete durable delta after reconciliation. Canonical Orchestrator coordinates; substantive wiki-skill work uses the shared Wiki Kanban board, not Bot Chats or coordinator-authored replacement docs. This specific route overrides generic named-bot messaging for wiki work. Coalesce pending updates, verify no-op without new event spam, and keep required documentation visibly pending until exact result readback; wiki Done never substitutes for source acceptance.

## Same-turn continuation
1. Waiting/review pending: verify preflight and actual subscriptions, then existing relevant validators before any release. READY is not started; retain actual run readback. Reviewer selector and actual reviewer profile must differ from author.
2. Accepted local: verify exact unchanged candidate and independent verdict, record acceptance, and perform already-authorized local delivery preparation NOW. Missing publication/production permission blocks execution, not preparation of its request. Reuse existing evidence/cards; substantive preparation may use one scoped specialist with verified subscription/admission and expected trigger, not a promise to do it later.
3. Preparing delivery: use permitted non-secret reads to establish target, authentication/interface, protection/required CI and automatic deployment triggers. Produce one concrete packet: executor, exact target/repository/branch/environment/resources, candidate/base/diff/commit digest, exact commands/actions, time/attempt bounds, expected CI/deployed identity/original acceptance evidence, rollback and exclusions. UNKNOWN prerequisites are not runnable placeholders: bounded discovery or a precise capability decision precedes execution.
4. Awaiting external approval: retain the existing human gate BLOCKED and read back its packet binding. Actually PRESENT the consolidated request in canonical user-visible Bot Chat/authorized destination. A file or acceptance comment alone is not presentation. Record supported receipt/history; if the final response presents it, record presentation pending and verify the real message on the next legitimate readback/event. No self-wake or polling job; absent receipt => presentation unverified, not a claimed success.
5. Authorized execution: genuine scoped approval must match the concrete candidate/packet and still-valid window. Recheck budget, authority, target and dependencies, then admit only that executor/action. An expired window cannot authorize merge. Acceptance verified requires actual original outcome evidence, not source Done, CI or static review alone.

## Bounded blocker handling
Classify dependency waiting, missing evidence, ordinary tooling error, guard/auth capability denial, missing authority, exhausted budget or coordination state separately from implementation defects. One evidence-changing local recovery per blocker may proceed within existing scope and original cumulative budget after verified idle; an unchanged/exhausted blocker stays parked. Keep full previous consumption; no replacement-card or renamed-phase reset. The review-loop guard still governs author corrections (including pending rejection); review-routing or missing supplemental-check recovery does not restart the author.

An explicitly approved immutable workspace-binding setup error follows [worker progress recovery](worker-progress.md): old execution verified idle, old card parked, one same-candidate dir-bound replacement with full history/authority and supported same-board edge readbacks. This is not automatic recovery from exhausted budgets; an expired allowance requires the separately bounded, usage-preserving amendment in [review-loop guard](review-loop-guard.md). Reuse stable action identity across source/replacement, duplicate and ambiguous admissions; never reset counts or original elapsed time.

Actual denial => stop, retain exact command/rule and unchecked assertions, route to authorized policy owner. Only an explicit reviewed new-interface decision plus actual guard preflight permits remaining independent checks; never disguise/repackage a denial. If recovery is unavailable, present one precise capability/scope/budget decision with evidence, existing owner and resume condition. No per-command approval loop, new research chain, fabricated readiness or implicit production authority.

## Accepted-local terminal checklist (before actual turn exit)

Apply this checklist at the actual final response/turn boundary after acceptance and on subsequent native wakes, not merely when recording source Done. Keep the original user intent separate from the source stage's local-only execution restrictions; those restrictions remain binding but do not waive the overall delivery outcome. Only an explicit user instruction making local-only the FINAL outcome permits local closure. Do not infer it from a native completion-contract, an offline stage, missing approval or a preparation-only worker assignment.

- Record source acceptance separately from outcome closure, the original mode/requested evidence level, actual achieved level and remaining requirements. Set `delivery_pending` in the existing outcome entry until that requested level AND any higher original outcome requirements are verified. A selected lower mode does not erase them. No acceptance-comment-only stop or claim that the overall task is done after preparation.
- If exact execution is already authorized, recheck all existing gates and cumulative budget, then execute/admit the authorized next action in this turn with readback and subscribed trigger; clear pending only on actual required acceptance evidence. If execution lacks authority, prepare AND present the concrete mode choices/approval packet in this same turn, not on a promised later turn or after a reminder. No automatic commit/publication/deployment follows from acceptance or mode selection.
- UNKNOWN auto-deploy or other mandatory prerequisites require a concrete visible prerequisite: name the missing fact, bounded permitted discovery, responsible existing actor, budget and resume evidence. Offer discovery/preparation only, not a runnable publication mode. Offline restrictions forbid external discovery. If substantive discovery needs a specialist and is authorized, admit that specialist once with subscription readback before release and actual run/next-trigger evidence; do not park a promise or create routing-only work. Otherwise present the exact capability/scope decision now. Existing actual denial, exhaustion and approval policies always win.
- Bind presentation to the exact candidate/packet, choices, destination and real user-visible message/history reference. A saved packet or acceptance comment is not presentation. If presenting via this turn's final response, actually include the choices/prerequisite there and record receipt pending/unverified until a legitimate subsequent history read confirms the real message; never fabricate a receipt or mark pending as accepted. No self-wake, polling job or reminder requirement to manufacture that readback.
- Reuse the stable gate/action identity. An unchanged gate with verified prior presentation is a no-op: retain its real receipt, no spam or duplicate admission. An unchanged but silent/unverified gate is NOT a presented gate: reconcile supported history first; if never sent, present now, and if send is ambiguous retain uncertainty without blindly resending. Close this turn only with the evidenced disposition below, not silent delivery_pending.

Tight synthetic instruction fixtures (offline document checks, not model-execution proof):

| State | Required disposition |
|---|---|
| source Done; original mode unmet | delivery_pending; prepare and present, not outcome closed |
| packet saved; gate silent | delivery_pending; present in this turn, not presentation complete |
| gate sent; receipt absent | delivery_pending; presentation unverified, retain pending receipt |
| gate presented; no approval | delivery_pending; await authentic scoped approval |
| approved exact execution; prerequisites valid | delivery_pending; admit authorized execution and verify requested level |
| requested level verified; no higher original requirement | outcome may close with exact acceptance evidence |
| user explicitly requests local-only final outcome | local closure allowed after exact local acceptance |
| source stage local-only; original delivery intent retained | delivery_pending; stage restriction is not final-outcome waiver |
| auto-deploy triggers UNKNOWN | delivery_pending; visible bounded prerequisite, no runnable publication mode |
| unchanged gate already presented; duplicate event | verified no-op; reuse receipt, no resend or admission |
| unchanged silent gate; duplicate event | delivery_pending; missing presentation still due |

## Turn-exit invariant
Exit with exactly one evidenced disposition:
- Verified authorized action and next subscribed trigger;
- Concrete external gate actually presented (or explicitly presentation-pending/unverified when no receipt yet);
- Bounded stop/capability decision, owner and resume condition;
- Verified duplicate/no-op bound to the existing record.

“Accepted; next needs approval” without executing authorized preparation violates this invariant. At-least-once wake queueing does not prove model execution or message receipt. No exactly-once effects, race freedom, hard coordinator budget, model compliance or end-to-end autonomy is guaranteed. A separately authorized bounded author → explicit independent review → native wake → concrete next action/visible gate test without corrective parent DM is required for live claims; do not reuse exhausted historical canaries.

## Verify acceptance without manufacturing more events
Start the primary test with complete immutable inputs and explicit independent reviewer routing. Permit only initial fixture/admission setup; count any corrective parent message or manual re-release afterward as assistance. Observe native execution and actual preparation output, not merely a Done card. Verify the gate's exact candidate/payload bindings in subsequent legitimate chat history; a user supplying the received gate is additional visibility evidence. Record that later receipt in a separate durable acceptance result rather than rewriting the earlier pending record. Preserve the result and essential sanitized evidence outside expiring scratch.

Report branches separately: primary continuation, ordinary-error recovery, duplicate/out-of-order reconciliation and ambiguous side effects. Use one explicitly scoped post-admission ordinary fault for recovery coverage, preserving the initial failure and permitting only its bounded correction. A guard denial is not the synthetic ordinary error and must stop the branch. Establish a supported replay/fault interface before testing duplicate notifications; never manufacture task transitions, rewrite event storage or use a parent DM while claiming native replay. Unavailable replay remains NOT TESTED, not PASS inferred from prose or a happy path. Never inject uncertainty into real publication merely to test reconciliation.
