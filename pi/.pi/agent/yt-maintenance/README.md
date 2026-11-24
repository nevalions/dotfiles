# Trusted-host yt maintenance

`~/.pi/agent/bin/pi-yt-maintenance` is a deterministic controller. It does not
invoke Pi, a model, or repository-supplied commands. Run it on the trusted PC;
only the existing read-only Kubernetes observer runs on the node. Source merge,
GitOps merge, registry publication, settings and secret changes are outside its
write interface. A qualifying proposal is a PR. The separately installed merge bot may merge only
the approved date-only category after validating the short-lived signature,
current base/head/diff and all required checks independently.

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
to today's UTC date, strictly later than the current source date. An already
owned identical patch may refresh after midnight without changing its epoch;
its date must remain strictly advanced and cannot be in the future. All other bytes and files must match the
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
policy drift stops the controller for review. Root-relative Forgejo job/run URLs
are normalized to the configured trusted HTTPS origin. Absolute evidence URLs
must use that same host and port, with the exact repository Actions path;
credentials, external origins, protocol-relative links, traversal, backslashes,
control characters, queries and fragments are rejected. Status failure messages
identify the exact check/SHA separately from malformed evidence URLs. Path-filtered workflows are
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
the publication job as well as every applicable build/test gate. GitOps
`post_status_contexts` must also be a nonempty explicit list of all applicable
post-merge job contexts; aggregate workflow success alone is insufficient. A scheduled
run cannot substitute for required `push` or `pull_request` evidence.

Read API access needs the two repositories' contents, commits, PRs, status,
Actions and branch protection plus Harbor artifact/reports and registry pull.
Proposal writes additionally require `proposal_enabled: true` **and a separate
explicitly authorized repository-scoped `source.proposal_auth_command`**. The
write client allows only source branch creation, that one Dockerfile update,
PR creation, server-side rebase of its owned PR and signed issue-comment writes. Existing personal/admin read credentials are never automatically
reused for writes. Without the separate grant, `--once` atomically saves exact
qualified content and unified diff in `state.json` under `decisions` with
`awaiting-authorization`; it performs no source write. API commits also require
`source.commit_author` with the operator-approved name/email. No source-merge
endpoint exists in the controller; the independently configured merge bot owns
that operation after checking its separate policy.

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


## Narrow automatic source merge

Signing requires `signing_enabled: true`, `proposal_enabled: true`, the separate
`source.proposal_auth_command`, a dedicated `source.proposal_actor` distinct
from the merger, `source.signing_key_file` and its pinned
`source.signing_public_key_sha256`. The only signed source scope is
`nevalions/yt-downloader`, target `main`, path `Dockerfile`. Provision the writer
separately as a **repository-restricted** Forgejo token with the required
repository/issue write scopes. Live Forgejo Swagger supports token
`repositories: [{owner, name}]`; verify returned token metadata and denial on
other repositories before unattended use. The controller never creates tokens,
changes account permissions or falls back to its read credential for a write.

The workstation private key is an unencrypted PKCS8 PEM Ed25519 key, owned by
the controller user with mode 0600. Only the raw 32-byte public key and its SHA256
fingerprint go to the merge bot. Keys, token helpers and config remain private;
the controller rejects symlink/unsafe key files and a fingerprint mismatch.
Python `cryptography` is required only when signing is enabled. Rotate the
public policy and private config together through an explicit operator action.

The controller records ownership of each PR it creates and persists checkpoints
before branch creation, after PR creation, after rebase and after signature
readback. It never signs a human PR, bootstrap remediation, repair PR, an
unrecorded deterministic branch or a head changed outside its own operation.
An existing unowned matching PR suppresses duplicate proposals but stays
unsigned. Keep controller state through restarts. Immediately before PR creation,
the controller persists an exact intent containing repository, dedicated actor,
base, deterministic branch, committed head and proposed content hash. If PR
creation succeeds but its ownership checkpoint is interrupted, recovery requires
that exact persisted intent and API-confirmed actor/repository/base/branch/head,
a complete one-file tree check and a new production qualification. A changed
base/head, missing intent or mismatched bytes refuses ownership recovery. Other
unowned PRs are never adopted.

Before each signature the controller reads the exact current main and owned PR
head, proves a one-file diff and mode 100644 on both Git objects, checks that only
the anchored epoch line strictly advances without a future date, and
independently collects production qualification again. First proposals use the
current UTC day; an owned unchanged prior-day patch can refresh overnight only
with new qualification and the same exact recorded head/content. It compares two fresh deployment
observations and requires the same qualifying fix. Official APKINDEX/secdb
fetches must be within five minutes of signing; the latest successful exact
immutable image scan must be within 48 hours. Cached local qualification alone
cannot authorize a signature.

When main advances, only an owned PR with the exact previously recorded head
and proven original date-only diff can be rebased using Forgejo's PR update
`style=rebase`. The rebased tree must equal current main plus the original epoch
advance exactly; other changes stop signing. The packet binds the actual new
head so old CI cannot authorize it. If main already has that epoch or later,
the proposal becomes obsolete and waits for rollout without another bump.

A signature is an issue comment, not a PR title/body update:

```
<!-- yt-os-refresh-v1
{"payload":"BASE64_UTF8_JSON","signature":"BASE64_ED25519_SIGNATURE"}
-->
```

The signature covers the exact decoded JSON bytes. Payload schema 1 contains
`type: yt-os-refresh`, repository/target, exact base/head and PR number, path,
before/after SHA256, old/new epoch, numeric issued/expiry times, the full
fresh qualification and the authoritative `protection` snapshot described
below. Lifetime is at most 900 seconds. The node independently
verifies those fields, current source state, required current-head checks and
protection before merging. A changed base/head, expired proof or replay onto
another PR cannot authorize a merge. Scheduled controller passes refresh only
the owned signature comment with PATCH, which avoids revalidating an unchanged
PR through title/body edits; an actual rebase produces a new head requiring
fresh CI. Before a comment write, the new body is checkpointed. After an
interrupted create/update, the controller can adopt only a cryptographically
authentic own comment bound to the exact current PR/base/head/content and
qualification identity, then refresh it with PATCH. An expired signature may
prove comment ownership for this recovery only; it never authorizes a merge.
This avoids repeated comment creation after a crash. Comment reads use the
producer-restricted writer's existing issue scope, without broadening the read
token or calling `/user`. Use a controller interval shorter than the signature
lifetime.

This extension does not authorize the controller to merge, repair source,
modify workflow/policy/settings, widen package/base scope or change credentials.

```sh
python3 -m unittest discover -s tests -p 'test_pi_yt_*.py'
```


### Signed authoritative protection snapshot

The repository-restricted merger token cannot read Forgejo's admin-only
protection rule endpoint. The trusted workstation's existing read identity
therefore supplies that one privileged observation inside the signed payload;
no wider merge-token permissions or new credential are needed. This does not
replace the merger's own repeated live branch/head/content/status checks or
Forgejo's atomic merge enforcement.

Immediately before signing, the controller requires the live `main` branch to
be protected, status checks enabled, the exact current base and exact eight
pilot PR contexts. Its effective protection name must be `main`. It then reads
`/branch_protections/main` using the existing read identity, requires the exact
main rule, exact eight contexts and all three enforcement flags, and rereads
the branch to detect changes. It never infers hidden flags from empty API
fields and never changes the protection settings.

`payload.protection` has exactly these fields:

```json
{
  "repository": "nevalions/yt-downloader",
  "branch": "main",
  "base_sha": "SAME_FULL_BASE_SHA_AS_PAYLOAD",
  "checked_at": 1795435200,
  "apply_to_admins": true,
  "block_on_outdated_branch": true,
  "enable_status_check": true,
  "status_check_contexts": ["EXACT_EIGHT_PINNED_PR_CONTEXTS_IN_SORTED_ORDER"]
}
```

The exact contexts are the four CI lint/typecheck/test/quality-gate PR jobs and
the four security-pr semgrep/gitleaks/trivy-fs/pip-audit PR jobs, including their
literal ` (pull_request)` suffixes. Snapshot time is numeric, no later than
`issued_at`, no more than 900 seconds before it, and still within 900 seconds
when used for merging. Missing/extra fields, wrong source/base, false or
nonboolean flags, reordered/missing/duplicate contexts and stale/future
snapshots fail closed. Expired signatures may establish ownership of an
already existing comment for refresh only; fresh merge authorization always
requires a new snapshot and signature.

## Approved website frontends

The same flow supports exactly these additional producer scopes. All use protected
`master`, `Dockerfile`, `linux/amd64`, Alpine `v3.24` and `libxml2`.

| Producer repository | Site selector / namespace / Deployment / Flux Kustomization | Container | Image suffix / GitOps overlay |
| --- | --- | --- | --- |
| `nevalions/ochistka-musoroprovoda.ru` | `ochistka-musoroprovoda` | `nginx` | `library/ochistka-musoroprovoda-frontend`; `ochistka-musoroprovoda/overlays/prod/kustomization.yaml` |
| `nevalions/videooperator.su` | `videooperator-su` | `nginx` | `library/videooperator-su-frontend`; `videooperator-su/overlays/prod/kustomization.yaml` |
| `nevalions/videosemka.su` | `videosemka-su` | `nginx` | `library/videosemka-su-frontend`; `videosemka-su/overlays/prod/kustomization.yaml` |

`--site SITE` selects `~/.config/pi-yt-maintenance/sites/SITE/config.json`
and `~/.local/state/pi-yt-maintenance/sites/SITE`. The shipped site examples
start with proposals and signing disabled. Pin each site's actual protection,
workflow directory, auth helpers, producer/GitOps bare mirrors and signing key
before enabling it. Never reuse a signer or proposal credential across sites.
The independent `pi-site-maintenance@SITE.timer` units are installed by stow but
must be explicitly enabled after validation. Each instance has its own lock,
qualification/proposal history, pending candidates and verified receipts. State
records its source/target identity and rejects cross-site reuse.

The immutable allowlist binds source repository, default branch, Dockerfile,
image suffix, platform and frontend target/overlay. Each site's exact protected
PR context is `CI / build (pull_request)`; producer post-merge evidence includes
both build and publication. Website runtime source must use a versioned
`nginxinc/nginx-unprivileged:*alpine3.24` base with Alpine/libxml2 guards. The
existing Python/yt policy retains its eight exact contexts. Additional protection
contexts or workflow files stop the flow for policy review.

The signed envelope deliberately retains schema 1, type `yt-os-refresh` and
comment marker `yt-os-refresh-v1`. Its repository and target are bound to the
explicit site policy; the broker must pin the matching site's public key,
repository, actor and image. A proof for one site cannot verify as another site
or as yt. Transport argv is `transport_command + [operation, SITE]`, where only
`observe` and `verify` exist. Compound portal Kustomizations do not authorize
changes to their contact Deployment/image.
