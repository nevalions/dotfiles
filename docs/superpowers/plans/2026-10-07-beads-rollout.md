# Pinned Beads client rollout

Goal: prevent an old PATH-selected client from opening modern trackers.

Use a checksum-pinned 1.3.1 release in a versioned lib directory. A launcher checks the exact executable version before forwarding arguments. User installation covers interactive tooling; system installation covers default login, cron and systemd PATH without changing unrelated environment settings. Preserve displaced executables, and document explicit paths for restricted CI or SSH environments.

- [x] Verify wrong-version launcher refusal in a scratch test.
- [x] Implement checksum-verified installer with user and system prefixes and recoverable backups.
- [x] Validate archive rejection, version rejection, argument forwarding and idempotent installation.
- [x] Install user launcher and verify actual local invocation contexts; install system launcher if root authorization can be exercised.
- [x] Inventory tracker working/committed schema, rows and remote before migration.
- [x] Rehearse designated migration on a backup of each tracker before its live operation.
- [x] Preserve and merge xls-bridge deltas explicitly; retain ambiguous states unchanged.
- [x] Verify all26 local schemas and semantic retention;24 fresh-clone remote states independently; document2 no-remote exceptions and local invocation evidence. Record evidence and tracker progress.

Follow-up authorization: commit, push and merge after required checks pass. Parent coordinates those stages separately. Other machines receive instructions only.

Verified result:25 clean trackers hold2659 issues; xls-bridge holds37 plus169 exact local events. All26 working/committed schemas66. Final FAS/SBB used reviewed supported exclusive gates; earlier script concurrency limitations are recorded in the kube rollout report. Other-machine operations remain outside scope; Git shipping results are recorded separately in the Beads issues.

Follow-up: replace package-owned /usr/bin/bd with a locally built pinned Arch package, preserve its old executable, and execute isolated SSH and real cron checks with both default and restricted PATH. No permanent service configuration changes.

- [x] Build pinned package-owned /usr/bin guard; test version refusal and argument forwarding.
- [x] Execute isolated real SSH and cron jobs with the normal invocation path.
- [x] Install the reviewed Arch package with user sudo, preserving the old package binary.
- [x] Verify absolute /usr/bin and restricted-PATH interactive/SSH/cron execution after installation.
Separately authorized commit/push/merge and exact required checks are tracked in the Beads issues before closure.

Follow-up verified: package-owned /usr/bin/bd and all local PATH clients report1.3.1. Both normal/restricted SSH and scheduled cron jobs pass, as does restricted user-systemd execution. The old raw package executable is retained outside PATH; no permanent SSH/cron service settings changed.
