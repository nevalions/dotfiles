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

A healthy receipt has `status: observed`, `mode: current-observation`, and
`verified_release: false`. It records the currently installed state without a
candidate revision or expected image digest. It cannot prove that a requested
release was delivered or that an image tag resolves to a particular candidate.
A release verifier must separately correlate an authorized candidate revision
and expected digest; this first-install observer makes no such claim.

Run local fixture checks with:

```sh
python3 -m unittest discover -s tests -p test_pi_kube_maintenance.py
```
