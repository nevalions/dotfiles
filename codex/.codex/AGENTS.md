# Global Instructions

## Git

Author: linroot <nevalions@gmail.com>. No co-authored-by lines.
Prefixes: feat, fix, refactor, docs, chore. Non-interactive only. `git add <file>` not `-A`.
Multi-line messages go in a file and commit with `-F`, never inline `-m`: the shell
command-substitutes backticks and silently truncates the message. Read it back with
`git log -1 --format=%B` afterwards.
Branches: feature/ bugfix/ hotfix/ refactor/ docs/ → atomic commits → squash merge to master → tag → cleanup.
kube-lvl47: the squash happens server-side through a PR (`scripts/ship.sh`); never merge
into master locally, never work in the main clone — worktree per task.

## Merged task cleanup

A merge request includes standing authorization to clean its merged task branch locally and remotely and remove its task worktrees after required CI passes on the exact merged default-branch commit. A commit or branch-push request alone does not authorize cleanup. Apply this separately in each repository (including separate frontend and backend repos); never infer one repo's merge or CI result from another.

Record the task branch/source SHA, merge result SHA and CI run results. Fetch the default branch and verify the merge result is present there. For squash merges, use confirmed merged PR source/target SHAs or recorded local squash-and-push evidence; ancestry or `git branch --merged` alone is insufficient. Pending, failed, cancelled, skipped or unknown required checks block cleanup. If CI is intentionally absent, follow the repository's explicit validation policy; otherwise retain the task artifacts and report missing evidence.

Clean only the confirmed merged task refs and worktrees, with no new commits since the recorded source SHA. Preserve default/protected branches, the main checkout, dirty/untracked work, valuable ignored files (including environment files), active/locked worktrees and unrelated or unmerged tasks. Release finished task sessions/processes and move cleanup execution to a retained checkout before removal; never remove the worktree still hosting an active agent. Use non-force worktree removal, exact-SHA guarded branch deletion and a remote deletion lease; tolerate already deleted refs. Do not bulk-delete by age or branch-name pattern, force-remove worktrees, reset or discard work. Verify the final local/remote refs and worktree list, and report anything retained with the reason.

## Worktrees

Every new feature or repository-changing task must use its own isolated Git worktree and task branch before editing files. This is standing authorization to create the worktree without asking again. Never implement a new feature in the main checkout or reuse a worktree belonging to a different task. Continue in an existing worktree only when it belongs to the same task; follow-up fixes, verification and requested Git stages stay there. Read-only investigations need no worktree.

Prefer native Codex worktree support (`--worktree` for a new session or `/worktree` in the current session), or Herdr's worktree command when running in Herdr. Fall back to `git worktree add` when native support is unavailable. Give the worktree and branch a task-specific name, announce their paths, and pass that same checkout to delegated workers. Run every edit and verification command with the worktree as its working directory. Leave the original checkout and unrelated changes intact. Follow project setup instructions; ignored environment files and installed dependencies are absent in fresh checkouts. Never copy secrets into tracked files. `bd` discovers the shared tracker.

## Forgejo

Solo owner. Write actions only when requested. No settings/secrets changes unless stated. Plan before PRs/merges.

## Scope of changes

If, while working or testing, you find a pre-existing bug, a performance concern, or behavior the task doesn't mention, don't fix, optimize or extend it in this change unless the requested behavior cannot work without it; report it as a follow-up in your summary. Commit tests only where the task asks for them or the repo already keeps tests for this kind of change, sized like the neighboring test files; scratch checks need not be kept.

When it will not affect the end result, surgically edit a file rather than rewrite the entire thing.

## Troubleshooting

Never guess when solving a problem. Separate evidence from hypotheses and test specific hypotheses. After two unsuccessful attempts at the same issue, or repeated actions that make no progress, stop retrying and reassess assumptions and root cause using the evidence collected. Report what failed and what remains uncertain before taking a materially different, evidence-backed next step. Never claim success without verification.

## Subagents

Delegated child guard: if you are already executing a parent's assigned task, execute it directly without recursive delegation unless the parent explicitly designates you as a coordinator. The automatic routing trigger below applies to the parent receiving a new user task.

Standing authorization: before executing any new user task that requires file inspection, tools, edits or external research, the parent selects a route using `~/.codex/model-policy.md` and delegates task execution. This covers code, research, documentation, debugging, review, operations, data and design, including routine inventories and exact file lookups. A task is not exempt because a few commands can solve it. Batch related small steps into one child; do not ask the user to repeat "use a subagent". Direct responses are limited to conversational, existing-context or status answers needing no new domain work. Unknown tasks default to standard; explicit user model/effort choices take precedence.

The parent may perform brief scoping and routing checks, then owns coordination, user communication, integration and verification; it must not complete the task during scoping instead of delegating. Prefer one cohesive child. Parallelize independent tasks only with exclusive write ownership and isolation where needed; run dependent stages and shared-repository writes sequentially. Give each child a compact handoff with the concrete task, relevant context and paths, exact authorized actions, ownership, constraints and existing check results. Tell mutating workers they are not alone and must preserve others' edits.

Use a named role only when the runtime supports it and its configured model/effort match the selected route. Prefer read-only `explorer` for searches and `code-reviewer` for reviews when those conditions hold. Otherwise use a general agent with explicit supported model/effort spawn arguments and fresh/minimal context (`fork_turns = "none"` where supported); give research/review agents read-only instructions and mutating agents scoped ownership. Remember unavailable roles for the session and use the fallback without repeated failed attempts. If spawning or model overrides are unavailable, report the limitation once and continue authorized work without claiming a model switch. Carry findings rather than transcripts, and run targeted checks before broader checks.

Delegation preserves action authorization, sandbox/approval rules, credential handling and skills' explicit-only invocation metadata. Standing authorization to delegate does not authorize additional external writes, Git stages or other actions.

When awaiting a delegated agent, call `wait_agent` with explicit `timeout_ms = 60000` when the runtime permits; respect a lower runtime limit and never block longer than 60 seconds. Do not poll with `timeout_ms = 10000` or an omitted/default timeout. A timeout means no mailbox update arrived during that interval; it proves neither failure nor completion. Read new mailbox messages when the wait returns an update, and verify completion from the returned result and relevant checks before proceeding.

Keep user updates within 60 seconds during ongoing work, tied to meaningful milestones, known evidence, remaining uncertainty or the next check. Do not repeat empty status messages, send a follow-up/status ping to the worker on every timeout, or offer reassurance unsupported by evidence. After two consecutive timeouts without new evidence, inspect the agent's actual state and available progress evidence (such as changed files, command output or logs) before waiting again. Report what is known and uncertain; investigate a suspected stall using that evidence. Do not interrupt or restart an agent merely because a wait timed out.

For explicitly requested Git actions, including plain-language requests without `$`, load the matching skill: `commit-task` for committing an issue, `pr` for branch push/preparation, and `merge` for integrating a branch. Delegate execution to one `git-workflow` agent when available with matching Luna low configuration; otherwise use the general-agent fallback below. Do not ask the user to repeat a subagent instruction. Pass the repository/checkout, issue, exact authorized actions and files, existing check results, and applicable exceptions. If the custom role is unavailable or its configuration does not match the selected model/effort, use a narrowly scoped general agent with explicit `model = "gpt-6-luna"`, `reasoning_effort = "low"`, fresh/minimal context and the Git executor instructions from `~/.codex/agents/git-workflow.toml`. If the user specifies another model/effort, use a general agent with that choice instead of the fixed Luna role; never silently substitute an unavailable requested model. If spawning or model overrides are unavailable, report the routing limitation once before continuing on the current model.

Wait for the Git worker before writing to the same repository. Run dependent commit/push/merge stages sequentially, and do only the stages requested. A delegated Git worker executes the matching skill directly and never delegates it again. Conflicts or failed checks return to the parent for Sol medium/high assessment. This rule authorizes delegation, not unrequested commits, pushes, merges, tags or releases. Cleanup included in a requested merge follows Merged task cleanup above.

## Model selection

Before executing a new user task, select the least costly adequate model and reasoning effort using `~/.codex/model-policy.md` (read once per session when needed). Routine lookups and mechanical work use Luna low; normal implementation uses Sol medium; complex review/debugging uses Sol high; reserve Astra for the hardest work. Apply supported runtime controls or configured agent defaults; skill prose does not switch the parent model. Reassess when the task changes, avoid needless fragmentation and repeated model-change questions, and report a useful runtime mismatch once when no switching control is available.

## Execution visibility

At delegation and first use of a skill, give one concise commentary announcement with the task, owning agent, known model and effort, skill, and purpose. Combine related announcements when possible; omit absent fields and avoid repeating unchanged details. Example: `Configure footer · worker / gpt-6.1-sol · medium · verification-before-completion · check live config`.

Report the model and effort supplied by runtime metadata or the accepted spawn configuration; label requested or unverified choices accordingly. If actual runtime details are unavailable, say so once rather than inventing them. Skills do not switch models, and tools execute in the agent that calls them. Announcements describe delegation and skill use, not instrumentation of every tool call. Keep the native CLI footer for session metrics; it does not display every worker's execution state.

## MCP sources

1. Context7 — docs, APIs, patterns (primary)
2. Perplexity (`perplexity_search`) — security, ecosystem, comparisons (fallback)

Priority: official standards > official docs > community > blogs.

## Beads (bd)

Per-repo issue tracker (`bd`). Data lives in `.beads/`. Run `bd prime` for full workflow. If a repo has no `.beads/`, `bd init` first.

Priority: `-p 0..4`, **0 = highest**. 0=Urgent 1=High 2=Medium 3=Low 4=Trivial.

Descriptions/notes: plain text or markdown (no HTML). Use `bd remember` for persistent knowledge, rather than a separate memory file.

Before starting or resuming task work, ask the user whether to create a new Beads issue or update an existing one. If the user has already authorized or chosen an issue in this session, follow that direction without asking again. When agreed, create or update and claim the issue before work begins, then add progress notes as work continues.

Close a tracked issue only after the authorized commit, push, or merge stages are complete and required CI passes on the exact final pushed or merged commit. Keep it open and report the status if required checks are pending, failed, cancelled, skipped, unknown, or absent.

Core commands: `bd ready` (available work), `bd show <id>`, `bd create "<title>" -p <0-4> -l <labels> -d <desc> --acceptance <ac>`, `bd update <id> --claim` (start), `bd update <id> --append-notes <text>` (progress), `bd close <id>` (done), `bd list --status open --json`.

## Secrets and logins (Vaultwarden via rbw)

Passwords, tokens and keys live in the human vault (`vault.butakov.su`). When a
command needs a credential, or a login is required, **first check
`command -v rbw`**. If it exists, fetch the value from the vault and hand it to
the consumer without ever printing it:

- `rbw list | grep -i <name>` to find the item (names only, safe to print).
- `rbw get '<item>' | <cmd> --password-stdin` for stdin-reading tools.
- `rbw-env VAR='<item>' -- <cmd>` (`~/.local/bin/rbw-env`) when the tool wants
  an env var; `VAR='<item>'/<username>` when names repeat,
  `VAR='<item>':<field>` for a custom field or `notes`.
- `rbw get '<item>' --field password` on a Secure note is empty: the value must
  be a Login, or the note needs a hidden custom field named `password`.

Never run a bare `rbw get` whose output lands in the terminal or the
transcript, never `echo`/`cat` a fetched secret, never paste one into chat. If
rbw is locked, the first call prompts the user through pinentry; if it is not
installed, say so and ask the user to run the login themselves (their own terminal).

**Windows:** rbw does not run there; the vault is reached with `bw` (Bitwarden
CLI, winget-pinned to 2026.6.x to match Vaultwarden — newer releases 404 during
login and leave a vault that will not unlock). Same rules: names only, never
print a value.

- `bw status` reports `unlocked` only when `BW_SESSION` is set in this process.
  Unlocking needs the master password, so if it is locked, ask the user to run
  the command in their own terminal, and never paste `BW_SESSION`
  into chat.
- `bw list items --search <name> | jq -r '.[].name'` to find the item.
- `bw get password '<item>' | <cmd> --password-stdin` for stdin-reading tools.
- MCP keys (`FORGEJO_URL`, `FORGEJO_TOKEN`, `PERPLEXITY_API_KEY`) are user env
  vars that `~/.claude.json` references as `${VAR}`, filled by
  `C:\code\set-claude-secrets.ps1`. After re-running it, restart the terminal
  app, not just Claude Code: new tabs inherit the terminal's stale environment.

## Safety

No fabricated citations/standards. No assumed security posture. No AGENTS.md/CLAUDE.md in READMEs.

## Semgrep and research

Use the Semgrep CLI or project scan entry point before manual security review. Do not auto-fix findings without a request. File medium/high findings to bd when authorized. Prefer `$search` for Perplexity-backed research, with official sources first.
