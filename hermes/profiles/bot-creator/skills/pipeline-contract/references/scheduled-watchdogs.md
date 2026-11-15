# Scheduled advisory watchdogs

## Build and verify

1. Inspect installed native cron help and supported metadata reads. Avoid listing interfaces that promote ready work. Reuse the existing scheduler; do not add a daemon or polling service. Verify the actual consuming profile, selected model and callable tools independently of script execution.
2. Prefer native no-agent scheduling when deterministic metadata rules suffice. The configured model may serve interactive interpretation without being invoked on every tick. Add learned routing only after measuring a problem and its added inference cost; catalog entries and guidance skills do not prove installed executable integration.
3. Persist per-board/card semantic fingerprints and delivery state. Exclude volatile heartbeat/request timestamps. Cap digest size without marking unsent overflow delivered. Suppress unchanged delivered findings; distinguish queue acceptance from coordinator consumption. An ambiguous failed receipt must not immediately re-enable the same page: persist its unresolved outbox and pending remainder across ticks, restarts and coverage gaps, then let Orchestrator reconcile through supported evidence. Do not create an unbounded resend loop or escalate routine receipt reconciliation to Bot Creator. Bind receipt reads to the exact profile, job and execution; inspect helper side effects before calling a metadata lookup read-only. Test repeated ticks, restart, gap, queued/unknown/failed outcomes and successful FIFO settlement.
4. Keep active work and explicit current holds out of resumption recommendations. Historical approval words are not reliable current holds, and an unmatched hold pattern is not evidence of authority. Send advisory context only; the coordinator freshly checks scope, approval, dependencies and worker state before acting.

## Aging without progress timestamps

Establish first-seen and last-observed-semantic-change timestamps when source progress fields are absent. Label the result **observed unchanged**, never historical inactivity. Creation time and heartbeat do not substitute for substantive progress. First scan creates an age baseline, not stale findings. Separately emit a bounded startup/gap reconciliation digest when authorized: label historical inactivity unknown and do not call it age-qualified. Capture one persistent reconciliation epoch with finite FIFO pages so overflow is neither lost nor repeatedly reported. Include technical and human-gated candidates only as explicitly no-authority reconciliation items; exclude active workers and preserve deliberate holds. This makes intermittent-host monitoring useful without inventing observations during downtime.

Reset aging on meaningful status/blocker/scope changes. Preserve it across restarts only with continuous coverage. Define a maximum observation gap relative to cadence; larger gaps or clock rollback reset continuity. Failed scans must not commit partial observations or count the unseen interval as confirmed inactivity.

## Acceptance

Test fresh/stale thresholds, semantic changes, active runs, explicit holds, historical approval mentions, restart persistence, failed scans, clock rollback, coverage gaps, dedupe and overflow with deterministic clocks. Then run one real read-only scan and read back the native schedule.

Track separate milestones: real baseline; natural elapsed qualification; coordinator consumption; later real unchanged-alert suppression; longer threshold qualification. Synthetic tests are not natural elapsed acceptance, and quiet scans are not positive notification proof. Report false-positive human-gated advisories as a limitation even when the coordinator safely declines them.

## Missed schedules

Before restarting or editing cron, compare current time, last success, scheduler heartbeat, boot/shutdown evidence and missed-occurrence policy. Host shutdown can explain healthy jobs with stale coverage. Catch-up cannot reconstruct absent observations. Let the next natural scan reset continuity and verify that reset; do not add another monitoring loop.

Continuous overnight coverage needs an always-on host. Do not promise a continuous full-day threshold on a machine that shuts down nightly. Distinguish enabled schedule, live scheduler, successful execution, useful observation and consumed notification in status reports.
