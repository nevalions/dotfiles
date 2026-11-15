# Cross-repository Kubernetes pipeline

## Intake and ownership
Load this reference at intake, alongside contract.md, workspace-lifecycle.md and bounded-research.md when diagnostic work is involved. Populate templates/deployment-map.md using exact non-secret source locators and observation times. Classify every assertion as repo-documented, historical observation, live-verified, proposed, or unknown. Local Git metadata is not live cluster evidence. Resolve conflicting docs explicitly; never promote a historical image or context to current identity.

| Role | Owns | Does not imply |
|---|---|---|
| orchestrator | Map, capability check, risk/approval bindings, cross-repo DAG, evidence admission and final acceptance | Cluster execution, human approval or permission from a DONE parent |
| diagnostician | Bounded installed MCP pod/event/metrics observations in an explicit namespace | Logs, exec, setup, route isolation, successful downloads or full inventory |
| cluster-operator | Task-scoped safe selected-field discovery and local implementation/review/test; exact setup/experiment/deployment only with meaningful execution approval | Production authority from local implementation scope, tool availability, namespace smoke or profile existence |
| main-implementer | Reviewed code/manifests/tests in owned per-repo candidates after freshness gates | Production mutation or publication |
| commiter | Approved repo-specific commit/push/PR/merge operations, exact remote/result SHA | Deployment authority merely because the action is Git |
| ci-watcher | Required actual provider checks for each exact integration SHA and image-build provenance | Running image identity, Flux reconciliation or application acceptance |

Keep independent plan/implementation review, tester/browser-tester and docs gates from the main contract. Preserve existing candidates, worktree ownership and failed provenance. One evidence identity per repository; link app SHA -> build/run -> immutable image digest -> deployment-repo pin/result SHA -> Flux revision -> workload imageID. Do not collapse two repositories into one SHA or let an app test stand for manifest validation. Changed inputs invalidate downstream evidence.

## Approval before automatic deployment triggers
A default-branch push/merge, release tag, image publication, deploy-bot auto-merge, hold release, or image-automation change may deploy without an operator command. Inspect that chain BEFORE Commiter publishes, not after CI. Require both delivery policy and deployment approval covering the affected environments, image/commit identity, exact trigger, rollback and bounds. The approval may explicitly cover the resulting build/digest derivation; unknown output mappings block deployment acceptance. Never disable automation, change hold, suspend Flux or bypass branch/security/freshness gates as a workaround.

Standing scopes count only when backed by an actual user approval reference with allowed executor, context/environment, namespaces/resources, operations, duration/expiry, limits, rollback and exclusions. Recheck scope/revocation before action. This skill grants none. One user implementation task can cover bounded non-secret inspection, selected-field metadata/config discovery, local artifact/runner/code changes after Git gates, review and offline tests. Do not fragment that scope into per-tool permissions or hypothetical owner attestations. Setup, production experiments, publication and data-changing production acceptance remain distinct execution authority, consolidated into exact reviewed decisions where practical. Read-only API permission is not user authorization, but an already-authorized discovery envelope need not be re-approved per read.

## Three independent deployment/incident gates
1. **Identity:** fresh explicit context/cluster identity, namespace, workload/pod UID and name-matched container imageIDs; app result SHA/build provenance and deployment-repo result SHA/pin agree. Record timestamps and commands/exits; tags alone are insufficient.
2. **Reconciliation:** source artifact revision and per-app last applied revision match the authorized deployment SHA, observed generation catches metadata generation, Ready succeeds, not suspended; deployment rollout and actual imageIDs match. A source fetch alone, CI PASS, or pods Ready is not reconciliation/acceptance proof. Query only under approved read scope; forced reconcile/suspend/resume is a separate mutation.
3. **Application:** original acceptance criteria with expected and actual results. For yt-downloader: fresh completed production download row, non-null file_path, independent file existence/content evidence and deployed candidate identity; durable sanitized stderr and useful application diagnostics where required by the incident. Isolated media sample is not this acceptance. Production API/row/file checks require their own approved scope.

Repository `close` validator does not validate these three gates. No new deploy validator is introduced here; Orchestrator must enforce this checklist with actual evidence and keep final acceptance blocked on UNKNOWN/FAIL. Never manufacture PASS from a docs example.

## Examples (policy examples, not permission)
- App-only yt-downloader fix: app review/tests -> approval BEFORE default-branch publication (auto-deploy follows images) -> app exact-SHA CI/build digest -> deploy-bot pin review/delivery evidence -> deployment-repo exact-SHA CI -> authorized identity/reconciliation -> separately authorized download row/file acceptance.
- Manifest-only proxy change: kube-lvl47 candidate review/tests -> scoped GitOps deployment approval before ship/merge -> exact result-SHA CI -> operator observes approved bay target and Flux revision -> app acceptance. No live balancer edit as a shortcut.
- Incident investigation: Orchestrator owns one outcome -> reuse existing evidence -> cluster-operator performs task-scoped selected-field discovery and chooses simplest safe diagnosis -> local implementation, independent review and offline tests -> one exact execution decision at the next meaningful risk boundary. New infrastructure is optional, not a prerequisite if existing approved resources suffice. A reviewed decision may explicitly cover setup and a bounded experiment together; setup-only authority never silently releases an experiment or incident closure.

## Capability evidence boundary
Record current capability and native worker evidence in durable task artifacts, not static incident summaries in this procedure. Verify effective tools and exact worker admission before execution. A successful local worker or namespace-read smoke does not verify production exec, routing enforcement, mutation or deployment. Reuse still-valid evidence; do not repeat unrelated research or provision credentials.
