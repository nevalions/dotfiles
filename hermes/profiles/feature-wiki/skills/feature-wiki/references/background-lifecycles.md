# Background lifecycle investigation

Use when tracing downloads, exports, imports, or other work that outlives
its initiating HTTP request. Inspect definitions; do not run jobs or tests
without authorization.

## Trace in this order

1. Follow the UI event to its submitted payload and route. Record defaults,
   validation, authentication dependencies, and applicable middleware; the
   browser's choices do not prove the server rejects other inputs.
2. Read admission queries and transaction boundaries. Determine whether a
   limit counts active work, successful work, or all retained records. Check
   whether counting and insertion are atomic before claiming a hard cap.
3. Identify the execution boundary: in-process background task, executor,
   subprocess, or durable queue. Do not call accepted work durable merely
   because its database row is committed.
4. Map each state write to its visibility boundary: local object mutation,
   process-memory update, database flush/commit, and API response. Inspect
   polling and terminal-state recognition; a status name used in queries
   does not establish that the worker ever assigns it.
5. Follow output-path construction through postprocessing and delivery.
   Check whether success requires the final file to exist and whether
   download-serving routes have their own authentication or ownership gates.
6. Trace exception boundaries, retries, and cleanup in execution order.
   Check failures before the main try block and whether progress entries,
   temporary files, partial output, and database rows are removed on every
   terminal path. A hook-specific removal is not unconditional cleanup.
7. Read deletion and cancellation separately. Determine whether deleting a
   record or file actually stops the worker, and how a late worker commit
   handles a missing row; document orphan-output risk as synthesis unless
   directly demonstrated.
8. Read scheduler enablement, cutoff calculations, and recovery ordering.
   Identify whether age means creation time or last activity, whether live
   workers are checked, and whether a recovered record can be deleted in
   the same pass. State if disabling retention also disables recovery.
9. Inspect matching tests and mocks. Separate route tests with a mocked
   worker, worker tests with mocked dependencies, and live integration
   checks; none substitutes for another.

## Access and deployment checks

- Inspect owner predicates independently for status, history, deletion,
  and artifact serving; authentication alone does not imply per-user
  isolation.
- Trace middleware and dependencies before claiming a route is unprotected;
  a route body alone does not establish its effective access boundary.
- Treat shared-library behavior as observed behavior, not automatically a
  vulnerability; ask whether shared or private access is intended.
- Identify process-local dictionaries and schedulers before discussing
  replicas. Explain non-shared progress or duplicated schedulers as
  deployment implications, not proof of the actual deployment topology.

## Evidence discipline

Cite the submission handler, worker, observer, and cleanup paths separately.
Attribute direct code findings to the current inspection, not an earlier
scout report that lacks them. Use scoped history or comments for rationale;
label consequences not exercised at runtime as synthesis or risks.
