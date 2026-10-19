# CI/CD workflow

This guide describes how we run Forgejo CI/CD across our repositories while
keeping work within the resources of a personal setup. CI validates a change;
the repository's publishing or deployment workflow delivers the merged result.
Each repository defines its own checks and delivery steps.

Develop locally or in a draft pull request, validate the change through the
repository's supported integration path, then validate the resulting default
branch commit. Where PRs are used, validate the latest ready revision before
merging. Older development commits do not each need a passing CI run.

## When CI runs

| Event or state | Expected behavior |
| --- | --- |
| Local development | Run useful local checks and keep intermediate commits local. |
| Ordinary feature branch push | Do not start ordinary CI just for the push. Use a draft PR if remote development is needed. |
| Draft or work-in-progress PR | Skip validation jobs while the change is unfinished. |
| Ready PR opened, updated, or reopened | Validate the latest PR head on `opened`, `synchronize`, or `reopened`. |
| PR title or body edited | Handle `edited`; validate the current head when the PR is ready. |
| New ready PR revision | Run fresh checks for that revision; earlier results do not validate it. Cancel superseded PR validation runs. |
| Merge into the default branch | Run the normal pipeline once for the resulting `main` or `master` commit. Let publishing and deployment finish. |
| Explicit release tag, manual run, or scheduled maintenance | Preserve the repository's intended workflow. Avoid adding duplicate tag checks. |
| Repository intentionally without CI | Follow its documented local validation policy. |

Forgejo maps the configured work-in-progress title prefix to the PR's `draft`
state. Removing that prefix makes the PR ready and emits `edited`. Other edits
to a ready PR's title or body can also cause validation of its current head.
Check the current revision before starting another manual run.

## Before starting

Read the repository's contribution and validation documentation, its
`.forgejo/workflows/` files, and current branch protection. Identify:

- The actual default branch and supported merge procedure or helper.
- The required PR checks and the events that trigger them.
- The pipeline expected after a merge, including any publishing steps.
- Any deliberate local-only validation, release, or maintenance exceptions.

Checks vary by repository. Do not assume every project runs the same tests,
security scans, number of jobs, or merge helper. A branch push or PR request
and a request to integrate into the default branch have different scopes;
follow the repository's procedure and the actions actually requested.

## Operating a change

1. **Develop and check locally.** Use an isolated task branch or worktree.
   Keep unfinished commits local or on a draft PR. Run the local checks that
   apply to the files being changed.
2. **Choose the repository's integration path.** If the repository permits
   direct integration, complete its documented local validation gates and use
   its supported merge procedure, then continue with merged-result validation
   below. When a PR is required or used, make it ready for review and record its
   current source commit and expected checks. Watch validation for that exact
   revision. Cancel superseded PR validation runs when a newer revision takes
   their place; leave default branch publishing and deployment runs alone.
3. **Verify a PR before merging.** Confirm every required check passed for the
   current ready PR head. A combined success indicator alone is insufficient
   if an expected check or workflow is missing. A new commit needs fresh
   checks. Immediately before merging, re-read the source revision and use
   the supported merge procedure's revision guard so a changed head cannot
   slip through with older results.
4. **Verify the merged result.** Record the confirmed source commit and merge
   result. Check the normal default branch pipeline on that exact merge
   commit, including the expected publishing or deployment steps. Do not
   substitute a passing PR run or an older default branch run as evidence.
5. **Clean up after validation.** Fetch the default branch and confirm it
   contains the merge result. Record check names, revision identifiers, and
   run links in the appropriate private task record. Only then remove the
   task's merged branch and worktree according to repository policy.

Pending, failed, cancelled, skipped, unknown, or missing required checks block
cleanup. For an intentionally CI-free repository, its documented local
validation replaces CI evidence. Prove which task revision was merged;
squash merges need a recorded source-to-result relationship, since ordinary
commit ancestry is not enough.

Preserve unrelated branches, dirty or untracked work, valuable ignored files,
and active or locked worktrees. Remove only the task artifacts whose current
revision still matches the recorded merged source. Run cleanup from a retained
checkout and use guarded branch deletion and non-force worktree removal.

## Security scans

Keep each repository's intended scan coverage, severity threshold, and
vulnerability database freshness requirements. Where configured, use approved
database mirrors and caches to reduce repeated downloads and external rate
limits. Infrastructure endpoints and authentication belong in private
configuration, not in this guide or public examples.

A scanner that cannot initialize its database or authenticate has not completed
a vulnerability assessment. Treat that as an operational failure, separately
from actual vulnerability findings. Restore database or authentication access
and rerun the affected checks; do not disable the scanner, weaken its threshold,
or accept stale data to make the pipeline green.

## Troubleshooting and resource use

| Symptom | What to check |
| --- | --- |
| No jobs for an unfinished PR | Draft jobs are intentionally skipped. Make it ready when validation is needed. |
| No validation after making a PR ready | Check `edited` handling, the draft condition, and the repository's workflow events. |
| Several PR runs are queued | Identify the latest head and cancel only superseded PR validation. Reuse valid current-head evidence when no new run is needed. |
| A check is green but merge is blocked | Compare required protection checks with results for the exact current head; inspect missing or non-passing contexts. |
| Scanner fails before reporting findings | Check database initialization, mirror/cache availability, freshness, and authentication. |
| Merge passed but delivery is unfinished | Inspect the pipeline for the exact merged default branch commit and let delivery finish. |
| No CI exists in a repository | Confirm this is intentional and use its documented local checks. Missing access to CI is not proof that CI is absent. |

Keep one monitor responsible for a change's CI status. Avoid duplicate manual
runs, repeated validation of historical commits, and cancellation of ongoing
default branch delivery. Investigate the failing stage before retrying an
unchanged run.

## Keeping this guide public

Document behavior and generic procedures here. Keep private hostnames,
addresses, repository inventories, deployment details, credentials, and actual
run evidence in private configuration or task records. Review new examples,
links, command output, and screenshots before publishing them.
