# Deployment map: <application>

Status: DRAFT / NOT EXECUTION AUTHORITY. Unknown fields must remain explicit.

- Sources: exact non-secret path/line, repository HEAD, read timestamp; distinguish canonical clone from retained candidate.
- Application repository/candidate/base/result SHA: UNKNOWN.
- Deployment repository/candidate/base/result SHA and owned manifest/overlay paths: UNKNOWN.
- Build provider/workflow/run, source SHA -> immutable image digest mapping: UNKNOWN.
- Deployment trigger chain (branch/tag/image/automation/hold/merge) and all affected environments: UNKNOWN.
- Context/cluster identity, namespace, Flux source/Kustomization, workload/service/container names: UNKNOWN.
- Repo-documented values: list with sources; not runtime facts.
- Historical observations: evidence reference/time; not current bindings.
- Live-verified values: exact bounded command, exit, time, evidence ref; otherwise NONE.
- Conflicts/unknowns and responsible owner: explicit, including branch naming drift.
- Role routing: orchestrator / diagnostician / cluster-operator / main-implementer / commiter / ci-watcher; actual capability evidence.
- Approval: actual user reference or NONE; executor, action, exact targets, duration, bounds, exclusions, rollback, revocation check. Separate preparation/discovery/setup/experiment/delivery/deployment/acceptance/cleanup.
- Identity acceptance: app SHA -> build digest -> deployment SHA -> actual workload UID/imageID.
- Reconciliation acceptance: source revision, app applied revision/generation/Ready, rollout.
- Application acceptance: original expected row/file/API behavior and fresh observations.
- Cleanup: exact owned inventory/UID preconditions; preservation; separate approval. No blanket deletion.
- Delivery status / CI status / deployment status / incident status: separate, default UNKNOWN.
