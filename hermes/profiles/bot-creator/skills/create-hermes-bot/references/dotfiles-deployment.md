# Dotfiles deployment for agent profiles

## Inspect before designing

1. Locate the existing dotfiles checkout; read its AGENTS.md and applicable instructions. Inspect `git status --short` before edits so unrelated work remains untouched.
2. Inventory tracked installer scripts, package READMEs, Stow ignore files, and portable configuration inputs. Read actual scripts: a documented flag does not establish safe ordering or profile support.
3. Inspect live symlink targets without printing credential-bearing files. Compare live links with documented ownership; ignore rules do not remove links created by an older installation.
4. Trace each installer's target resolution, preflight, backup, configuration, linking, plugin, and verification stages. Check whether environment variables select the active authoring profile instead of the intended consumer.
5. Run supported dry runs only after reading their implementation. Report syntax validation, link simulation, configuration validation, and actual runtime discovery separately.

## Reuse one deployment entry point

Prefer a thin common entry point over independent synchronization systems. Share target selection, dependency preflight, backups, dry-run reporting, and failure summaries while retaining tool-specific configuration and discovery behavior. Read existing repository commands rather than assuming all tools use an installer: one may use plain Stow while another merges private settings or invokes its native configuration CLI.

Keep portable defaults separate from generated private configuration. Preserve local model/provider selections unless replacing them is explicitly requested. Distinguish add-missing-defaults behavior from enforced synchronization: a local-wins merge will not propagate edits to settings already present.

## Validate targets before any mutation

Validate destination layout and all known conflicts across every selected tool and profile before applying settings or replacing SOUL. Reject foreign links and redirected runtime parents before writes. A Stow package rooted at `.hermes` does not automatically support `profiles/<name>`; an installer that rejects the target only during linking can already have changed the wrong profile.

Keep dry runs free of application CLI calls that can initialize or migrate live state; inspect files and use Stow simulation instead. Use isolated scratch targets for first-install planning when required, and test that the actual destination remains unchanged. Exclude named-profile source packages from default-profile Stow so a default install cannot accidentally deploy every bot. Describe downstream apply failures as potentially partial unless rollback is implemented and tested.

For named bots, select an explicit profile-specific SOUL, settings input, and skill destination. Never reuse a default-profile SOUL for every bot merely because the same installer can resolve its path. Treat Desktop presentation metadata separately from profile files and local canonical chat state.

## Preserve tool-specific symlink behavior

Do not impose `--no-folding` globally. Inspect and preserve known discovery requirements: some agent or skill loaders discover directory links but skip individual symlinked files. Test discovery in the consuming tool, not just link existence.

Keep runtime roots as real local directories. Link only deliberately managed entries or curated subtrees. Directory links can intentionally capture newly authored skill references and scripts in Git, but linking an entire live runtime root can also capture credentials, caches, and state.

Inspect stale links explicitly when a file becomes excluded from Stow. Migrate them with backups and scope approval; a successful Stow simulation does not prove that ignored live files are local.

Use a separate checkout on each machine when installers generate private, Git-ignored files inside the package. Do not share that generated checkout between targets with different private settings.

When testing deployment from an isolated feature worktree, record every live link pointing into it and keep the worktree until those links are deliberately migrated to the durable checkout. Include those exact links and the cleanup dependency in any Git-delivery handoff. After integration, compare the integrated assets, repoint only the owned links, and verify their resolution before removing the worktree; deleting a successfully tested worktree can otherwise break the installed bot. Do not run an all-tool installer merely to relocate one bot's links. Do not imply the primary checkout or remote repository contains changes that exist only in the feature worktree.

## Separate definitions from runtime state

Version SOUL, reviewed custom skills, portable setting inputs, and intentional plugin source. Keep credentials, OAuth tokens, sessions, databases, locks, logs, and caches local. Keep memories local unless the user separately requests a designed sharing mechanism. Deploy schedules to explicitly chosen owners to avoid duplicate execution across hosts.

A copied skill or plugin definition does not install binaries, dependencies, credentials, or runtime tools. Validate these on each target platform. For one continuous bot history across devices, consider clients connected to one backend rather than filesystem synchronization of active databases.

## Verification and reporting

For implementation work, test a fresh destination, an existing destination, a conflicting file, a foreign symlink, a repeated install, an invalid profile target, inherited author-profile environment variables, and dry-run no-write behavior in an isolated fixture. Verify invalid targets fail before any mutation. Exercise the installer itself even if manual linking already made the bot work; a successful manual installation does not test the deployment entry point.

Then, when authorized, verify selected skills and tools in the target profile's fresh runtime. Check installed CLI help first; a bounded smoke-test pattern is `hermes -p <name> chat --oneshot --max-turns 5 --run-budget 120 -s <skill> -q '<read-only test>'`. Ask it to print a fixed marker through terminal and explain why inspection does not authorize deployment. Inspect actual tool output, not only the final claim. This verifies that runtime and loaded skill, not remote installation or Desktop registration.

Report existing implementation, observed gaps, proposed changes, and checks performed separately. Do not describe an inspection request as authorization to migrate live configuration or export all profiles.
