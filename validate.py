#!/usr/bin/env python3
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
CHECKS = ("stow", "lua", "claude", "herdr")


def run(command, *, cwd=ROOT, env=None):
    print(f"+ {' '.join(command)}", flush=True)
    try:
        return subprocess.run(command, cwd=cwd, env=env, check=False).returncode == 0
    except OSError as error:
        print(f"Could not run {command[0]}: {error}", file=sys.stderr)
        return False


def validate(check):
    if check == "stow":
        with tempfile.TemporaryDirectory(prefix="dotfiles-stow-") as target:
            return run(
                ["stow", "--simulate", "--dir", str(ROOT), "--target", target,
                 "openclaude", "claude-skills", "git"],
                cwd=target,
                env={**os.environ, "HOME": target},
            )
    if check == "lua":
        return run(["stylua", "--check", "."])
    if check == "claude":
        mods = sorted(ROOT.glob("claude-mods/*/.claude-plugin/plugin.json"))
        if not mods:
            print("No Claude mods found", file=sys.stderr)
            return False
        results = []
        for manifest in mods:
            mod = str(manifest.parents[1].relative_to(ROOT))
            results.append(run(["claude", "plugin", "validate", mod]))
            results.append(run(["claude", "plugin", "test", mod]))
        return all(results)
    return run(
        ["herdr", "config", "check"],
        env={**os.environ, "HERDR_CONFIG_PATH": str(ROOT / "herdr/.config/herdr/config.toml")},
    )


def main():
    parser = argparse.ArgumentParser(description="Run local dotfiles checks without applying configs.")
    parser.add_argument("checks", nargs="*", metavar="CHECK", help=f"{' | '.join(CHECKS)} (default: all)")
    args = parser.parse_args()
    for check in args.checks:
        if check not in CHECKS:
            parser.error(f"unknown check: {check}")
    failed = [check for check in dict.fromkeys(args.checks or CHECKS) if not validate(check)]
    if failed:
        print(f"Failed checks: {', '.join(failed)}", file=sys.stderr)
        return 1
    print("All requested checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
