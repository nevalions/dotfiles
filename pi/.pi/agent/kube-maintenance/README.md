# Canary observation

`pi-kube-maintenance` observes the installed canary using Python 3 and `kubectl`.
It makes only Kubernetes `get` requests and makes no Pi or model API calls.
Use an operator-provided kubeconfig through `KUBECONFIG`; no endpoint or credential
is embedded in the runner.

```sh
KUBECONFIG=/path/to/kubeconfig ~/.pi/agent/bin/pi-kube-maintenance \
  --once --context bay --state-dir ~/.local/state/pi-kube-maintenance
```

Defaults are Flux Kustomization `flux-system/autodeploy-canary`, Deployment
`agent-school/autodeploy-canary`, and container `canary`. Override with
`--flux-namespace`, `--kustomization`, `--namespace`, `--deployment`, or `--container`.
The kubeconfig needs read access to that Kustomization and deployment, and list
access to ReplicaSets and pods in the deployment namespace. This command does
not create RBAC, configure a cluster, reconcile Flux, or deploy a candidate.

Exit 0 means two reads found the same healthy current resources: Flux Ready
at its current generation and applied/attempted revision, a complete deployment,
an owned current ReplicaSet matching its revision/template, and the expected
ready pods with digest-bearing runtime image IDs. The comparison removes the
ReplicaSet's generated `pod-template-hash` label when matching templates. Each
kubectl request has a 10-second request timeout and 15-second process timeout;
at most eight calls take approximately 120 seconds plus local overhead.
Changes during observation fail conservatively; the next invocation can retry.

Each invocation emits one JSON receipt and atomically replaces `latest.json` in
`--state-dir`, including on observation failure. Failure exits nonzero and stores
`status: failed` with an error; a filesystem failure is reported to stdout when
state cannot be saved. JSON argument parsing errors occur before observation.
The receipt identifies the context/target, timestamp, Flux revision, deployment
and ReplicaSet generations/UIDs/resource versions, pod UIDs and runtime digests.
Treat a failed receipt as a failed check even if it contains partial observation
fields. Keep state outside the repository and use one operator host/state path.

Without a candidate, a healthy receipt has `status: observed`,
`mode: current-observation`, and `verified_release: false`. The normal systemd
invocation automatically reads `/etc/pi-kube-maintenance/candidate.json` when
present; it needs no timer or CLI change. Removing that file restores observation
mode. No Kubernetes resources or candidate files are written by the runner.

An operator publishes a candidate atomically after verifying the release CI and
registry manifests. The automatic file must be a root-owned regular file, with
no group/world write bits, under root-owned directories without group/world
write bits. Symlinks, malformed input, and unauthorized files fail closed. Keep
the service unprivileged and the candidate outside its writable paths. The
runner trusts these operator-supplied CI/registry references; it does not contact
Forgejo or a registry and needs no registry credentials. A deliberately invoked
`--candidate-file /path/to/candidate.json` also permits a file owned by the
invoking user, with no group/world write bits, for fixtures and one-shot checks.
That explicit path is an operator override of the file location/owner policy;
it never overrides the context or target selected by CLI arguments.

Candidate schema (all shown fields required; use full lowercase SHA/digests):

```json
{
  "schema_version": 1,
  "target": {
    "context": "bay",
    "flux_namespace": "flux-system",
    "kustomization": "autodeploy-canary",
    "namespace": "agent-school",
    "deployment": "autodeploy-canary",
    "container": "canary"
  },
  "expected_revision": "master@sha1:<40-character-merge-sha>",
  "release": {
    "pr": 123,
    "source_sha": "<40-character-pr-head-sha>",
    "merge_sha": "<40-character-merge-sha>",
    "required_ci": [
      {"context": "<required-check>", "url": "https://<run-url>",
       "sha": "<40-character-merge-sha>", "status": "success"}
    ]
  },
  "desired_image": "registry.example/canary:<exact-tag>",
  "registry_evidence": {
    "tag_ref": "registry.example/canary:<exact-tag>",
    "manifest_digest": "sha256:<64-character-top-level-manifest-digest>",
    "runtime_manifest_digest": "sha256:<64-character-selected-platform-manifest-digest>",
    "url": "https://<registry-evidence-url>"
  }
}
```

List every required successful post-merge CI check for that exact merge SHA.
For a multi-platform image, verify the running node platform and the selected
manifest from the registry; retain the top-level digest separately. A runtime
`repo@sha256:...` is compared with `runtime_manifest_digest`. An opaque runtime
config digest such as `containerd://sha256:...` cannot establish the registry
manifest identity and fails candidate verification. An unchanged digest is
allowed: the exact revision and desired tag still have to match.

Only two identical healthy snapshots, exact Flux applied/attempted revision,
exact deployment/pod tag and repository, and the registry-verified runtime
manifest digest produce `mode: candidate-verification`, `status: verified`, and
`verified_release: true`. Candidate inputs are read safely again before the
receipt is published. A changed input or resource version fails and can be
retried. Stale revisions, healthy wrong images, unready workloads, mismatched
runtime digests and bad CI references fail; no prior success is reused.

Candidate receipts contain the complete candidate and its canonical SHA256
`candidate_id`. Each run atomically replaces both
`candidates/<candidate_id>.json` and `latest.json` in the state directory; each
file is flushed and directory-synced independently. The indexed file records
the most recent result for that candidate, including transient failures and
later recovery. It survives candidate removal and later observation runs. The first successful
receipt is also saved without replacement at `verified/<candidate_id>.json`,
so later unrelated cluster revisions cannot erase the original proof. This
historical proof never bypasses a new observation or changes a failed result.
Consumers must require a successful process and a current receipt with
`status: verified` and `verified_release: true`; a historical receipt alone is
not current health evidence. State is private local evidence, not a signed
external attestation. Use a single timer/operator writer for one state path.

Failures retain the observed Flux attempted/applied revision and selected condition
reason/status fields, deployment generation/readiness/image and pod image IDs/state
kinds. Condition messages and termination logs are excluded. This holds even when
Flux health fails before detailed rollout validation. Error text includes
actual versus expected revision/image/digest for candidate checks. Inspect
`latest.json` and the service journal after a broken rollout, retry the same
candidate after reconciliation, and remove/replace the root-owned candidate
only as a deliberate operator action. No installation, image build, rollout,
rollback, or credential provisioning is performed by this verifier.

Run local fixture checks with:

```sh
python3 -m unittest discover -s tests -p test_pi_kube_maintenance.py
```

`--observe-only` explicitly ignores both automatic and explicit candidate input
and cannot be combined with `--candidate-file`. Use it for an independent target
when the canary's automatic candidate is present. Existing timer invocations
retain their original candidate behavior.

The trusted controller may bind a release merge to a later, independently proven
GitOps revision. Optional `release.gitops_revision_sha` defaults to `merge_sha`.
If it differs, `expected_revision` must use that SHA and `revision_evidence` must
bind `release_merge_sha`, `revision_sha`, `relation: ahead`, an HTTPS
`compare_url`, the exact `desired_image`, immutable `file` and 40-character
`blob_sha`. The controller verifies ancestry and unchanged image pin before
publishing this packet; the node trusts that evidence like its existing CI and
registry references. It still independently requires the exact live Flux
revision, image, runtime digest and two stable healthy snapshots. An unrelated
commit never replaces the original release merge or its post-merge checks.
