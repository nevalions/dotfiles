#!/usr/bin/env python3
"""Install the tracked Hermes configuration into $HERMES_HOME.

Two steps, both idempotent:

1. Apply ``config.base.yaml`` through ``hermes config set``. Keys already
   present in the live config.yaml are kept (local choices win) unless
   ``--force`` is passed. config.yaml itself is never edited or symlinked:
   Hermes rewrites it at runtime, so the tracked file is the *input*, not the
   installed artifact.
2. Link ``~/.hermes/SOUL.md`` to the tracked file (a real file is backed up
   first, which is why stow does not own it) and stow ``hermes`` so custom
   skills point back into this repo.

Usage:
    python3 hermes/install.py --check     # dry run, writes nothing
    python3 hermes/install.py
    python3 hermes/install.py --force     # also overwrite live settings
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

PACKAGE = "hermes"
REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_DIR = REPO_ROOT / PACKAGE
SETTINGS_FILE = PACKAGE_DIR / "config.base.yaml"
SOUL_FILE = PACKAGE_DIR / ".hermes" / "SOUL.md"
PLUGINS_DIR = PACKAGE_DIR / ".hermes" / "plugins"

KEY_RE = re.compile(r"^([^\s:#][^:]*?):(?:\s+(.*))?$")


class InstallError(RuntimeError):
    pass


def hermes_home(override: str | None) -> Path:
    raw = override or os.environ.get("HERMES_HOME") or "~/.hermes"
    path = Path(raw).expanduser()
    if path.name != ".hermes" or path.is_symlink():
        raise InstallError(f"HERMES_HOME must be a real directory named .hermes: {path}")
    return path.resolve()


def hermes_bin() -> str:
    exe = shutil.which("hermes")
    if not exe:
        raise InstallError(
            "hermes is not on PATH. Install it first "
            "(curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash)."
        )
    return exe


def run(cmd: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, cwd=cwd, env=env, text=True, capture_output=True)
    if proc.returncode != 0:
        detail = (proc.stdout + proc.stderr).strip()
        raise InstallError(f"{' '.join(cmd)} failed (exit {proc.returncode})" + (f":\n{detail}" if detail else ""))
    return proc


def strip_comment(value: str) -> str:
    """Drop a trailing ``# comment`` that is outside quotes."""
    quote = None
    for i, ch in enumerate(value):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "#" and (i == 0 or value[i - 1].isspace()):
            return value[:i].rstrip()
    return value


def read_settings(path: Path) -> list[tuple[str, str]]:
    if not path.is_file():
        raise InstallError(f"missing settings file: {path}")
    settings: list[tuple[str, str]] = []
    seen: set[str] = set()
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition(":")
        key, value = key.strip(), strip_comment(value).strip()
        if not sep or not key or not value:
            raise InstallError(f"{path}:{lineno}: expected `dotted.key: value`")
        if key in seen:
            raise InstallError(f"{path}:{lineno}: duplicate key {key}")
        seen.add(key)
        settings.append((key, value))
    if not settings:
        raise InstallError(f"{path}: no settings found")
    return settings


def read_config_keys(path: Path) -> dict[str, str]:
    """Return ``dotted.key -> scalar`` for keys already present in config.yaml.

    Only block-style mappings are understood, which is what
    ``hermes config set`` writes. A container key (mapping or list) is recorded
    with an empty value: it counts as set, and the caller resolves the real
    value through ``hermes config get``. A missed key just means the tracked
    default is applied.
    """
    found: dict[str, str] = {}
    if not path.is_file():
        return found
    stack: list[tuple[int, str]] = []
    for raw in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        line = raw.strip()
        if line.startswith("-"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        match = KEY_RE.match(line)
        if not match:
            continue
        key = match.group(1).strip()
        value = strip_comment(match.group(2) or "").strip()
        while stack and stack[-1][0] >= indent:
            stack.pop()
        dotted = ".".join([k for _, k in stack] + [key])
        found[dotted] = value.strip("\"'")
        if not value:
            stack.append((indent, key))
    return found


def cmd_env(home: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["HERMES_HOME"] = str(home)
    return env


def apply_settings(home: Path, settings: list[tuple[str, str]], *, force: bool, check: bool) -> int:
    exe = hermes_bin()
    config = home / "config.yaml"
    present = read_config_keys(config)
    changed = 0
    for key, value in settings:
        if key in present and not force:
            shown = present[key]
            if not shown and not check:
                proc = subprocess.run([exe, "config", "get", key], env=cmd_env(home), text=True, capture_output=True)
                shown = " ".join(line.strip().lstrip("- ").strip() for line in proc.stdout.splitlines() if line.strip())
            print(f"  keep  {key} = {shown or '(empty)'}  (local value wins; --force to replace)")
            continue
        action = "would set" if check else "set"
        print(f"  {action} {key} = {value}")
        if not check:
            run([exe, "config", "set", key, value], env=cmd_env(home))
        changed += 1
    return changed


def link_soul(home: Path, *, force: bool, check: bool) -> None:
    soul = home / "SOUL.md"
    if soul.is_symlink() and soul.resolve() == SOUL_FILE:
        print(f"  link  {soul} already points at {SOUL_FILE}")
        return
    if soul.exists() and not soul.is_symlink():
        tracked = SOUL_FILE.read_bytes()
        if soul.read_bytes() != tracked and not force:
            print(f"  warn  {soul} differs from the tracked copy; it will be replaced")
        backups = home / "backups"
        dest = backups / f"SOUL.md.{time.strftime('%Y%m%d-%H%M%S')}"
        while dest.exists():
            dest = dest.with_name(f"{dest.name}x")
        print(f"  backup {soul} -> {dest}")
        if not check:
            backups.mkdir(parents=True, exist_ok=True)
            shutil.copy2(soul, dest)
            if dest.read_bytes() != soul.read_bytes():
                raise InstallError(f"backup verification failed: {dest}")
            soul.unlink()
    elif soul.is_symlink():
        print(f"  unlink {soul} (points elsewhere)")
        if not check:
            soul.unlink()
    print(f"  link  {soul} -> {SOUL_FILE}")
    if not check:
        home.mkdir(parents=True, exist_ok=True)
        soul.symlink_to(SOUL_FILE)


def stow(home: Path, *, check: bool) -> None:
    exe = shutil.which("stow")
    if not exe:
        raise InstallError("GNU Stow is not installed (pacman -S stow).")
    if home.name != ".hermes":
        # The package maps hermes/.hermes -> <target>/.hermes, so a home with
        # another name would be linked beside the real one, not into it.
        raise InstallError(
            f"HERMES_HOME is {home}, but the stow package targets a directory "
            "named .hermes. Use the default ~/.hermes layout or add a separate "
            "package for this layout."
        )
    target = home.parent
    # Default (folding) stow is deliberate: each custom skill directory becomes
    # one link, so files a skill adds later stay tracked. Make sure the parents
    # exist first, or stow would fold the whole .hermes/skills tree instead.
    skills_dir = home / "skills"
    if not skills_dir.is_dir():
        print(f"  mkdir {skills_dir}")
        if check:
            print("  stow  plan deferred until the skills directory exists")
            return
        skills_dir.mkdir(parents=True, exist_ok=True)
    plan = run([exe, "-n", "-v", "-t", str(target), PACKAGE], cwd=REPO_ROOT)
    output = plan.stdout + plan.stderr  # stow prints LINK/MKDIR progress on stderr
    lines = [line for line in output.splitlines() if line.startswith(("LINK:", "UNLINK:", "MKDIR:"))]
    for line in lines:
        # Folding .hermes or .hermes/skills would turn the repo into live
        # runtime state; only per-entry links are acceptable here.
        if re.match(r"^LINK: \.hermes(/skills)? =>", line):
            raise InstallError(
                "stow would fold the whole "
                f"{home} tree into the repo ({line}).\n"
                "Create the target directories first (Hermes does this on first run), "
                "then re-run."
            )
    if not lines:
        print("  stow  already linked, nothing to do")
        return
    for line in lines:
        print(f"  {line}")
    if check:
        return
    run([exe, "-t", str(target), PACKAGE], cwd=REPO_ROOT)


def enable_plugins(home: Path, *, check: bool) -> None:
    """Enable every plugin tracked under hermes/.hermes/plugins/ (opt-in list)."""
    if not PLUGINS_DIR.is_dir():
        return
    manifests = sorted(PLUGINS_DIR.glob("*/plugin.yaml"))
    if not manifests:
        return
    if check:
        for manifest in manifests:
            print(f"  would enable plugin {manifest.parent.name} if not already enabled")
        return
    exe = hermes_bin()
    proc = subprocess.run(
        [exe, "config", "get", "plugins.enabled"], env=cmd_env(home), text=True, capture_output=True
    )
    enabled = {
        line.strip().lstrip("- ").strip()
        for line in proc.stdout.splitlines()
        if line.strip()
    } if proc.returncode == 0 else set()
    for manifest in manifests:
        name = manifest.parent.name
        if name in enabled:
            print(f"  plugin {name}: already enabled")
            continue
        if check:
            print(f"  would enable plugin {name}")
            continue
        result = run([exe, "plugins", "enable", name], env=cmd_env(home))
        message = (result.stdout + result.stderr).strip().splitlines()
        print(f"  plugin {name}: {message[0] if message else 'enabled'}")


def canon(text: str) -> str:
    """Normalise a value for comparison: `config get` prints lists as "- item"."""
    stripped = text.strip()
    if stripped.startswith("["):
        try:
            return ",".join(str(item) for item in json.loads(stripped))
        except json.JSONDecodeError:
            pass
    parts = []
    for line in stripped.splitlines():
        line = line.strip()
        if line.startswith("- "):
            line = line[2:].strip()
        if line:
            parts.append(line.strip("\"'"))
    return ",".join(parts)


def verify(home: Path, settings: list[tuple[str, str]]) -> list[str]:
    problems: list[str] = []
    soul = home / "SOUL.md"
    if not soul.is_symlink() or soul.resolve() != SOUL_FILE:
        problems.append(f"{soul} is not linked to {SOUL_FILE}")
    exe = hermes_bin()
    for key, value in settings:
        proc = subprocess.run([exe, "config", "get", key], env=cmd_env(home), text=True, capture_output=True)
        got = proc.stdout.strip()
        if proc.returncode != 0 or not got:
            problems.append(f"{key} does not resolve (expected {value})")
        elif canon(got) != canon(value):
            print(f"  note  {key} resolves to {got!r} (tracked default {value!r})")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install the Hermes dotfiles package.")
    parser.add_argument("--check", action="store_true", help="show what would change and write nothing")
    parser.add_argument("--force", action="store_true", help="overwrite settings already present in the live config")
    parser.add_argument("--skip-settings", action="store_true", help="only stow files")
    parser.add_argument("--skip-stow", action="store_true", help="only apply settings")
    parser.add_argument("--skip-plugins", action="store_true", help="do not enable tracked plugins")
    parser.add_argument("--home", help="HERMES_HOME to install into (default: $HERMES_HOME or ~/.hermes)")
    args = parser.parse_args(argv)

    home = hermes_home(args.home)
    if home.name != ".hermes":
        raise InstallError(f"HERMES_HOME must be a directory named .hermes: {home}")
    if home.exists() and not home.is_dir():
        raise InstallError(f"HERMES_HOME is not a directory: {home}")
    config = home / "config.yaml"
    if config.is_symlink() or (config.exists() and not config.is_file()):
        raise InstallError(f"config.yaml must be a regular local file: {config}")
    settings = read_settings(SETTINGS_FILE)
    if not args.skip_stow:
        exe = shutil.which("stow")
        if not exe:
            raise InstallError("GNU Stow is not installed.")
        if home.parent.exists():
            run([exe, "--simulate", "--no-folding", "-t", str(home.parent), PACKAGE], cwd=REPO_ROOT)
    prefix = "check:" if args.check else "install:"
    print(f"{prefix} HERMES_HOME={home}")

    if not args.skip_settings:
        print("settings")
        apply_settings(home, settings, force=args.force, check=args.check)
    if not args.skip_stow:
        print("files")
        link_soul(home, force=args.force, check=args.check)
        stow(home, check=args.check)
    if not args.skip_plugins:
        print("plugins")
        enable_plugins(home, check=args.check)

    if args.check:
        print("dry run: nothing written")
        return 0

    problems = verify(home, settings)
    for problem in problems:
        print(f"  error {problem}")
    if problems:
        return 1
    print("done. Restart Hermes (or /reset) to pick up new settings and skills.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except InstallError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
