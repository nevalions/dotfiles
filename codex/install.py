#!/usr/bin/env python3
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import tomllib


def encode(value):
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, list):
        return "[" + ", ".join(encode(item) for item in value) + "]"
    if isinstance(value, dict):
        return "{ " + ", ".join(json.dumps(key) + " = " + encode(item) for key, item in value.items()) + " }"
    raise ValueError("Unsupported TOML value type: " + type(value).__name__)


def serialize(data, prefix=()):
    lines = []
    if prefix:
        lines.append("[" + ".".join(json.dumps(part) for part in prefix) + "]")
    for key, value in data.items():
        if not isinstance(value, dict):
            lines.append(json.dumps(key) + " = " + encode(value))
    for key, value in data.items():
        if isinstance(value, dict):
            lines.append(serialize(value, (*prefix, key)))
    return "\n".join(lines) + "\n"


def merge(defaults, current):
    result = defaults.copy()
    for key, value in current.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge(result[key], value)
        else:
            result[key] = value
    return result


def prune_empty_directories(path):
    if path.is_symlink() or not path.is_dir():
        return
    for child in path.iterdir():
        prune_empty_directories(child)
    try:
        path.rmdir()
    except OSError:
        pass


def main():
    parser = argparse.ArgumentParser(description="Merge Codex defaults and stow the Codex packages.")
    parser.add_argument("--target", type=Path, default=Path.home())
    parser.add_argument("--check", action="store_true", help="Check config and Stow conflicts without applying.")
    parser.add_argument("--skip-plugins", action="store_true", help="Install config and skills without bundled plugins.")
    args = parser.parse_args()
    package = Path(__file__).resolve().parent
    repo = package.parent
    target = args.target.expanduser().resolve()
    if os.environ.get("CODEX_HOME") and Path(os.environ["CODEX_HOME"]).resolve() != target / ".codex":
        parser.error("This Stow package uses ~/.codex; unset CODEX_HOME or select its parent with --target.")
    live = target / ".codex/config.toml"
    source = package / ".codex/config.toml"
    defaults = tomllib.loads((package / "config.base.toml").read_text())
    current = tomllib.loads(live.read_text()) if live.exists() else {}
    output = serialize(merge(defaults, current))
    tomllib.loads(output)
    stow_base = ["stow", "--dir", str(repo), "--target", str(target)]
    stow = [*stow_base, "--no-folding", "codex"]
    skills_stow = [*stow_base, "codex-skills"]
    if live.is_symlink() and live.resolve() != source:
        parser.error("Existing config.toml is managed by a different symlink; resolve it before installing.")
    if source.exists() and (not live.is_symlink() or live.resolve() != source):
        if source.read_text() != output:
            parser.error("Generated config belongs to another target; use a separate dotfiles checkout.")
    if args.check:
        result = subprocess.run([*stow, "--simulate"], capture_output=True, text=True)
        skills_result = subprocess.run([*skills_stow, "--simulate"], capture_output=True, text=True)
        print("TOML is valid. Existing settings will be preserved.")
        if result.returncode and live.is_file() and not live.is_symlink():
            print("Stow may report the expected config.toml conflict; inspect other conflicts below.")
        print(result.stdout + result.stderr, end="")
        print(skills_result.stdout + skills_result.stderr, end="")
        raise SystemExit(result.returncode or skills_result.returncode)
    backup = None
    if live.is_file() and not live.is_symlink():
        directory = target / ".codex/backups"
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup = directory / ("config.toml." + stamp)
        shutil.copy2(live, backup)
        backup.chmod(0o600)
    source.parent.mkdir(parents=True, exist_ok=True)
    temporary = source.with_suffix(".toml.tmp")
    with open(temporary, "w", opener=lambda path, flags: os.open(path, flags, 0o600)) as handle:
        handle.write(output)
    temporary.replace(source)
    if backup:
        live.unlink()
    try:
        subprocess.run([*stow, "--simulate"], check=True)
        subprocess.run([*skills_stow, "--simulate"], check=True)
        subprocess.run(stow, check=True)
        subprocess.run([*stow_base, "--delete", "codex-skills"], check=True)
        prune_empty_directories(target / ".agents/skills")
        subprocess.run(skills_stow, check=True)
    except subprocess.CalledProcessError:
        if backup and not live.exists():
            shutil.copy2(backup, live)
        raise
    print("Installed Codex config, agents and skills. Restart Codex to load MCP connections.")
    if backup:
        print("Previous config: " + str(backup))
    if not args.skip_plugins:
        codex = shutil.which("codex")
        if not codex:
            raise SystemExit("Config installed; install Codex and re-run to enable bundled plugins.")
        env = os.environ.copy()
        env["CODEX_HOME"] = str(target / ".codex")
        subprocess.run([codex, "plugin", "marketplace", "add", str(package / "plugin-marketplace")], env=env, check=True)
        for name in ("superpowers", "frontend-design"):
            subprocess.run([codex, "plugin", "add", name + "@dotfiles"], env=env, check=True)


if __name__ == "__main__":
    main()
