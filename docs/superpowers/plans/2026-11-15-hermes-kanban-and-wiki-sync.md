# Hermes Multi-Profile Kanban Pipeline & Wiki Vault Sync Plan

**Date:** 2026-11-15
**Scope:** `/home/linroot/dotfiles/hermes`, `/home/linroot/.hermes`, and `/home/linroot/vault/linroot-wiki-code`
**Constraint:** Zero paid cloud relays or extra LLM token spend for sync, formatting, or commit bookkeeping.

---

## Goal

1. Eliminate configuration, skill-hosting, and `SOUL.md` drift between live `~/.hermes/profiles/*` and portable `~/dotfiles/hermes/profiles/*`.
2. Reduce Kanban pipeline friction (scratch workspace traps, handoff reserve timeouts, unattended `execute_code` denials, and stale/superseded board clutter).
3. Establish a **3-tier, zero-LLM synchronization architecture** for `/home/linroot/vault/linroot-wiki-code` across Git worktrees, Forgejo (`git.butakov.su`), self-hosted Honcho (`100.64.0.16:18000`), all 25 Hermes profiles, and multi-device Obsidian clients.

---

## Architecture Overview (Wiki & Pipeline Flow)

```
[1. Authoring & Review (Git Worktree)]
  wiki-skill (Author) ---> wt/t_xxxx branch ---> reviewer (Independent Review)
                                                        |
                                                        v (Approved)
[2. Deterministic Gate & Publish (Zero-LLM Script: vault-publish.py)]
  1) markdownlint-cli2 + check-wikilinks.py + index counts + raw-evidence sha256
  2) Fast-forward/merge into /home/linroot/vault/linroot-wiki-code (main)
  3) Commit 1: ingest changes -> read short SHA
  4) Commit 2: append `cleanup | commit <sha>` to RW/log.md -> git push origin main (Forgejo)
                                                        |
            +-------------------------------------------+-------------------------------------------+
            v                                           v                                           v
[3A. Agent Memory Sync (Zero-LLM)]         [3B. Multi-Harness Local Access]            [3C. Live UI Sync (Zero-Cost)]
  Post-commit hook: vault-honcho-sync.py     OBSIDIAN_VAULT_PATH pinned in .env          Syncthing over Tailscale
  Upserts RW/index.md & frontmatter          vault-ro-guard.py blocks RO/ for all        Syncs working tree + RO/ drops
  into Honcho peer `linroot-wiki`            & blocks RW/ for non-wiki profiles          (.stignore excludes .git & workspace.json)
```

---

## Phase 1: Reconcile Dotfiles & Profile Portability (`~/dotfiles/hermes`)

### 1.1 Track Missing & Divergent Profiles
- [ ] **Add `kanban-watch` to `dotfiles/hermes/profiles/kanban-watch/`**:
  - Track `SOUL.md`, `config.base.yaml` (including `kanban.include_role_history: false`), `scripts/kanban_watch.py`, and `skills/kanban-watch/SKILL.md`.
- [ ] **Reconcile `cluster-operator/SOUL.md`**:
  - Copy the live Nov 11 `observer` peer routing instructions (`hermes -p cluster-operator peer dm observer --json ...`) into `dotfiles/hermes/profiles/cluster-operator/SOUL.md` and re-link via `install.py` so running the installer does not revert `cluster-operator` to local `kubectl`.
- [ ] **Reconcile `beads-coordinator` symlinks & `SOUL.md`**:
  - Merge the `## Authorized pipeline integration` section from `/home/linroot/.local/share/hermes-pipeline-integration/dotfiles/hermes/profiles/beads-coordinator/SOUL.md` into `dotfiles/hermes/profiles/beads-coordinator/SOUL.md`.
  - Repoint `~/.hermes/profiles/beads-coordinator/SOUL.md` and `skills/beads-coordination` to `~/dotfiles/hermes/...` and retire the stale `~/.local/share/hermes-pipeline-integration` staging clone.
- [ ] **Sync `config.base.yaml` with Live OpenCode Go & Model Settings**:
  - Update `commiter`, `git-puller`, and `task-creator` `config.base.yaml` to `deepseek-v4.1-flash` (`opencode-go`).
  - Update `orchestrator/config.base.yaml` to `gpt-6.1-sol` and `dotfiles-sync/config.base.yaml` `agent.reasoning_effort` to `low`.
  - Update `fallback_providers` and `agent.reasoning_overrides` across `ansible-operator`, `cluster-operator`, `diagnostician`, `planner`, `researcher`, and `reviewer` so `python3 hermes/install.py --check` reports zero value drift.
  - Update the profile roster table in `dotfiles/hermes/README.md` to cover all 25 profiles.

### 1.2 Decouple Shared Skills from `bot-creator` Runtime Home
- [ ] **Promote shared pipeline skills to `dotfiles/hermes/.hermes/skills/`**:
  - Move `pipeline-contract` (currently hosted inside `~/.hermes/profiles/bot-creator/skills/pipeline-contract`) and `git-freshness` (currently inside `~/.hermes/profiles/git-puller/skills/git-freshness`) into tracked `dotfiles/hermes/.hermes/skills/` (or shared `codex-skills/.agents/skills/`) and link profiles to the canonical stowed location.
- [ ] **Track role-owned specialist skills**:
  - Track `kanban-implementation`, `kanban-review`, `kanban-task-intake`, `pipeline-tester`, `pipeline-browser-tester`, `pipeline-planner`, `pipeline-ci-watcher`, `pipeline-cleaner`, `pipeline-repo-docs`, `ansible-operations`, and `cluster-operations` under their respective `dotfiles/hermes/profiles/<role>/skills/` directories.
- [ ] **Archive one-off incident skills in `bot-creator`**:
  - Move historical incident/prototype skills (`kanban-watch-gap-candidate`, `local-os-auth-handoff-prototype`, `mapped-container-offline-prototype`, etc.) out of active `bot-creator/skills/` into an archive folder to reduce prompt snapshot bloat.

---

## Phase 2: Kanban Pipeline Runtime & Governance Improvements

### 2.1 Register Projects & Eliminate Scratch Workspace Traps
- [ ] **Populate `projects.db` and bind `board.json` defaults**:
  - Register primary repositories (`dotfiles`, `kube-lvl47`, `yt-downloader`, `inbox-watcher`, `linroot-wiki-code`, `ansible`, `hermes-extras`) in `~/.hermes/projects.db`.
  - Set `default_project_id` on corresponding Kanban boards (`dotfiles`, `kube-lvl47`, `main`, `inbox-watcher`, `wiki`, `ansible`) so newly admitted tasks inherit deterministic project Git worktrees instead of irreversible `workspace_kind: scratch`.
- [ ] **Prune stale Git worktrees**:
  - Run `git worktree prune` and clean up the 10 prunable `/tmp/dotfiles-*` worktrees and detached `~/.codex/worktrees/*` clones after verifying no unmerged commits remain.

### 2.2 Standardize Execution Guards, Toolsets & Turn Budgets
- [ ] **Align role toolsets and `approvals` policies**:
  - Define 3 clear profile approval templates:
    1. *Read-Only / Verifier* (`reviewer`, `repo-scout`, `researcher`, `diagnostician`, `ci-watcher`, `kanban-watch`): allow read-only file tools and approved single-purpose verification scripts; disable `execute_code` in `platform_toolsets.cli` so workers never trigger unattended-mode `execute_code` denials on turn 1.
    2. *Worktree Author / Tester* (`main-implementer`, `dotfiles-sync`, `tester`, `browser-tester`, `repo-docs`, `wiki-skill`, `planner`): allow worktree file edits and scoped test runners; block `RO/` vault paths and external network/push.
    3. *Guarded Operator / Delivery* (`commiter`, `cluster-operator`, `ansible-operator`, `cleaner`, `beads-coordinator`): require explicit operation packets and `approvals.mode: smart` / `unattended_mode: deny` for production mutations.
- [ ] **Disable irrelevant bundled consumer skills on worker profiles**:
  - Apply the `skills.disabled` list (excluding `apple-*`, `manim-video`, `songwriting-and-ai-music`, `p5js`, etc.) across all specialist profiles to shrink `.skills_prompt_snapshot.json`.
- [ ] **Enforce checkpoint-before-deadline reserves**:
  - Keep `FAST TRACK` (`references/fast-track.md`) as the default for small config/doc deltas and decouple helper-script unit-test expansion (such as `canonical_manifest.py` synthetic filename edge cases on `dotfiles/t_bcf0715c`) from operational config delivery.
- [x] **Clean up superseded & parked cards (`backlog-priority56-1794774070`)**:
  - Reconciled all 28 open cards across all 9 boards: 20 superseded cards archived (including `dotfiles/t_bcf0715c`, `kube-lvl47/t_d0234b45`, `main/t_962621b6`, 15 obsolete `yt-downloader` micro-cards, and both `autonomy-canary` cards), `main/t_f68fae61` closed (`Done`), and `dotfiles/t_d3fd2f9d` + `delivery/t_f34ccbb9` delivered to `origin/main` at `7ec1747edd988bc7fa14626b9a7830c855d99cf0`.

### 2.3 Prevent 3.1 GB Per-Run `HERMES_HOME` Scratch Bloat in Installer Tests
- [x] **Root cause**:
  - When `hermes/tests/test_install_profiles.py` invokes `install.py` against a brand-new `self.hermes_home` per test method (`7` non-dry-run tests), Hermes PM (`hermes_cli/venv_sync.py:_prepare_borrowed_launch`) sees no `installs/` in the temporary `HERMES_HOME` and provisions a fresh `309 MB` `cache/uv` + `130 MB` `installs/f32efac6eacde290` (`440 MB` per test method = `3.1 GB` per 9-test run, taking `~391s`).
  - Neither `ProfileOverrideContract` nor `FreshInstallAndSelection` in `hermes/tests/test_install_profiles.py` defines `tearDown()`, leaving `3.1 GB` in `~/.hermes/profiles/{dotfiles-sync,reviewer}/cache/scratch/` after every run (`~30.1 GB` accumulated across runs 14–21).
- [x] **Fix in `hermes/tests/test_install_profiles.py`**:
  1. Set `HERMES_DISABLE_LAZY_INSTALLS=1` and symlink `self.hermes_home / "installs"` to the owning `/home/linroot/.hermes/installs` in `setUp(self)` so `activate_dependencies()` uses the committed venv without triggering `_prepare_borrowed_launch` or `publish_launchers`.
  2. Add `tearDown(self)` (`shutil.rmtree(self.home.parent, ignore_errors=True)`) to both test classes so passing test runs leave `0 MB` on disk (verified: 9/9 tests pass in `213.4s` with `0 B` left in `/tmp/hermes-install-test`).
- [x] **Reclaim the ~30.1 GB in `cache/scratch`**:
  - Deleted obsolete test scratch directories under `/home/linroot/.hermes/profiles/dotfiles-sync/cache/scratch/*` (`4.0K` remaining) and `/home/linroot/.hermes/profiles/reviewer/cache/scratch/*` (`4.0K` remaining); all durable receipts remain intact under `/home/linroot/.hermes/profiles/orchestrator/workspaces/observer-provider-delivery/config-separated/completion-9332/`.

---

## Phase 3: `linroot-wiki-code` 3-Tier Zero-LLM Sync Implementation

### 3.1 Tier 1 — Deterministic Staging, Lint, Two-Step Commit & Forgejo Push
- [ ] **Make `RW/raw-evidence/` self-contained for `opencode-go-rollout-2026-11-12`**:
  - Copy the 7 sanitized rollout artifacts from `/home/linroot/.hermes/profiles/bot-creator/opencode-go-rollout/` into `RW/raw-evidence/opencode-go-rollout/2026-11-12/` with an `archive-manifest.json` and update `source_path` in `RW/sources/opencode-go-rollout-2026-11-12.md` so the vault has zero external path dependencies.
- [ ] **Create `dotfiles/hermes/.hermes/skills/note-taking/obsidian/scripts/vault-publish.py`**:
  - Deterministic Python CLI (stdlib only, zero LLM calls) that:
    1. Verifies clean/expected scope in `/home/linroot/vault/linroot-wiki-code` (or merges an approved `wiki` board worktree branch).
    2. Runs `markdownlint-cli2` (using `.markdownlint-cli2.jsonc`) over changed `.md` files (excluding `RW/raw-evidence/**`).
    3. Runs `check-wikilinks.py` and resolves vault-relative path links.
    4. Verifies `RW/index.md` category header counts (`Sources`, `Topics`, `Entities`, `Synthesis`) match actual `.md` file counts on disk.
    5. Verifies all `RW/raw-evidence/**/archive-manifest.json` (`artifacts` / `files`) SHA-256 checksums.
    6. Creates **Commit 1** (`docs: ingest <summary>`) staging only the authorized ingest files.
    7. Reads `git rev-parse --short HEAD` and `git diff-tree --no-commit-id --name-only -r HEAD`, appends the required `## [YYYY-MM-DD HH:MM] cleanup | commit <sha>` block to `RW/log.md`, re-lints `RW/log.md`, and creates **Commit 2** (`docs: record commit <sha>`).
    8. Runs `git push origin main` to `ssh://git@git.butakov.su:2222/nevalions/linroot-wiki-code.git` when `--push` is passed.
- [ ] **Publish the pending Nov 12 ingests (`t_0c05d199` & `t_21001daa`)**:
  - Run `vault-publish.py` to commit and push the 12 currently uncommitted files in `/home/linroot/vault/linroot-wiki-code` cleanly to Forgejo.

### 3.2 Tier 2 — Zero-LLM Vault → Honcho Memory Sync (`peer='linroot-wiki'`)
- [ ] **Create `dotfiles/hermes/.hermes/skills/note-taking/obsidian/scripts/vault-honcho-sync.py`**:
  - Pure Python script (no LLM inference) talking to self-hosted Honcho (`http://100.64.0.16:18000`, workspace `hermes-personal`, peer `linroot-wiki`):
    1. Materializes `peer('linroot-wiki')`.
    2. Parses `RW/index.md` catalog entries into a structured peer card (`honcho_profile(peer='linroot-wiki', card=[...])`) so any bot can inspect the full wiki catalog in one fast call.
    3. Extracts YAML frontmatter + `## Summary` / `## Key claims` bullets from new/updated pages in `RW/{sources,topics,entities,synthesis}/*.md`, deduplicates against existing conclusions, and writes new facts with `source` attribution (`RW/topics/<slug>.md`).
- [ ] **Wire `.githooks/post-commit` in `linroot-wiki-code`**:
  - Configure a tracked `.githooks/post-commit` (with relative `git config core.hooksPath .githooks`) that triggers `vault-honcho-sync.py` best-effort after each commit on `main`.
- [ ] **Pin `OBSIDIAN_VAULT_PATH` & Read-Only Guard Across Profiles**:
  - Add `OBSIDIAN_VAULT_PATH=/home/linroot/vault/linroot-wiki-code` to `dotfiles/hermes/.env.example` and live `~/.hermes/.env`.
  - Extend `vault-ro-guard.py` (or profile hook config) so `RO/` is blocked for all agents and `RW/` writes are blocked for non-author profiles (`researcher`, `planner`, `repo-scout`, `diagnostician`, `reviewer`), allowing safe read-only wiki consultation across the fleet.

### 3.3 Tier 3 — Live Multi-Device & Obsidian App Sync (Syncthing)
- [ ] **Configure `.stignore` in `/home/linroot/vault/linroot-wiki-code`**:
  - Create `/home/linroot/vault/linroot-wiki-code/.stignore` ignoring:
    ```gitignore
    .git
    .obsidian/workspace.json
    .obsidian/workspace-mobile.json
    .obsidian/cache
    .trash
    ```
- [ ] **Share `/home/linroot/vault/linroot-wiki-code` via Syncthing over Tailscale**:
  - Sync the working tree in real time with remote workstations/mobile Obsidian clients without enabling `obsidian-git` 1-minute auto-commits, preserving `SCHEMA.md`'s strict commit-per-ingest history on Forgejo.

---

## Verification Checklist

- [ ] `python3 ~/dotfiles/hermes/install.py --check` exits 0 with no unexpected symlink replacements or model/provider drift.
- [ ] `python3 ~/.hermes/agent-hooks/vault-ro-guard-tests.py` passes 100% of guard regression tests.
- [ ] `vault-publish.py --dry-run` on `/home/linroot/vault/linroot-wiki-code` validates `markdownlint-cli2` (exit 0), `check-wikilinks.py`, `RW/index.md` counts (`Sources: 10`, `Topics: 23`, `Entities: 1`, `Synthesis: 1`), and all `RW/raw-evidence/**/archive-manifest.json` SHA-256 digests.
- [ ] After authorized run of `vault-publish.py --push`, `git -C /home/linroot/vault/linroot-wiki-code status -s` is clean (except ignored UI state), `RW/log.md` ends with the `cleanup | commit <sha>` record, and `main` matches `origin/main` on `git.butakov.su`.
- [ ] `vault-honcho-sync.py --verify` confirms peer `linroot-wiki` in workspace `hermes-personal` matches the catalog counts and topic summaries in `RW/index.md`.
