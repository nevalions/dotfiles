# Starter deployment map: yt-downloader

Evidence classification: **repo-documented/local metadata, not live-verified**. Prepared from read-only local sources and board `main`; no cluster commands run. This map grants no production authority.

## Sources and identities
- App clone `/home/linroot/code/yt-downloader`, observed HEAD `e4001e7b2db7434933e81d05f440eea389ae28b7`; deployment clone `/home/linroot/code/kube-lvl47`, HEAD `9e083f80dfbd4221859bc57749e6f1957129d05e`.
- Retained candidates (preserve unchanged): `/home/linroot/code/.worktrees/t_962621b6/yt-downloader` and `/home/linroot/code/.worktrees/t_962621b6/kube-lvl47`. Historical board packet binds these SHAs; this preparation did not revalidate candidate cleanliness or freshness and does not authorize editing them.
- kube `README.md:3,41–51`: Flux GitOps, namespace/app Kustomization yt-downloader. `docs/gitops.md:3–11,33–44,168–174`: separate bay/vas clusters track master; bay receiver, vas poll; protected master delivered through reviewed PR/ship path, not direct push.
- `clusters/bay/apps/yt-downloader.yaml:1–19`: Flux Kustomization `flux-system/yt-downloader`, source GitRepository `flux-system`, path `./yt-downloader`, prune/wait true, timeout 5m, interval/retry 10m. This establishes bay's repo configuration, not current reconciliation. No yt-downloader vas deployment established by this inspection.
- `yt-downloader/kustomization.yaml:16–26`: `docker.butakov.su/library/yt-downloader:v0.1.1-7-ge4001e7`; image replacement for nevalions/yt-downloader. This is a tag pin, not verified immutable provenance.
- `deploy/auto-deploy.yaml:55–62`: image above, overlay yt-downloader, cluster bay, Kustomization yt-downloader, hold false, track describe.
- `docs/operations/auto-deploy.md:7–22,72–85,104–109`: poller -> image bump -> deploy-bot PR/auto-merge -> Flux; rollback older pin plus hold true; releasing hold is itself a deployment trigger. No rollback or hold change authorized here.
- kube `yt-downloader/README.md:120–157,204–219`: app/bgutil/xray containers, localhost bgutil 4416 and SOCKS 10808, deployment via image poller. PVC/application data and cookies are excluded from diagnostic setup.
- app `README.md:35–43,263–303,402–452`: app code, models/database, authenticated download/status APIs, Forgejo CI and Harbor image. CI/build/publishing claims are repo-documented only.

## Conflicts and unknowns
App README says main; kube app README/auto-deploy comments say master. Local app `refs/remotes/origin/HEAD` resolves to `origin/main`; this is cached local metadata, not live remote or workflow trigger verification. Verify actual workflow/ref/automation before publication. Root kube README's single-cluster/Flux version and timing summary differs from newer gitops docs and per-app YAML; use exact per-app source for proposed targets and confirm live before execution. Do not infer actual running versions from documentation.

Unknown: current cluster identity and pod UID/imageIDs; actual build digest/provenance; current Flux revision/conditions; actual CI runs; credential-use arrangement; enforced egress for bgutil/extractor/media; endpoint ports; public solver-cache digest; full runner/enforcement; cleanup UID inventory. No standing production authorization has been established by this map.

## Historical observations (not refreshed)
Board `main`, t_e3987a73 comment reports 2026-11-08T12:01:00Z metadata: bay/yt-downloader, Deployment yt-downloader, Service yt-downloader-svc, pod yt-downloader-5c959679c5-cf2rz, UID 5f333f78-b847-4d4e-8dc9-0583fd421c20, app/bgutil/xray ready; app imageID sha256:45e85166e19b739c23a9f1cf4c2a3c2be2444717a4d9f8a0d15dbee701610fd0. This is a read-back of recorded evidence, not a new cluster probe. t_a34e4011/t_72544640 observations/routing completed; MCP did not attest cluster context or experiment isolation. Parent reports real cluster-operator Sol namespace-read smoke and MCP discovery, no live worker test.

## Routing and gates
Orchestrator owns admission; diagnostician only bounded installed MCP observations; cluster-operator prepares local packet and performs only later expressly approved operations; main-implementer edits reviewed candidates; commiter delivers each repo under policy; ci-watcher verifies exact result-SHA checks/build mapping for both repos. Before app publication, approve its automatic image-to-production effect; before deployment repo merge, approve GitOps deployment and affected contexts. General commit permission cannot waive this.

Keep t_e3987a73 human gate, t_8be370a5 experiment and t_19e3c844 final acceptance blocked pending their actual criteria. Setup packet review is not setup execution, experiment approval or incident closure. Reuse existing packet `/home/linroot/.hermes/profiles/planner/cache/t_ca89f87a-command-packet.md` (board t_ca89f87a approved static prerequisite accuracy only) and plan `/home/linroot/.hermes/profiles/planner/cache/t_58a4adca-remediation-plan.md`; do not overwrite them.

Acceptance requires all three: app SHA/build digest/deployment SHA/workload UID-imageID identity; matching Flux source/applied revision and healthy generation/rollout; separately authorized fresh production completed row with non-null file_path and independently verified output file, original diagnostic stderr/log criteria and exact-SHA delivery/CI. Isolated paired-exit samples never satisfy production acceptance. Current delivery, CI, deployment and application acceptance: **not verified by this integration; incident unresolved**.
