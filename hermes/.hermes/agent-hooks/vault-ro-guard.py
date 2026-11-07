#!/usr/bin/env python3
"""pre_tool_call guard: forbid writes into the Obsidian vault's RO/ folder.

Policy (see <vault>/AGENTS.md): RO/ is read-only for agents; RW/ is read-write.
Obsidian itself runs as the same user, so this cannot be enforced with file
permissions without also breaking the app -- it is enforced here, per agent tool
call. Reads of RO/ are always allowed.

Wire protocol: JSON payload on stdin, JSON decision on stdout.
  {"decision": "block", "reason": "..."}   -> tool call refused
  {}                                        -> allow
"""
from __future__ import annotations

import ast
import json
import os
import re
import shlex
import sys

MESSAGE_PREFIX = "RO-GUARD: "
VAULT = os.path.realpath(
    os.path.expanduser(os.environ.get("OBSIDIAN_VAULT_PATH") or "~/vault/linroot-wiki-code")
)
RO_DIR = os.path.join(VAULT, "RO")

WRITE_TOOLS = {"write_file", "patch", "multi_edit", "str_replace_editor", "notebook_edit"}
SHELL_TOOLS = {"terminal", "shell", "bash", "run_command"}
CODE_TOOLS = {"execute_code", "python", "run_python"}

WRITE_VERBS = {
    "rm", "rmdir", "unlink", "shred", "mv", "cp", "touch", "mkdir", "ln",
    "truncate", "dd", "tee", "install", "rsync", "sed", "perl", "chmod",
    "chown", "chgrp", "setfacl", "patch", "unzip", "tar", "gzip", "zip",
    "git", "apply_patch", "sponge",
}
INTERPRETERS = {"python", "python3", "node", "ruby", "perl", "bash", "sh", "zsh", "eval", "exec"}
# git subcommands that only read
GIT_READONLY = {
    "status", "log", "diff", "show", "branch", "remote", "rev-parse", "ls-files",
    "blame", "describe", "config", "cat-file", "shortlog", "tag", "fetch",
}
CODE_WRITE_PATTERNS = re.compile(
    r"""open\s*\([^)]*['"][wax]\+?['"]|\.write_text\s*\(|\.write_bytes\s*\(
      |os\.remove|os\.unlink|os\.rename|os\.replace|os\.rmdir|os\.makedirs|os\.mkdir
      |shutil\.(rmtree|move|copy|copy2|copyfile)|pathlib[^\n]*unlink|\.unlink\s*\(
      |sed\s+-i|>\s*\S*/RO/""",
    re.VERBOSE,
)

# --- execute_code inspection -------------------------------------------------
# Attribute/name of a call that can mutate the filesystem.
MUTATING_CALLS = {
    "write_text", "write_bytes", "unlink", "rmdir", "mkdir", "makedirs", "touch",
    "rename", "replace", "remove", "rmtree", "move", "copy", "copy2", "copyfile",
    "chmod", "chown", "truncate", "symlink", "link", "hardlink_to", "write",
    "writelines", "dump",
}
# Calls that run a shell/child process: arg 0 is the command.
EXEC_CALLS = {"system", "popen", "run", "call", "check_call", "check_output", "Popen", "run_command"}
READ_MODES = set("rbt")


def _literal(node) -> str | None:
    """String value of a literal / f-string-with-no-placeholders node, else None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, (str, bytes)):
        v = node.value
        return v.decode() if isinstance(v, bytes) else v
    if isinstance(node, ast.JoinedStr) and all(
        isinstance(getattr(v, "value", None), str) for v in node.values
    ):
        return "".join(str(getattr(v, "value", "")) for v in node.values)
    return None


def _looks_like_path(s: str) -> bool:
    return "/" in s or s.endswith(".md") or s.startswith("~")


def _mentions_ro(code: str) -> bool:
    """Does the snippet reference the RO folder -- absolute, relative, or as a path segment?"""
    if RO_DIR in code:
        return True
    return bool(re.search(r"""['"/\\]RO['"/\\]""", code) or re.search(r"""['"]RO['"]""", code))


def _cmd_from_argv(node) -> str | None:
    """Join a literal list/tuple argv (subprocess style) into a command string."""
    if isinstance(node, (ast.List, ast.Tuple)):
        parts = [_literal(el) for el in node.elts]
        if parts and all(isinstance(p, str) for p in parts):
            return " ".join(parts)  # type: ignore[arg-type]
    return _literal(node)


def _mode_writes(node) -> bool:
    """open() mode -- absent means read; any of wax+ writes."""
    lit = _literal(node)
    if lit is None:
        return True  # unknown mode: assume it writes
    return any(ch in lit for ch in "wax+")


def _ast_ro_risk(code: str) -> str | None:
    """Return a reason string when the snippet would write into RO/, else None."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None  # handled by the text fallback
    mentions_ro = _mentions_ro(code)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
        args = list(node.args) + [kw.value for kw in node.keywords]

        # open(...) — only interesting when the mode writes
        if name == "open":
            mode = args[1] if len(args) > 1 else next(
                (kw.value for kw in node.keywords if kw.arg == "mode"), None
            )
            if mode is not None and not _mode_writes(mode):
                continue
            if mode is None and len(node.keywords) == 0 and len(args) < 2:
                continue  # plain read
            if mode is None:
                continue
            if args:
                lit = _literal(args[0])
                if lit is not None:
                    if inside_ro(lit, "") or lit.startswith(RO_DIR):
                        return f"open({lit!r}, write mode)"
                    continue
            if mentions_ro:
                return "open() with a non-literal path while RO/ is referenced"
            continue

        if name in ("eval", "exec", "compile"):
            if mentions_ro:
                return f"{name}() over dynamic code while RO/ is referenced"
            continue

        if name in EXEC_CALLS:
            cmd = _cmd_from_argv(args[0]) if args else None
            if cmd is None:
                if mentions_ro:
                    return f"{name}() with a non-literal command while RO/ is referenced"
                continue
            if not mentions_ro:
                continue
            tokens = cmd.split()
            write_verb = any(t in WRITE_VERBS or t in INTERPRETERS for t in tokens)
            touches_ro = RO_DIR in cmd or re.search(r"(^|[\s'\"=])RO/", cmd)
            if write_verb and touches_ro:
                return f"{name}() would run a writing command against RO/"
            continue

        if name not in MUTATING_CALLS:
            continue
        # A mutating call: does any literal argument land inside RO/?
        literals = [s for s in (_literal(a) for a in args) if isinstance(s, str)]
        receiver = func.value if isinstance(func, ast.Attribute) else None
        if receiver is not None:
            recv = _literal(receiver)
            if isinstance(recv, str):
                literals.append(recv)
        hit = next((s for s in literals if _looks_like_path(s) and (RO_DIR in s or inside_ro(s, ""))), None)
        if hit:
            return f"{name}() targets {hit!r} in RO/"
        if mentions_ro and not literals:
            return f"{name}() with a non-literal path while RO/ is referenced"
    return None


def block(reason: str) -> None:
    print(json.dumps({"decision": "block", "reason": MESSAGE_PREFIX + reason}))
    sys.exit(0)


def resolve(path: str, cwd: str) -> str:
    p = os.path.expanduser(str(path))
    if not os.path.isabs(p):
        p = os.path.join(cwd or os.getcwd(), p)
    # realpath on a non-existent leaf still normalises the parent; that is enough
    return os.path.realpath(p)


def inside_ro(path: str, cwd: str) -> bool:
    return resolve(path, cwd) == RO_DIR or resolve(path, cwd).startswith(RO_DIR + os.sep)


def check_path_tool(tool: str, args: dict) -> None:
    cwd = args.get("cwd") or ""
    candidates = []
    for key in ("path", "file_path", "file", "target", "target_file", "filename"):
        val = args.get(key)
        if isinstance(val, str) and val:
            candidates.append(val)
    if isinstance(args.get("paths"), list):
        candidates.extend([p for p in args["paths"] if isinstance(p, str)])
    for cand in candidates:
        if inside_ro(cand, cwd):
            block(
                f"{tool} refused: '{cand}' is inside {RO_DIR} (read-only for agents). "
                f"Read it, or write the change into {os.path.join(VAULT, 'RW')} instead."
            )


def shell_command_of(args: dict) -> str:
    for key in ("command", "cmd", "script", "input"):
        val = args.get(key)
        if isinstance(val, str) and val:
            return val
    return ""


def check_shell(args: dict) -> None:
    command = shell_command_of(args)
    if not command:
        return
    cwd = args.get("cwd") or os.getcwd()
    cwd_in_ro = inside_ro(cwd, cwd)
    if "RO" not in command and not command.strip().startswith("cd") and not cwd_in_ro:
        return

    try:
        tokens = shlex.split(command, comments=False)
    except ValueError:
        tokens = command.split()

    lowered = tokens
    ro_tokens = []
    cd_into_ro = False
    for idx, tok in enumerate(tokens):
        if tok in ("cd", "pushd") and idx + 1 < len(tokens):
            if inside_ro(tokens[idx + 1], cwd):
                cd_into_ro = True
            continue
        if tok.startswith("-") or not any(ch in tok for ch in "./"):
            continue
        if inside_ro(tok, cwd):
            ro_tokens.append(tok)
    redirect_into_ro = False
    for match in re.finditer(r">>?\s*([^\s|;&<>]+)", command):
        target = match.group(1).strip("'\"")
        if target in ("/dev/null", "&1", "&2") or target.startswith("&"):
            continue
        if inside_ro(target, cwd):
            redirect_into_ro = True
            break

    has_verb = any(tok in WRITE_VERBS or tok in INTERPRETERS for tok in lowered)
    if has_verb or redirect_into_ro:
        if ro_tokens or redirect_into_ro or cd_into_ro or cwd_in_ro:
            block(
                "terminal refused: this command would modify "
                f"{RO_DIR} (read-only for agents). Reads are fine; put the write in "
                f"{os.path.join(VAULT, 'RW')} or ask the user to change RO/ by hand."
            )
    # git plumbing that can rewrite the worktree
    if "git" in tokens and any(t in tokens for t in ("checkout", "restore", "clean", "rm", "mv", "apply")):
        if ro_tokens or inside_ro(cwd, cwd):
            block("terminal refused: git would rewrite tracked files under RO/.")


def check_code(args: dict) -> None:
    code = args.get("code") or ""
    if not isinstance(code, str) or not code:
        return
    reason = _ast_ro_risk(code)
    if reason is None and _mentions_ro(code):
        # Unparseable snippet or context we could not resolve: fall back to the
        # narrower text heuristic (write operations only, no blanket exec match).
        if CODE_WRITE_PATTERNS.search(code):
            reason = "snippet contains a write operation while RO/ is referenced"
    if reason:
        block(f"execute_code refused: {reason}. Do the write in RW/ instead.")


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        print("{}")
        return

    tool = payload.get("tool_name") or ""
    args = payload.get("tool_input")
    if not isinstance(args, dict):
        args = payload.get("args") if isinstance(payload.get("args"), dict) else {}
    if not args.get("cwd") and payload.get("cwd"):
        args.setdefault("cwd", payload["cwd"])

    if tool in WRITE_TOOLS:
        check_path_tool(tool, args)
    elif tool in SHELL_TOOLS:
        check_shell(args)
    elif tool in CODE_TOOLS:
        check_code(args)
    # read_file / search_files & everything else: never blocked

    print("{}")


if __name__ == "__main__":
    main()
