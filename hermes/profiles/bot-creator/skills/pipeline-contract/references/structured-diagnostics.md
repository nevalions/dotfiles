# Optional structured diagnostic replacement contract

Use only when diagnostics themselves are an explicitly authorized necessary deliverable. Do not put logging/observability refactoring ahead of a causal application fix; parked diagnostics remain parked. Repeated leaks after free-text regex patches indicate a representation-boundary problem, not a shortage of token patterns. Record this as a **new design correction** under current user authority; never claim an older free-text-sanitization plan approved it. Preserve exact candidate, models, independent review and all production/publication gates.

## Boundary: construct safe data; never sanitize arbitrary prose

Persist/log only locally generated allowlisted messages from a constant catalog plus strictly bounded structured fields. Never carry source strings through a regex replacement or 'safe-looking' fallback. External source strings must never be stored/logged anywhere along the path: arbitrary response text, exception text/repr/args/tracebacks, command output, URLs, headers, cookies, paths, credentials, usernames, long IDs and even ordinary lowercase token strings are all untrusted. Do not hash raw secrets as a substitute for excluding them. Unknown keys are discarded; unknown enum values map to a fixed category; unknown objects are not stringified. Do not recursively serialize arbitrary mappings, exception causes, logger extras or attachments.

Suggested versioned record, adapted explicitly to actual schema before implementation:

- `version`: exact integer schema version (reject booleans).
- `message_code`: member of a reviewed finite catalog; displayed message is a local constant selected by code, never an interpolated source string.
- `error_class`: finite application-owned enum such as NONE, AUTH_REJECTED, ACCESS_DENIED, RATE_LIMITED, TIMEOUT, TRANSPORT_ERROR, UPSTREAM_ERROR, INTERNAL_ERROR, UNKNOWN_ERROR. Normalize an untrusted exception to a known category based on reviewed type/status checks, **never `str(exc)`, `repr(exc)`, class-name interpolation, `exc.args` or traceback rendering**. Unknown subtype => UNKNOWN_ERROR. Avoid user-defined properties/conversion methods.
- `status`: exact integer HTTP status 100..599 when independently obtained from a trusted typed adapter, otherwise null. Do not parse status from arbitrary error text. No bool/float/numeric-string coercion.
- `phase`: member of finite app-owned phase catalog (e.g. FETCH, PARSE, STORE, FINALIZE); exact allowed values only.
- `id`: application-generated correlation identity (e.g. fixed 32 lowercase hex from local RNG), or bounded internal row ID with explicit ownership/range. **Never validate and preserve an externally supplied token merely because it matches the format.** ID provenance matters as much as syntax.
- Optional counters: exact nonnegative integers with application-selected upper bounds; timestamps locally generated with an explicit unit/range. No free-form names, text, arbitrary metadata or extension bag.

Produce genuine useful diagnostics: phase, safe known category, trusted status, internal correlation identity, bounded attempt count, and generated messages explaining actionable class-level next steps. UNKNOWN_ERROR is honest and still correlatable; don't erase all failures into success or empty records. Sanitization is not remediation of the underlying failure.

## Preserve application and migration semantics

Trace every source-to-sink path (DB columns, row updates, logs, exception handlers, stdout/stderr, queue/notifications, diagnostic export) before replacing representation. Keep row identity/ownership, ordering, success/failure status, retries and update/transaction behavior intact; preserve existing migration sequencing, constraints and rollback expectations. Add a separate versioned representation or explicitly reviewed compatible migration; don't silently change unrelated columns, reset row state or broaden retention. Existing potentially unsafe stored text requires an explicit approved purge/migration plan; do not read/log/re-emit it while migrating. No production migration execution without the existing production gate.

## Required offline probes and independent review

Test boundary construction before implementation (RED), then GREEN. Include arbitrary lowercase strings, mixed Unicode/control characters/newlines, percent/escape encodings, giant strings, malformed nested structures, exception repr/args/cause and hostile `__str__` objects. Assert noninterference: changing only arbitrary source text cannot change any persisted/logged output. Assert no source sentinel in DB records, captured logs/stdout/stderr, exceptions and serialized payloads. Test positive diagnostics for each allowlisted class/status/phase and ID provenance, strict bool/int/float/length/range/unknown-key handling, unknown exceptions without interpolation, and adversarial variations **not just the latest review examples**. Verify migration compatibility, unchanged row semantics, and all full required gates on the final candidate. Reviewer inspects the trust boundary and every sink independently; passing focused examples is not privacy approval. No approval while any required probe is missing or any raw text path survives.

This file is a contract, not an implementation or claim that an application is safe. Use the existing [review-loop guard](review-loop-guard.md) to stop architecture churn and preserve the outcome-first critical path.
