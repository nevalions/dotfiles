---
name: obsidian
description: Read, search, create, edit notes; maintain LLM wiki vaults.
version: 1.2.0
author: Teknium (teknium1), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Obsidian, Notes, Markdown, Vault]
    related_skills: []
---

# Obsidian Vault

Use this skill for filesystem-first Obsidian vault work: reading notes, listing notes, searching note files, creating notes, appending content, adding wikilinks, and maintaining a wiki the agent owns (`index.md`, `log.md`, ingest/query/lint).

## Vault path

Use a known or resolved vault path before calling file tools.

The documented vault-path convention is the `OBSIDIAN_VAULT_PATH` environment variable, for example from `${HERMES_HOME:-~/.hermes}/.env`. If it is unset, use `~/Documents/Obsidian Vault`.

File tools do not expand shell variables. Do not pass paths containing `$OBSIDIAN_VAULT_PATH` to `read_file`, `write_file`, `patch`, or `search_files`; resolve the vault path first and pass a concrete absolute path. Vault paths may contain spaces, which is another reason to prefer file tools over shell commands.

If the vault path is unknown, `terminal` is acceptable for resolving `OBSIDIAN_VAULT_PATH` or checking whether the fallback path exists. Once the path is known, switch back to file tools.

## RO / RW folders

Vaults may be split into two top-level folders:

- `RO/` — **read-only for agents**. Read and search it freely. Never write, edit, append, move, rename, or delete anything under `RO/`, and never `chmod`, `sudo`, or `git checkout` around the rule. If a change is needed there, ask the user, or copy the note into `RW/` and edit the copy.
- `RW/` — **read and write**. All note creation and edits belong here.

File permissions are deliberately **normal** on these folders: the Obsidian app runs as the same OS user as the agent, so a `chmod`-based restriction also locks the app out of its own vault. Enforcement is per agent call instead:

- Hermes: the `pre_tool_call` shell hook `~/.hermes/agent-hooks/vault-ro-guard.py` blocks `write_file`, `patch`, `terminal`, and `execute_code` calls that would modify `RO/`. Reads pass — including read-only Python that merely references the RO path. Verify with `hermes hooks list`; regression suite: `python3 ~/.hermes/agent-hooks/vault-ro-guard-tests.py`.
- Other agents: the vault's `AGENTS.md` states the same rule.

Before creating a note, resolve the target folder: default to `RW/` when the vault has these folders and the user did not name a path. Vault-root files (e.g. `AGENTS.md`) are writable but should stay as configuration, not notes.

## Wiki vault schema (this user's `linroot-wiki-code` vault)

When the vault root contains a `SCHEMA.md`, read it before writing: it is authoritative, and it lives at the vault ROOT — looking for `RW/SCHEMA.md` finds nothing and wastes a turn. That schema requires an ingest to touch more than the obvious page: a dated source page under `RW/sources/`, the topic or entity page itself, an `RW/index.md` entry that stays consistent with the catalog counts, and an `RW/log.md` entry recording touched files, provenance and scope. Writing the topic page alone leaves dangling citations and a stale index.

Keep provenance explicit in these pages: distinguish facts a delegating session verified from checks this session actually ran, and label counts as dated snapshots.

The log and index are also auditable on their own. When asked to "check the log" or "check the index", or after a delegated ingest or commit lands, follow `references/vault-conformance-audit.md`: log order and entry-type drift, catalog counts vs real file counts, and `SCHEMA.md` claims vs current git/ignore state. Two rules from it that decide most verdicts: `log.md` is append-only, so a stale-looking entry is corrected by appending a new one and never by editing history; and a log whose entries all end "no commit or push" while the repo has pushed commits is a missing entry, not a contradiction. The same reference carries the markdown-lint gate; `linroot-wiki-code` now ships its tuned config at the vault root (`.markdownlint-cli2.jsonc`, MD013/MD060/MD025 off, `RW/raw-evidence/**` ignored) and `SCHEMA.md` requires `markdownlint-cli2` to exit 0 on changed notes before a commit. Never run `--fix` over `RW/raw-evidence/**`: it rewrites bare URLs and breaks the manifest sha256 values.

## Where a vault rule belongs

A rule that must bind every agent touching the vault — Hermes bots, Claude Code, Codex — belongs in the vault's own `AGENTS.md`/`SCHEMA.md`. Written only into one profile's skill it never reaches the other harnesses, and per-profile skill copies diverge silently, so the fix has to be re-applied bot by bot. When the rule obliges a delivery actor to record something, define it as metadata rather than prose — e.g. a `cleanup | commit <sha>` log entry carrying SHA, branch and files touched — because a commit-only bot is usually forbidden to author wiki content and will correctly report the gap instead of fixing it. Editing the committing bot's skill is the wrong lever, not a missing fix.

## Read a note

Use `read_file` with the resolved absolute path to the note. Prefer this over `cat` because it provides line numbers and pagination.

## List notes

Use `search_files` with `target: "files"` and the resolved vault path. Prefer this over `find` or `ls`.

- To list all markdown notes, use `pattern: "*.md"` under the vault path.
- To list a subfolder, search under that subfolder's absolute path.

## Search

Use `search_files` for both filename and content searches. Prefer this over `grep`, `find`, or `ls`.

- For filenames, use `search_files` with `target: "files"` and a filename `pattern`.
- For note contents, use `search_files` with `target: "content"`, the content regex as `pattern`, and `file_glob: "*.md"` when you want to restrict matches to markdown notes.

## Create a note

Use `write_file` with the resolved absolute path and the full markdown content. Prefer this over shell heredocs or `echo` because it avoids shell quoting issues and returns structured results.

## Append to a note

Prefer a native file-tool workflow when it is not awkward:

- Read the target note with `read_file`.
- Use `patch` for an anchored append when there is stable context, such as adding a section after an existing heading or appending before a known trailing block.
- Use `write_file` when rewriting the whole note is clearer than constructing a fragile patch.

For an anchored append with `patch`, replace the anchor with the anchor plus the new content.

For a simple append with no stable context, `terminal` is acceptable if it is the clearest safe option.

## Targeted edits

Use `patch` for focused note changes when the current content gives you stable context. Prefer this over shell text rewriting.

## Wikilinks

Obsidian links notes with `[[Note Name]]` syntax. When creating notes, use these to link related content.

## LLM-wiki vaults

A vault may also be an **agent-maintained wiki** (Karpathy's LLM-wiki pattern): the human curates raw sources, an agent compiles them into interlinked pages, and a schema file governs the cycle. When the vault is laid out this way, these hold on every task:

- Read the vault's `AGENTS.md` for raw-source permissions and its schema for workflow. Do not assume `RO/` is the only raw-source location. In `linroot-wiki-code`, requested ingestion permits archiving raw evidence and investigation reports under `RW/` without separate location-only approval. Keep raw artifacts distinct from derived pages, record exact durable paths and provenance, and keep source repositories read-only unless separately authorized. New pages go under `RW/`; never write `RO/`.
- `RW/index.md` (content catalog) is updated on every ingest, filed answer, rename and deletion — read it before searching. `RW/log.md` (append-only timeline) gets one greppable entry per operation.
- Update an existing page before creating a near-duplicate, and add the reverse link on the page you just referenced. For retrospective updates, preserve historical sections but put the latest evidence-backed state near the top with explicit supersession; do not leave an old staged-only statement looking current after activation.
- Prefer self-contained evidence under `RW/raw-evidence/<source>/<revision>/` for requested ingests. Copy authorized sanitized reports/manifests unchanged and verify recorded hashes. When original artifacts contain excluded material, archive explicitly selected sanitized fields instead; record original path/hash, selection scope and capture time, and label the projection as distinct from an unchanged copy. Set `source_path` and active citations to actual vault-relative artifacts so a clone does not require another agent's workspace. Preserve original absolute locations as historical provenance, not live dependencies. For a portability cleanup, copy rather than move/delete the original, update all derived-page citations, and append a migration entry without rewriting log history. If external storage is intentionally retained, cite its actual path and disclose portability limitations; never invent an `RO/` counterpart.
- For requests to keep the wiki current or cover all work, first map each named area to evidence and an existing page; publish a bounded coverage ledger distinguishing independently checked state, retained actor results, actor-only reports and explicit gaps. Separate activation, actual consumer/session loading, tests, repository delivery, deployed identity, application acceptance and board closure. Do not turn an inventory or bounded smoke into universal readiness, or a documentation request into monitoring or operational permission.
- When the user requests wiki-first sequencing, finish and verify the documentation before implementation begins. Return a concise coverage/result summary, exact absolute note/index paths, created-versus-updated scope, link checks and remaining unknowns so the parent can independently read back the handoff.
- A durable answer (comparison, decision, connection) is offered back as a page instead of dying in chat.
- Read the vault's `AGENTS.md` before the first write and follow its schema pointer. Prefer a root-level `SCHEMA.md` for wiki conventions and workflows, with `AGENTS.md` retaining safety policy and requiring that schema. Keep one canonical schema rather than duplicating it; preserve existing permission rules.

Scaffolding order, the schema's required contents, ingest/query/lint steps and the pitfalls that cost time: `references/llm-wiki.md`. Scan with `python3 scripts/check-wikilinks.py <vault>` and separately verify exact raw paths. The bundled checker matches note stems, not vault-relative paths: resolve each reported path-style target against the vault root (with `.md` where appropriate) before classifying it as broken. Report scanner output and manually resolved false positives separately; never claim a clean scanner run when it returned failures. Do not exclude raw-source targets merely because they are under `RO/` or `RW/`. Source-location permission never waives requested-ingestion scope, human review, or evidence checks.
