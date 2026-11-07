---
name: dotfiles-sync
description: Use when syncing agent dotfiles. Inspect, deploy, verify.
---

# Sync assistant definitions through dotfiles

## Activate

Use for inspecting, packaging, updating, or deploying Claude, Codex, or Hermes dotfiles and named bots. Do not activate for unrelated Git delivery or general system administration.

## Inputs and prerequisites

Resolve the dotfiles checkout, selected tools, target home, and named Hermes profiles. Distinguish inspection, packaging, local installation, publication, and remote deployment; these are separate permissions. If no target is supplied, inspect the local checkout first, but obtain an explicit target before a mutating deployment. Never infer the deployment target from this bot's HERMES_HOME.

Require Git, Python, GNU Stow, and the selected tool's CLI where its handler needs it. Check installed command help, not remembered flags. Linux/macOS/WSL are the intended Stow environments; native Windows requires a separately verified path. Missing tools are blockers, not capabilities provided by this skill.

## Procedure

1. Locate the existing checkout. Read AGENTS.md and applicable nested instructions, then inspect Git status, branch, and worktrees. Preserve dirty changes. Follow maintained isolation rules before editing.
2. Read the unified installer's help and implementation before using it. Inspect the existing tool-specific handlers and Stow ignore rules. Do not replace proven Codex directory-link discovery behavior with a global no-folding rule.
3. Inventory portable inputs and live link targets without printing private configuration. Record which source checkout owns each link. Excluded files can still have stale links from an older installation.
4. Build an explicit allowlist: reviewed SOUL, custom skills with supporting resources, portable config inputs, and intentional plugin source. Exclude credentials, OAuth tokens, generated private settings, memories, conversations, databases, caches, logs, locks, and canonical chat identifiers. Do not bulk-copy a live profile or use git add on a runtime tree.
5. For packaging an existing bot, inspect its SOUL and skill ownership and export only authorized definitions. Do not copy bundled skills unnecessarily. Shared skills must be available to the consumer, not merely this bot. Keep tool/provider declarations separate from persona and procedures.
6. For installation, preflight every selected target before mutation. Reject invalid names, path traversal, foreign symlinks, and conflicting files. Do not use Stow --adopt, delete conflicts, or overwrite another bot's SOUL to make a run pass. Backups or replacement need deliberate scope. A named profile must select its own assets.
7. Run the actual supported dry-run mode. Inspect its result before applying. For generated private Codex config, use a separate checkout per machine. Retain local model/provider selections unless explicitly asked to change them. Explain that local-wins defaults do not enforce subsequent changes to existing settings.
8. Apply only the selected deployment. Never implicitly deploy every profile or start gateways/routines. If a step fails, stop, report what already changed, and preserve recovery paths; do not call a multi-step installer transactional unless it is.
9. Verify links, config resolution, and skill discovery in the exact consumer profile. For an authorized fresh-runtime smoke test, use a bounded harmless read-only request and inspect actual tool output. Restart only the selected service when authorized and required. Distinguish structural checks from runtime execution.
10. Review the scoped diff for secrets and unrelated changes. Follow maintained repository Git policies only for the requested delivery stage. A local edit is not a published update, and a push is not a remote installation. Remote targets require explicit host and scope; do not guess credentials or endpoints.

## Safety and failure paths

- Inspect/plan requests cause no deployment or external writes.
- Secrets remain local even in a private Git repository. Report credential presence or absence without values; authenticate through supported flows.
- Never synchronize active SQLite databases or OAuth stores through Git/Stow.
- Do not duplicate scheduled work across hosts. Cron enablement and messaging identities require explicit ownership.
- If a foreign link, local conflict, missing dependency, unsupported platform, or dirty-tree conflict blocks work, report the exact path and safe next decision. Do not silently skip and claim success.
- If the same definitions are needed on several machines, deploy definitions independently. If the same conversation is needed everywhere, propose clients connected to one backend rather than copying live state.

## Verification and output

For code changes test a new target, existing target, repeated apply, conflicting real file, foreign symlink, invalid name, inherited HERMES_HOME, and dry-run no-write behavior in isolated fixtures. Test the selected platform rather than claiming portability from static review.

Report repository/branch, selected tools/profiles/host, files changed, local data preserved, dry-run and test results, installed versus pending work, and any required restart. Provide copyable commands based on the actual checked-in CLI. Never claim a model, MCP server, plugin, Desktop roster entry, or remote host is working from configuration alone.
