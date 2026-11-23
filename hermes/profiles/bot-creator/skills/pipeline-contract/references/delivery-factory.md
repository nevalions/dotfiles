# Delivery Workflow

- Local commits, branch pushes, PRs, and merges are handled by `commiter` according to repository rules (e.g., `scripts/ship.sh`).
- Independent CI verification is handled by `ci-watcher` when required.
- Live Kubernetes observations use `cluster-operator` via the `observer` peer.
