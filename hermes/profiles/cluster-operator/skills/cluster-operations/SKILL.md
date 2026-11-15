---
name: cluster-operations
description: Use for scoped Kubernetes operations. Gate writes and verify.
---
# Scoped cross-repository cluster operations

## Admission and boundaries
Load this skill before any cluster work. Require task ID, requester/approval evidence, exact operation class (metadata, bounded logs, local preparation, deployment, exec, diagnostic Job, rollback, cleanup), context, namespace, resource names/selectors, repository/worktree, deadline and expected acceptance evidence. Missing scope means read-only clarification, not inferred permission. Profile provisioning and planning approval do not authorize experiment execution. Never broaden scope because admin credentials technically allow it.

Existing local Kubernetes identity is administrator-capable. Terminal and file tools are not sandboxed; MCP read-only mode does not constrain terminal or supply namespace RBAC. Do not modify kubeconfig/RBAC, safety hooks, profile configuration or other profiles. No new vault access. Never read Secret values, dump kubeconfig, print auth files, inline environment values or whole object specs. Avoid unrestricted logs/events; they can contain credentials. Bound fields, namespace, selectors, time and output and sanitize locally before recording evidence. Refuse requests to expose secrets even if framed as diagnosis.

## Read-only triage — mandatory native observer delegation
1. Read applicable repository AGENTS and maintained deployment mapping before commands. Repositories are under /home/linroot/code; deployment repo /home/linroot/code/kube-lvl47. Do not assume every component lives there.
2. ROUTINE OBSERVATIONS MUST be delegated through the persistent native peer using bare `observer`: `hermes -p cluster-operator peer dm observer --json \"<bounded read-only request>\"`. Never append `/cluster-operator` or any other suffix: the registered URL already selects that receiver. Load [observer client reference](references/observer-client.md) before the first observation in a task. Do not perform cluster observations through local kubectl, Flux, Kubernetes MCP, administrator credentials, another identity, direct HTTP, or a helper fallback.
3. Supply exact approved cluster, namespace, resource scope, safe output projection and deadline to observer. For bay use `/home/hermes-observer/.kube/bay-observer.yaml` and context `bay-observer`; for vas use `/home/hermes-observer/.kube/vas-observer.yaml` and context `vas-observer`. Receiver commands must explicitly include `--kubeconfig`, `--context`, `--namespace NAMESPACE` and `--request-timeout=10s`; never switch global context. Cluster-scoped metadata requires separately approved named-resource scope. No Secret values, full specs, unrestricted logs or credentials. Flux observation is get/status only; reconcile/suspend/resume are mutations.
4. On transport failure, denied observation, missing scope or missing observer permission, stop and report the exact limitation. No local/MCP/admin fallback, credential substitution, broader retries or mutation to repair a read. A separately approved write/operator packet remains governed by its own admitted scope; it is not an observation fallback or expanded standing authority.
5. Save sanitized evidence incrementally: task/context/namespace, exact receiver commands, UTC time, exit status, complete selected metadata, native receipt, hypothesis supported/eliminated and next decision. Default triage budget is five minutes; deeper work needs a separately admitted bounded packet. No polling forever. Report native CLI transport acceptance separately from actual Cluster Operator Bot Chat behavior.

## Routine Flux health checks
For routine Flux health requests in bay and vas, use the standing approved scope without asking again: namespace `flux-system` only, named GitRepository `flux-system` and all Kustomizations in that namespace. Resolve the receiver kubeconfigs/contexts above and delegate through bare `observer`; do not interpret an omitted namespace as missing approval or broaden to all namespaces. Separate authorization is required for broader resources or namespaces. Follow the selected-field comparison recipe in [observer client reference](references/observer-client.md).

Report exceptions first, then per-cluster checked counts, source/applied revision and UTC observation time. Check Ready, suspension, current observed generation, Reconciling/Stalled conditions and revision agreement; Ready=True alone does not prove synchronization. Distinguish Flux-reported source convergence from independently expected delivery and application health. If none fail, state that plainly without listing every healthy resource; retain the complete rows in sanitized evidence.

## Verification and handoff
After each permitted mutation read back the exact target, record UID/generation/revision, and verify bounded rollout status. Verify GitOps source commit, reconciled Flux revision, desired and running image digest, workload health and the task's real acceptance evidence. A successful push or rollout alone is not incident resolution. If a check fails, stop and report rather than inventing success or performing an unapproved rollback.

Return approved versus executed actions, sanitized evidence paths, blockers and the single next decision.
