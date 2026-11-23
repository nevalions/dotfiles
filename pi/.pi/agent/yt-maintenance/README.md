# Trusted-host yt maintenance

`~/.pi/agent/bin/pi-yt-maintenance` is a deterministic controller. It does not
invoke Pi, a model, or repository-supplied commands. Run it on the trusted PC;
only the existing read-only Kubernetes observer runs on the node. Source merge,
GitOps merge, registry publication, settings and secret changes are outside its
write interface. A qualifying proposal is a PR requiring separate approval.

The pilot supports only libxml2 on Alpine 3.24 and one configured Linux platform.
It obtains a fresh healthy deployed observation, resolves its immutable runtime
manifest and content-hashed OCI config, and reads the latest successful Harbor
Trivy report for that exact digest. The latest scan summary must remain unchanged
across report retrieval. If the runtime reports a top-level index, it must
contain exactly one runnable platform plus only attestation descriptors
referencing that platform. Multiple runnable platforms fail closed. The runtime
index digest and scanned platform digest are retained separately. Only HIGH/CRITICAL rows for the selected package with
one fixed APK version and exact artifact digest qualify. The official same-branch
Alpine secdb must corroborate the CVE/fixed version and its official main APKINDEX
must contain that package/platform at the fix or later. Native `apk version -t`
performs every version comparison, including revision/suffix ordering.

Modern images must carry the producer's full `org.opencontainers.image.revision`
OCI config label. The immutable Dockerfile at that revision must contain the
Alpine 3.24 and libxml2 minimum guards. An optional private `legacy_baseline`
object can document the first pre-label deployed image only:
`runtime_manifest_digest`, `source_sha`, `alpine_version` and an immutable HTTPS
`evidence_url`. This exception is advisory qualification only: verified release
handoff always requires modern OCI provenance and the full producer checks.

Only `Dockerfile`'s single anchored `ARG APK_PATCH_EPOCH=YYYY-MM-DD` may change,
to today's strictly later valid date. All other bytes and files must match the
current source base; the controller verifies the remote content and complete Git
diff before opening a PR. Current same-scope open PRs and durable qualification
IDs suppress duplicates. A configured initial `legacy_baseline.producer_pr` can
identify the separately reviewed bootstrap remediation; its guarded source is
checked and no competing automatic proposal is created. Once that PR merges,
the old baseline waits for its rollout without another epoch bump. An interrupted branch/file/PR sequence is resumed from
its deterministic branch after validating its entire diff. A closed prior
proposal remains recorded and is not automatically reopened. Empty queues do
not create branches or PRs. Unsupported base/package, stale scans, unavailable
fixes, ambiguous evidence and epochs already at today's date stop proposals.

After a GitOps pin changes, the controller finds the actual pin-changing commit
and its merged PR; an unrelated recent commit is never substituted. It checks
the PR head statuses, complete applicable PR workflows, protection and exact
post-merge push workflows, then does the same for the OCI producer revision, including explicit individual
post-merge publication statuses. Associated-PR lookup uses the exact commit API;
it does not scan every closed PR. Pin history is consumed lazily until the
actual image change is found.
Expected workflow files are compared with the immutable workflow directory;
policy drift stops the controller for review. Path-filtered workflows are
conservatively required. It parses the exact Kustomize `images` entry with
PyYAML, selects the configured registry platform and hashes manifest/config
bytes. A trusted bare mirror proves that the accepted GitOps revision descends
from the pin merge. The accepted revision is the current applied revision when
its pin matches desired, otherwise the default head awaiting Flux. Both its
immutable image blob and ancestry proof are retained in the candidate.

The candidate is sent only through the configured fixed transport operation.
The transport installs a separate root-controlled yt candidate and invokes
`pi-kube-maintenance` under its dedicated account with all target flags and a
separate state directory. The current returned receipt must identify the exact
candidate, be generated during this invocation and report `verified_release`.
The registry tag is checked again before and after observation. A successful
receipt is atomically saved and read back on the PC. Temporary Flux lag leaves
a pending candidate for the next scheduled invocation; there is no internal
sleep/retry loop. Historical success does not turn a new failed check into a
pass. Completed release identities suppress repeated transport verification.

## Local installation and interface

Dependencies: Python 3, PyYAML, Git, the private Ansible/SSH transport, and native
apk-tools. On a host without apk-tools use a pre-pulled, reviewed immutable
Alpine platform image with Docker as in the example. The comparator container
has no network, mounts, capabilities or writable root filesystem. This uses the
trusted PC's normal Docker access; no Docker/Forgejo/Harbor credentials go to the
node. Private auth helpers return one HTTP Authorization header value on stdout;
the controller consumes it in memory, never logs headers/helper stderr, and
refuses HTTP redirects. Do not run credential helpers in an interactive terminal.

Stow `pi` after reviewed delivery. Copy `config.example.json` to
`$XDG_CONFIG_HOME/pi-yt-maintenance/config.json` (default `~/.config`), replace all
example fields with verified values, and set mode 0600. Keep helpers, inventories,
URLs, token references and caches private. Create trusted bare source/GitOps
mirrors with the exact configured origins using existing authenticated Git
access. The controller fetches only the configured branch or its deterministic
proposal branch. The config and mirrors must be owned/trusted by the controller
operator. Set expected contexts/workflow filenames from live branch protection
and current repository workflow files, separately for PR and post-merge push. Source `post_status_contexts` must include
the publication job as well as every applicable build/test gate. A scheduled
run cannot substitute for required `push` or `pull_request` evidence.

Read API access needs the two repositories' contents, commits, PRs, status,
Actions and branch protection plus Harbor artifact/reports and registry pull.
Proposal writes additionally require `proposal_enabled: true` **and a separate
explicitly authorized repository-scoped `source.proposal_auth_command`**. The
write client allows only source branch creation, that one Dockerfile update and
PR creation. Existing personal/admin read credentials are never automatically
reused for writes. Without the separate grant, `--once` atomically saves exact
qualified content and unified diff in `state.json` under `decisions` with
`awaiting-authorization`; it performs no source write. API commits also require
`source.commit_author` with the operator-approved name/email. No source-merge
endpoint exists.

```sh
~/.pi/agent/bin/pi-yt-maintenance --check --qualify-only
~/.pi/agent/bin/pi-yt-maintenance --check
~/.pi/agent/bin/pi-yt-maintenance --once
```

`--config` and `--state-dir` override XDG paths. `--check` performs fresh external
reads (including an observer invocation) and may refresh local Git mirror cache;
it does not change controller state, open proposals or invoke transport verify.
It still checks all gates. `--qualify-only` skips release lookup. `--once` does
one bounded pass; a nonblocking file lock prevents overlapping writers. Helper,
HTTP and kubectl calls have individual timeouts, API pagination is bounded, and
transient failures exit nonzero for the next timer tick. An external systemd
unit should also bound total runtime. No schedule is enabled by stowing this
package; the separately reviewed operator installation owns scheduling.

State defaults to `$XDG_STATE_HOME/pi-yt-maintenance` (`~/.local/state`).
`state.json` records proposals, pending candidate, verified IDs and last report;
`verified/<release-id>.json` retains the exact read-back receipt. Files are private
and atomic. Reports contain evidence identifiers/URLs, never auth values or raw
helper errors. Check `qualification_error`, `handoff_error` and the remote
observer's candidate receipts on failure. Preserve state across restarts to
retain closed-proposal deduplication; loss of local state is still protected
against existing open PRs/deterministic remote branches.

Transport grammar:

* `transport_command + ["observe"]`: empty stdin; one current receipt JSON;
  invoke observer with `--observe-only` and the fixed yt target.
* `transport_command + ["verify"]`: one candidate JSON, at most 64 KiB on stdin;
  install only the dedicated yt candidate, then return one current observer
  receipt JSON even when observation fails. Exit status must follow observation.

Target: context `bay`, Flux namespace `flux-system`, Kustomization/namespace/
Deployment `yt-downloader`, container `app`. Receipt `target` excludes context;
context is a separate receipt field. Candidate target includes it. The existing
canary candidate, state and timer remain independent. Transport code must
validate this exact target and never interpolate candidate fields into commands.

```sh
python3 -m unittest discover -s tests -p 'test_pi_*maintenance.py'
```
