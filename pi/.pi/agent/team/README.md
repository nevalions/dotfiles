# Pi team CLI

Run `pi-team` instead of `pi` for the team workflow. It loads the bundled subagent and todo examples and appends `workflow.md` to the parent prompt. Add `--model jev/auto` to use Jev for the coordinator; child models and effort are pinned in role frontmatter.

Ask for an implementation to run the plan, implementation, tests, review, and fixes without routine approvals. Ask for a plan or review only to keep it read-only. In the TUI, `/todos` shows the current session branch's checklist. It is not a shared board, an unattended queue, or a crash-recovery scheduler.

Only the wrapper loads the extensions. Do not add them to Pi's discovered extensions or shared settings. Role files under `~/.pi/agent/agents` are inert without the subagent extension. Workflow rules are prompt policy, not sandbox or permission enforcement.

## Interactive today, unattended factory planned

Repository implementation tasks need a Beads issue and an authorized claim. Beads owns task state; `/todos` only reflects the current session. Follow the repo's existing sync procedure and don't close an issue until its definition of done is verified. Tracker changes and remote publication still require authorization.

A worktree separates changes, not OS privileges: the worker has shell access and runs with the host user's permissions. Do not run this setup as an unattended service. There is no durable dispatcher, enforced sandbox, automatic recovery, or delivery bot. See the [unattended factory plan](factory-plan.md) for the implementation and pilot gates. Honcho is recall-only by default; see the [operator opt-in](../honcho-cli/README.md) for verified publishing from the coordinator. No automated wiki update is configured.

## Roles

| Role | Provider/model | Effort |
| --- | --- | --- |
| Scout | `opencode-go/deepseek-v4.1-flash` | Medium |
| Planner | `openai-codex/gpt-6.1-sol` | Medium |
| Worker | `openai-codex/gpt-6.1-terra` | Medium |
| Reviewer | `openai-codex/gpt-6.1-sol` | High |

The parent coordinates; the scout, planner, and reviewer use read-only tools. Worker edits are scoped to an isolated task worktree. Implementation authorization covers ordinary coding, tests, and review fixes, not commits, pushes, merges, deploys, or tracker changes.

## Install and verify

Deploy with `python3 install-agents.py --tools pi --check` and then the same command without `--check`, or link only `bin/pi-team`, `agents`, and `team` into `~/.pi/agent`. Requires a managed Pi release with both bundled examples and authenticated routes for the role models. Repository implementation also needs a working `bd` CLI, an initialized repo tracker, and a documented sync procedure. Verify the tracker with `bd where --json` and inspect the selected issue before admitting work.

On 2026-11-21, Pi 1.6.0 completed a live smoke test for all four roles. A separate disposable-repository test used GPT-6.2 Sol as coordinator: it updated code and docs in a task worktree, ran independent review, closed all milestones, and left the original checkout unchanged without a second user turn. RPC command discovery showed `todos` in `pi-team` but not plain `pi`. Model listing confirmed `jev/auto` was available; the end-to-end test did not exercise Jev routing.

## Proposed: Jev-assisted review routing

Not implemented. `jev/auto` currently selects the coordinator's model, not workflow stages. A future CLI-only integration would ask narrow probability questions about review-relevant properties, such as changes to access control, persisted data, and caller-visible behavior. Coordinator code would map those signals to suggestions for deeper review or extra tests. Start in shadow mode with sanitized fixtures; do not send raw private diffs or transcripts by default. Missing or uncertain signals keep the normal path. Deterministic checks, required review, and authorization stay in force.
