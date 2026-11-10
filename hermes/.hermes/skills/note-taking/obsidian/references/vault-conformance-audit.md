# Wiki vault conformance audit

Read-only audit of a schema-governed wiki vault (`SCHEMA.md` at vault root, `RW/` knowledge layers, append-only `RW/log.md`, catalog `RW/index.md`). Run it when asked to "check the log" or "check the index", or after a delegated ingest/commit lands — before repeating any report about the vault's state.

## Check battery

```bash
cd <vault>
# 1. Log shape: entries and their order
grep -n '^## \[' RW/log.md
# 2. Entry-type drift: types in use vs the documented set
grep -o '^## \[[^]]*\] [a-z-]*' RW/log.md | awk '{print $NF}' | sort | uniq -c
# 3. Cosmetic: double blank lines between entries
awk 'prev=="" && $0=="" {print NR": double blank"} {prev=$0}' RW/log.md
# 4. Catalog counts vs actual files
grep -nE '^## (Sources|Topics|Entities|Synthesis)' RW/index.md
for d in sources topics entities synthesis; do printf '%s: ' "$d"; ls RW/$d/*.md | wc -l; done
# 5. Schema and repo statements vs reality
git remote -v; git status -sb | head -1; cat .gitignore
```

Then spot-check every numeric claim in the log with `ls`/`wc -l` ("14 separate `RW/topics/bc-*.md` notes" → `ls RW/topics/bc-*.md | wc -l`).

## Rules

- `log.md` is append-only, newest at the bottom, one greppable `## [YYYY-MM-DD HH:MM] <type> | <title>` header plus `- touched:`. Test order and headers; never edit or delete an entry to make it true — correct it with a new entry.
- A log whose entries each end "no commit or push" while the repo has pushed commits is a MISSING ENTRY, not a contradiction. Those lines were true when written; the fix is a new entry recording the commit/push, not edits to history.
- Compare types in use against the documented whitelist (header block and `SCHEMA.md`). Drift means documentation is stale — name which side should change instead of silently using the undeclared type.
- Catalog counts must equal real file counts per page type; report both numbers when they diverge.
- Treat statements in `SCHEMA.md` about the environment as dated, not eternal: "no remote is configured", the `.gitignore` list, and the entry-type whitelist were true at scaffold time and go stale silently. Verify each against `git remote -v`, `.gitignore`, and the log before repeating it.
- Obsidian per-device state (`workspace.json`, `graph.json`) belongs in `.gitignore`; a permanently untracked `.obsidian/*.json` means the ignore list is incomplete, not that the last commit was sloppy.
- A commit that bundles many ingests is a schema deviation worth naming ("keep each completed ingest separate") only when the individual runs were authorized to commit and chose not to; if each run was correctly forbidden to commit, bundling is the only available outcome and is not a defect.
- The append-only rule protects dated entries, not the specification: correcting the log's own format block, the entry-type whitelist, or a stale `SCHEMA.md` statement is maintenance, not history rewriting.

## Markdown lint gate

`markdownlint-cli2` is what vault commits should gate on. When npm's global prefix is not writable, install without root: `npm install -g --prefix "$HOME/.local" markdownlint-cli2` drops it at `~/.local/bin/markdownlint-cli2`, which is on the gateway PATH. Confirm a bot can reach it, not just your interactive shell: `env -i HOME="$HOME" PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin" markdownlint-cli2 --version`. A distro package may carry the same build (`extra/markdownlint-cli2` on Arch) — pick one, never both, or the binary on PATH is ambiguous.

Measure before gating. On a prose wiki vault the stock ruleset returns four figures dominated by rules that are wrong for prose: MD013 (line length), MD060 (table column style), MD025 (frontmatter `title` plus an H1 reads as two top-level headings). Disable those three and the residue is signal — MD012 multiple blanks, MD022/MD032 blanks around headings and lists, MD058 blanks around tables, MD034 bare URLs, MD028 blank line inside a blockquote.

Never run `--fix` against the live vault first. Copy it, fix the copy, read the diff:

```bash
cp -r <vault> /tmp/vcopy
cd /tmp/vcopy && markdownlint-cli2 --config /tmp/ml.jsonc --fix "RW/**/*.md" "SCHEMA.md" "AGENTS.md"
diff -rq <vault> /tmp/vcopy | grep -v '^Only in'
```

Restrict `--fix` to the blank-line rules (MD012/MD022/MD032) and assert the diff is blank-line-only before applying it for real. Gate the commit on changed files rather than a whole-vault clean run: an untuned vault only runs clean after a formatting pass that rewrites authored prose, which a wiki commit should not do.

Pin the restrictions in the vault's own config so no later agent has to remember them — `.markdownlint-cli2.jsonc` at the vault root, auto-discovered from the working directory:

```jsonc
{ "ignores": ["RW/raw-evidence/**"],
  "config": { "MD013": false, "MD060": false, "MD025": false } }
```

The exclusion is not cosmetic. `--fix` applies every fixable rule and MD034 is fixable: it rewrites bare URLs as `<autolink>` inside archived artifacts, invalidating the sha256 values their manifests record. Point it at an evidence tree once and the evidence is gone.

Re-verify archived hashes after any fix pass, before committing. Treat a manifest that parses zero artifacts as a failed check, not a clean one — bundles do not share key names (`artifacts` in some, `files` in others), so probe both and assert non-zero before trusting the result:

```bash
python3 - <<'PY'
import json, hashlib, pathlib
for mp in sorted(pathlib.Path("RW/raw-evidence").rglob("archive-manifest.json")):
    man = json.loads(mp.read_text())
    ent = man.get("artifacts") or man.get("files") or []
    assert ent, f"{mp}: parsed 0 artifacts — wrong key, this check proved nothing"
    for e in ent:
        name = e.get("path") or e.get("name")
        p = pathlib.Path(name) if str(name).startswith("RW/") else mp.parent / name
        got = hashlib.sha256(p.read_bytes()).hexdigest()
        assert got == (e.get("sha256") or "").lower(), f"MISMATCH {p}"
print("raw evidence intact")
PY
```

When the autofix normalises something the schema documents — it inserts a blank line between every `## [..]` log header and its bullets — change the format block and the schema example to match. That block is maintenance, not history; fighting the linter to keep a heading-then-bullet shape loses on every run.

## Reporting shape

Findings first, each with the command output that shows it; separate real defects from cosmetic drift; then offer the concrete fix (append an entry, correct counts, add a `.gitignore` line) rather than applying vault writes unasked.
