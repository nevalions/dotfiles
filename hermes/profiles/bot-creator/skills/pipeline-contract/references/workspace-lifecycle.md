# Verified candidate lifecycle

## Supported choice

Create one owned native Git linked worktree, then use `workspace_kind="dir"` with its canonical absolute path on EVERY sequential planner, implementer, review-origin source, tester, browser-tester, repo-docs and Commiter card. Verify it exists and its Git common dir/branch/base match evidence before resolving it: `dir` resolution creates missing directories, which by itself is not proof of a valid checkout. Explicitly verify runtime workdir before edits; block on mismatch. Native review stays on the same source card.

Do not use native `worktree` or `worktree:<absolute>` as a retention guarantee. Installed cleanup preserves dirty/unpushed work but removes a clean worktree whose commits are reachable from remote-tracking refs. Active children defer cleanup only; the last child can trigger parent removal. No task (including parents/other boards) may own the retained checkout as removable scratch/worktree. Use explicit owned cleanup only after the contract cleanup gate and fresh human approval. No blanket pruning. Production candidates must be durable paths, not this test's ephemeral scratch directory.

## Mandatory admission readback

BEFORE repo-edit admission, canonical Orchestrator establishes the retained candidate and reads the parked card back: read back persisted workspace_kind and canonical absolute workspace path, require `workspace_kind="dir"`, and compare against the owned candidate's existing Git common directory, branch/base and full candidate digest (including staged, unstaged and untracked contents). Record authority, assignee and independent reviewer. A task-body path or a worker's reported cwd is not native binding evidence.

- Missing binding => NOT ADMITTED; establish and verify it before release.
- Wrong binding => NOT ADMITTED; scratch, removable worktree or another directory cannot substitute for the retained candidate. Explicitly verify actual runtime workdir before the first edit too.
- Workers must not silently create a divergent authoritative candidate, switch checkouts or treat scratch as authoritative. Preserve any already-created candidate and findings; report mismatch and block without further edits.
- When supported edit cannot change the immutable binding, use only the approved coordinator setup-error recovery in [worker progress](worker-progress.md). Do not delete/recreate the candidate, reset review history or copy edits into a newly authoritative tree.

These are caller-enforced admission requirements, not a new native hook; offline document checks cannot prove live rejection.

## Source and regression evidence

Verified installed source HEAD `2bd378ed1b8d6bf2192cb26e0a55ff3091e6bd19`:
- `hermes_cli/kanban_db.py:2640-2744`: real completion, child readiness recomputation, workspace cleanup.
- `hermes_cli/kanban_db_workspace.py:362-423`: `dir` preserved; active children defer removable cleanup; dir completion can sweep removable parents.
- same file `426-496`, `499-537`: clean/reachable worktree removal and deferred parent sweep.
- same file `787-825`: explicit absolute dir resolution.

Local official docs `website/docs/user-guide/features/kanban.md` document `dir` and `worktree:<path>`, but the blanket worktree preservation sentence is weaker than actual installed cleanup behavior. The live docs fetch was blocked by the retrieval service; inspected installed source and exercised it rather than trusting that sentence.

Reproduction (existing managed Python environment, no installs):
`PYTHONDONTWRITEBYTECODE=1 python /home/linroot/.hermes/profiles/bot-creator/cache/scratch/pipeline-verification/native_lifecycle.py`

Observed passing report:
`/home/linroot/.hermes/profiles/bot-creator/cache/scratch/pipeline-verification/native-run-jj8cr_4z/report.json`

The fixture isolates HERMES_HOME, shared HERMES_KANBAN_HOME, DB, workspace root, HOME and Git config in scratch BEFORE importing core. It uses a real SQLite DB and native Git repository, no production cards/repos, no models, no dispatcher. Plan and implementation use native claim/request_review/complete on the same source; sequential test/browser-test/docs/commit cards resolve the identical directory. It asserts unchanged directory inode, Git directory, staged diff, unstaged diff and binary untracked-content hashes after completion; all descendants become ready in order. The final local fixture commit is clean and locally remote-tracking-reachable yet survives as `dir`. A negative control proves `worktree` parent survives while a child is active but is removed after that child's completion. Completion hooks are explicitly disabled. Synthetic task names do not mean actual testing/browser/docs models ran.

This establishes native DB/workspace retention, not full tool/model/dispatcher admission, authenticated evidence, cross-process concurrent safety, or protection against unrelated prune commands. Re-run after source upgrades. Scratch evidence may be pruned; keep durable evidence separately only with authorization. Never turn this fixture into production completion commands.
