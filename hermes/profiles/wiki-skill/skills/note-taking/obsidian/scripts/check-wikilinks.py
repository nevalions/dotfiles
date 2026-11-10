#!/usr/bin/env python3
"""Report dangling wikilinks in an Obsidian vault.

Usage:
    python3 check-wikilinks.py [VAULT_PATH] [--allow PREFIX ...]

Strips fenced code blocks and inline code before matching, so illustrative
[[examples]] written as code are not reported. Exit code 1 when dangling
links exist, 0 when clean.

Typical agent call on a vault with RO/RW layers:
    python3 scripts/check-wikilinks.py ~/vault/my-wiki --allow RO/
"""
from __future__ import annotations

import argparse
import os
import re
import sys

SKIP_DIRS = {".git", ".obsidian", ".trash", "node_modules", ".venv", "__pycache__"}
FENCE = re.compile(r"```.*?```", re.S)
INLINE = re.compile(r"`[^`\n]*`")
LINK = re.compile(r"\[\[([^\]|#^]+)")


def strip_code(text: str) -> str:
    return INLINE.sub("", FENCE.sub("", text))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("vault", nargs="?",
                        default=os.environ.get("OBSIDIAN_VAULT_PATH", "."))
    parser.add_argument("--allow", action="append", default=[], metavar="PREFIX",
                        help="ignore link targets starting with this prefix, e.g. RO/")
    args = parser.parse_args()

    vault = os.path.realpath(os.path.expanduser(args.vault))
    if not os.path.isdir(vault):
        print(f"not a directory: {vault}", file=sys.stderr)
        return 2

    pages: dict[str, list[str]] = {}
    for dirpath, dirnames, filenames in os.walk(vault):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if name.endswith(".md"):
                pages.setdefault(name[:-3], []).append(os.path.join(dirpath, name))

    dangling: dict[str, set[str]] = {}
    for paths in pages.values():
        for path in paths:
            with open(path, encoding="utf-8", errors="replace") as handle:
                body = strip_code(handle.read())
            for target in LINK.findall(body):
                target = target.strip()
                if not target or target in pages:
                    continue
                if any(target.startswith(prefix) for prefix in args.allow):
                    continue
                dangling.setdefault(target, set()).add(os.path.relpath(path, vault))

    if not dangling:
        print(f"{len(pages)} pages, no dangling wikilinks")
        return 0

    for target in sorted(dangling):
        sources = ", ".join(sorted(dangling[target]))
        print(f"dangling [[{target}]] in: {sources}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
