---
name: git-freshness
description: Use before Git workflows. Check freshness safely.
---

# Git freshness

## Prerequisites
Require an explicit repository path, installed Git, and a verified local git-freshness executable. Inspect its --help before invoking: never invent flags. Follow the target repository's maintained instructions. This skill does not itself enforce Git hooks or supply authentication.

## Workflow start
1. Resolve the requested repository and branch. Do not substitute the current directory if the task specifies another repository.
2. Run `/home/linroot/.local/bin/git-freshness start --repo /absolute/repository/path` for that repository only when workflow synchronization is authorized. Substitute the verified target path using safe argument quoting. Run once before editing begins, not after every tool call. It may fetch and perform a clean fast-forward. Do not manually bypass a blocking result.
3. On dirty state, divergence, detached HEAD, absent upstream, or network failure, report the exact blocker. Preserve existing changes. Ask for a decision or route authorized integration to Commiter.
4. Pass the checked repository, branch, HEAD, result, and remaining limitations to the workflow owner. A previous check does not cover a different repository or branch.

## Before pushing
Use the installed pre-push enforcement. It must check actual pushed refs against fresh remote state and never pull or rewrite a branch during a push. A rejected check is a blocker. Do not bypass hooks, force-push, or retry a potentially successful remote mutation blindly. Local hooksPath overrides and --no-verify can bypass client hooks; report that limitation rather than claiming server enforcement.

## Boundaries
No automatic stash, reset, rebase, deletion, merge-conflict resolution, credential copying, commit, publication, or broad repository scans with mutation. Freshness checks do not authorize new changes. Preserve existing hooks and unrelated config. Non-Git workflows need no Git gate.

## Verification and output
Return observed command exit status, repository and branch identity, whether a fast-forward occurred, and blockers. Verify scripts in disposable local repositories before enabling them globally. Test behind/ahead/diverged histories, dirty files, missing upstream, network failures, existing hook chaining, and linked worktrees. Model availability and hook enforcement are separate checks.
