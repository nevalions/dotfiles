# Global Instructions

## Subagents

For every new user task requiring inspection, tools, edits or external research, the parent must read `~/.codex/model-policy.md` once per session, select the least costly adequate supported model/effort, and delegate execution. This includes routine inventories and exact lookups; batch related steps into one cohesive child. Unknown tasks use standard. Explicit user model/effort choices take precedence; never silently substitute an unavailable choice. Conversational, existing-context and status answers needing no new domain work may be direct.

The parent may briefly scope/route, then owns coordination, communication, integration and verification; scoping must not become execution. Children execute directly without further delegation unless appointed coordinators. Delegation preserves authorization, sandbox/approval rules, credentials safeguards and skills' explicit-only invocation limits; it grants no extra external writes or Git stages.

Use named roles only when supported and configured model/effort match the route: prefer read-only `explorer` for search and `code-reviewer` for review. Otherwise use a general agent with supported explicit model/effort and fresh/minimal context (`fork_turns = "none"` where supported). Handoffs include task, paths, authorized actions, ownership, constraints and checks. Research/review agents are read-only; mutating agents have scoped ownership and must preserve others' edits. Parallelize only independent work with exclusive write ownership/isolation; serialize dependent stages and shared-repo writes. Carry findings, not transcripts; verify results with targeted checks before broader ones.

Remember unavailable roles instead of retrying. If spawning/model controls are unavailable, report once and continue authorized work without claiming a switch. Skill prose does not switch models. Reassess routing when scope changes; avoid fragmentation and repeated model-change questions.

### Requested Git workflows

Plain-language requests trigger the same skills as explicit invocations: `commit-task` for issue commits, `pr` for branch push/preparation, `merge` for integration. Delegate to one `git-workflow` executor at `gpt-6-luna / low` when runtime configuration matches; otherwise a narrowly scoped general agent with that explicit configuration, minimal context and `~/.codex/agents/git-workflow.toml` instructions. A user-selected model/effort uses a general agent with that choice. Apply the unavailable-runtime fallback above.

Pass checkout, issue, exact actions/files, checks and exceptions. The executor runs the skill directly without recursive delegation. Wait for it before writing to the same repo; run only requested stages, sequentially. Conflicts/failed checks return to the parent for Sol medium/high assessment. This grants no unrequested commit, push, merge, tag or release. Merge cleanup follows **Merged task cleanup**.

### Waiting and visibility

- Use explicit `wait_agent(timeout_ms = 60000)` when supported; respect lower limits and never block over 60 seconds. No omitted/default or 10-second polling. A timeout proves neither failure, completion nor that a worker is running. Read mailbox updates and verify completion from results/checks.
- After two consecutive timeouts without new evidence, inspect actual agent state and files/output/logs before waiting again. Report evidence/uncertainty; investigate stalls without interrupting/restarting solely for a timeout. No empty pings or reassurance on each wait.
- After an aborted turn/interrupted worker, inspect state first. `send_message` does not resume idle/interrupted workers; use `followup_task` for remaining authorized scope.
- Keep meaningful user updates within 60 seconds. At delegation and first skill use, announce task, owner, known model/effort, skill and purpose together when possible. Omit absent fields; distinguish runtime/accepted configuration from requested/unverified choices. State unavailable runtime details once. Keep native CLI session metrics; it does not show every worker's state.

## Scope and evidence

Edit surgically when the result allows. Do not fix/optimize/extend unrelated or pre-existing behavior unless needed for the requested behavior; report follow-ups. Commit tests only if requested or the repo already keeps this kind, sized like neighboring tests; scratch checks need not be committed.

Never guess or claim success without verification. Separate evidence from hypotheses and test specific hypotheses. After two failed attempts at one issue or repeated no-progress actions, reassess assumptions/root cause; report failures/uncertainty before a materially different, evidence-backed step.

## Git and worktrees

Author: `linroot <nevalions@gmail.com>`; no co-authored-by lines. Prefixes: `feat`, `fix`, `refactor`, `docs`, `chore`. Non-interactive only. Stage explicit files with `git add <file>`, never `-A`. Put multi-line messages in a file and commit with `-F`, never inline `-m` (shell substitution can truncate backticks); verify with `git log -1 --format=%B`.

Lifecycle: `feature/`, `bugfix/`, `hotfix/`, `refactor/`, `docs/` → atomic commits → squash merge to master → tag → cleanup. This is not authorization for unrequested stages. For `kube-lvl47`, worktree per task; never work in the main clone or merge into local master. Squash server-side through a PR using `scripts/ship.sh`.

Every new feature/repo-changing task needs its own isolated worktree and task branch before edits; creation is already authorized. Reuse only the same task's worktree for follow-ups/checks/Git stages. Read-only investigations need none. Prefer native Codex (`--worktree` or `/worktree`) or Herdr support; otherwise `git worktree add`. Name task-specific branch/path, announce them, and pass the same checkout to workers. Run all edits/checks there; preserve original checkout/unrelated work. Follow project setup: fresh worktrees lack ignored env files/dependencies. Never copy secrets into tracked files. `bd` discovers the shared tracker.

### Merged task cleanup

A merge request authorizes removal of its merged task branches locally/remotely and task worktrees only after required CI passes on the exact merged default-branch commit. Commit/push alone does not. Prove this separately per repo, including frontend/backend; never infer one repo's result from another.

Record task branch/source SHA, merge-result SHA and CI evidence. Fetch default and verify the merge result is present. Squash proof requires confirmed merged PR source/target SHAs or recorded local squash-and-push evidence; ancestry/`git branch --merged` alone is insufficient. Pending, failed, cancelled, skipped, unknown or missing required checks block cleanup. If CI is deliberately absent, follow explicit repo validation policy; otherwise retain artifacts/report missing evidence.

Remove only confirmed merged task refs/worktrees unchanged since the recorded source SHA. Preserve default/protected branches, main checkout, dirty/untracked work, valuable ignored files (including env files), active/locked worktrees and unrelated/unmerged tasks. Release finished task processes/sessions; execute cleanup from a retained checkout, never the worktree hosting an active agent. Use non-force worktree removal, exact-SHA guarded local deletion and a remote deletion lease; tolerate absent refs. Never bulk-delete by age/name pattern, force-remove, reset or discard work. Verify final local/remote refs and worktree list; report retained artifacts/reasons.

## Forgejo and CI

Solo owner. Writes only when requested; settings/secrets changes require explicit scope. Plan before PRs/merges.

Before monitoring, record repo, PR, exact source SHA and expected checks. Read all relevant `.forgejo/workflows/` and current branch protection; distinguish PR from post-merge push workflows. Do not assume default-branch-only CI or reuse a previous job count.

Prefer authenticated Forgejo MCP reads. If commit status, protection or Actions reads are missing, use authenticated REST; admin runner-job tools are not substitutes. Inspect live `/swagger.v1.json` for routes/fields. Under `/api/v1/repos/{owner}/{repo}` use:

- `/commits/{sha}/status` and `/commits/{sha}/statuses`: combined `state`, `statuses[].status`.
- `/branch_protections/{branch}`.
- `/actions/runs?head_sha={sha}&limit=50&page=1`: `workflow_runs[]` fields `commit_sha`, `status`, `event`, `workflow_id`, `id`, `html_url`.

Validate every returned `commit_sha` against the requested SHA; paginate as needed. Prefer existing authenticated API access to browser login/vault unlock. Windows process/User environments differ: consume existing User variables in memory without printing values. Never dump credential/config files, persist `BW_SESSION`, export pod tokens, create tokens or change settings to monitor CI.

If terminal credentials are unavailable for `git.butakov.su`, the read-only fallback is context `bay`, namespace `forgejo`, deployment `forgejo-actions-exporter`. Verify it still exposes `/app/exporter.py`; keep credentials in the pod and use `exporter._api_get` only for allowlisted run/status/protection reads, returning only status/run evidence. Example (substitute a verified full SHA):

```bash
kubectl --context bay -n forgejo exec deploy/forgejo-actions-exporter -- python3 -c 'import sys,json; sys.path.insert(0,"/app"); import exporter; d=exporter._api_get("/repos/nevalions/kube-lvl47/commits/"+sys.argv[1]+"/status"); print(json.dumps({"state":d.get("state"),"statuses":[{k:s.get(k) for k in ("context","status","target_url")} for s in d.get("statuses",[])]}))' FULL_SHA
```

Runner health/logs (`bay`, namespace `forgejo-runners`) are supplementary, never CI pass proof. If access fails, report the exact endpoint/authentication path missing; do not treat CI as absent.

A combined success is insufficient: verify every expected required context/workflow run for the source SHA. Immediately before an authorized server-side merge, re-read source SHA and use the merge API SHA guard. If Windows cannot run `scripts/ship.sh`, check a real Python executable (Store stubs are not runtimes), then use authenticated merge REST only after equivalent script gates pass. Never merge into local master. Record confirmed PR source/merge-result SHAs; verify all expected post-merge runs on that exact merged SHA before issue closure/cleanup. Non-passing/missing checks listed in **Merged task cleanup** block completion.

One read-only monitor owns polling; the Git worker owns mutations. Wait at most 60 seconds, refresh evidence after each wait, and report meaningful changes/completion/blockers. Avoid duplicate monitors/unchanged updates. Handoff records checked SHA, context results, workflow events and run IDs/links; add to Beads notes when tracking is authorized.

## Beads tracking

Use `bd` for all task tracking/durable project memory, never markdown TODOs/ad hoc memory files. Read the `beads` skill at `.agents/skills/beads/SKILL.md` or `~/.agents/skills/beads/SKILL.md`. Per-repo data lives in `.beads/`; if absent, `bd init` before agreed tracking. Ask before starting/resuming whether to create a new issue or update an existing one, unless already chosen/authorized this session. When agreed, create/update and claim before work, then append progress notes.

Run `bd prime` when context is missing/stale. Native hooks may load it on Codex 0.129.0+; inspect/toggle with `/hooks`. Descriptions/notes are plain text/Markdown, no HTML. Persistent knowledge uses `bd remember`. Priorities `-p 0..4`: urgent, high, medium, low, trivial (0 highest).

Commands: `bd ready`; `bd show <id>`; `bd create "<title>" -p <0-4> -l <labels> -d <desc> --acceptance <ac>`; `bd update <id> --claim`; `bd update <id> --append-notes <text>`; `bd list --status open --json`; `bd close <id>`.

Close only after requested Git stages finish and required CI passes on the exact final pushed/merged commit. Keep open/report pending, failed, cancelled, skipped, unknown or absent required checks. Issues use local Dolt DB; sync is `refs/dolt/data`, `.beads/issues.jsonl` is passive export. See [Beads sync concepts](https://github.com/gastownhall/beads/blob/main/docs/core-concepts/sync-concepts.md).

## Credentials

Vault: `vault.butakov.su`. When credentials/login are needed, first check `command -v rbw` on supported systems. List names only (`rbw list | grep -i <name>`); pass values directly through stdin (`rbw get '<item>' | <cmd> --password-stdin`) or `~/.local/bin/rbw-env VAR='<item>' -- <cmd>`. Use `'<item>'/<username>` for duplicate names; `'<item>':<field>` for custom fields/notes. Secure-note `--field password` is empty: use a Login or hidden custom `password` field. Locked rbw prompts through pinentry; if absent, report it and ask the user to log in in their own terminal.

Never print, echo/cat, expose bare credential-fetch output in terminal/transcript, or paste secrets into chat.

Windows uses `bw`, not rbw, winget-pinned to 2026.6.x for Vaultwarden compatibility (newer releases 404 on login and cannot unlock). List names only: `bw list items --search <name> | jq -r '.[].name'`; pass `bw get password '<item>' | <cmd> --password-stdin`. `bw status` is unlocked only with `BW_SESSION` in the current process. If locked, ask the user to unlock in their own terminal; never request/paste the master password or `BW_SESSION` in chat.

MCP User variables `FORGEJO_URL`, `FORGEJO_TOKEN`, `PERPLEXITY_API_KEY` are referenced as `${VAR}` in `~/.claude.json`, filled by `C:\code\set-claude-secrets.ps1`. After rerunning it, restart the terminal app; new tabs inherit its stale environment.

## Research and safety

Prefer Context7 for docs/APIs/patterns; Perplexity (`perplexity_search`, preferably `$search`) for security/ecosystem/comparisons as fallback. Source order: official standards → official docs → community → blogs. No fabricated citations/standards or assumed security posture. Do not put AGENTS.md/CLAUDE.md in READMEs.

Run Semgrep CLI/project scan entry point before manual security review. Do not auto-fix without request; file medium/high findings in Beads only when authorized.
