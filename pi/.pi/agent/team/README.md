# Pi team CLI

Run `pi-team` instead of `pi` for the team workflow. It loads the bundled subagent and todo examples and appends `workflow.md` to the parent prompt. Add `--model jev/auto` to use Jev for the coordinator; Pi subagent models and effort are pinned in role frontmatter. The AGY implementation worker is pinned separately to `gemini-4-hydrogen-high` at `high` effort.

Ask for an implementation to run the plan, implementation, tests, review, and fixes without routine approvals. Ask for a plan or review only to keep it read-only. In the TUI, `/todos` shows the current session branch's checklist. It is not a shared board, an unattended queue, or a crash-recovery scheduler.

Only the wrapper loads the bundled subagent and todo extensions. `~/.pi/agent/extensions/agy-worker.ts` is auto-loaded in both plain Pi and `pi-team`; the wrapper enables team mode. Role files under `~/.pi/agent/agents` are inert without the subagent extension. The legacy Pi worker role is not used by the team workflow. Workflow rules are prompt policy, not sandbox or permission enforcement.

## Interactive team and local run ledger

The separate `~/.pi/agent/bin/pi-team-run` command records durable checkpoints, CI waits, and closeout dispositions. Use it alongside the interactive team; it does not execute stages. See the [pipeline runbook](pipeline.md) for installation, resume, and the opt-in journal watcher.

Repository implementation tasks need a Beads issue and an authorized claim. Beads owns task state; `/todos` only reflects the current session. Follow the repo's existing sync procedure and don't close an issue until its definition of done is verified. Tracker changes and remote publication still require authorization.

Both launch modes preflight worktree writes and use a per-worktree advisory `flock` plus a Linux bubblewrap namespace. AGY sees a read-only host filesystem with its workspace bound writable; the PID namespace cleans up subprocesses when the launcher exits. The lock covers AGY invocations using this extension, not manual writers. The worker can still read user-accessible files and use the network; this is not a confidentiality boundary or a Codex-style escalation prompt. The Pi coordinator's own tools are unchanged. Authenticate AGY outside the worker if its login requires writing configuration. AGY stays in `accept-edits` with no approval bypass. Do not run this as an unattended service. See the [unattended factory plan](factory-plan.md) for the implementation and pilot gates. Honcho is recall-only by default; see the [operator opt-in](../honcho-cli/README.md) for verified publishing from the coordinator. No automated wiki update is configured.

## Roles

| Role | Provider/model | Effort |
| --- | --- | --- |
| Scout | `opencode-go/deepseek-v4.1-flash` | Medium |
| Planner | `openai-codex/gpt-6.1-sol` | Medium |
| Worker | AGY `gemini-4-hydrogen-high` | High |
| Reviewer | `openai-codex/gpt-6.1-sol` | High |

The parent coordinates; the scout, planner, and reviewer use read-only tools. The coordinator gives the AGY worker an isolated task worktree and verifies its changes and checks. AGY print mode can deny tools; send edit-only assignments and have the coordinator run checks. The tool reports recognized denial categories without printing raw denial entries. In team mode it renews the coordinator's existing Beads claim every 30 seconds during delegation, aborting AGY on a failed heartbeat. The Beads lease TTL must comfortably exceed the renewal interval plus the five-second heartbeat timeout. This is node-local, and idle, planning, review and CI waits are not renewed. Implementation authorization covers ordinary coding, tests, and review fixes, not commits, pushes, merges, deploys, or tracker changes.

## Install and verify

Deploy with `python3 install-agents.py --tools pi --check` and then the same command without `--check`. Requires Linux with working bubblewrap PID namespaces and util-linux `flock`, a managed Pi release with both bundled examples and authenticated routes for the Pi role models, plus an authenticated `agy` on PATH with access to `gemini-4-hydrogen-high`. Repository implementation also needs a working `bd` CLI, an initialized repo tracker, and a documented sync procedure. Verify the tracker with `bd where --json` and inspect the selected issue before admitting work.

On 2026-11-21, before switching the worker to AGY, Pi 1.6.0 completed a live smoke test for the original four Pi roles. A separate disposable-repository test used GPT-6.2 Sol as coordinator: it updated code and docs in a task worktree, ran independent review, closed all milestones, and left the original checkout unchanged without a second user turn. RPC command discovery showed `todos` in `pi-team` but not plain `pi`. Model listing confirmed `jev/auto` was available; the end-to-end test did not exercise Jev routing.

## Proposed: Jev-assisted review routing

Not implemented. `jev/auto` currently selects the coordinator's model, not workflow stages. A future CLI-only integration would ask narrow probability questions about review-relevant properties, such as changes to access control, persisted data, and caller-visible behavior. Coordinator code would map those signals to suggestions for deeper review or extra tests. Start in shadow mode with sanitized fixtures; do not send raw private diffs or transcripts by default. Missing or uncertain signals keep the normal path. Deterministic checks, required review, and authorization stay in force.
