#!/usr/bin/env python3
import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tomllib


def main():
    parser = argparse.ArgumentParser(description="Read-only Codex inventory and observed tool counts.")
    parser.add_argument("--days", type=int, default=30)
    args = parser.parse_args()
    if args.days < 1:
        parser.error("--days must be positive")
    home = Path.home()
    codex = Path(os.environ.get("CODEX_HOME", home / ".codex"))
    config_path = codex / "config.toml"
    config = tomllib.loads(config_path.read_text()) if config_path.exists() else {}
    print("Codex inventory (credentials, prompts and tool arguments omitted)")
    names = Counter()
    for root in [home / ".agents/skills", codex / "skills"]:
        print("Skills:", root)
        if not root.exists():
            continue
        for folder in sorted(root.iterdir()):
            if folder.is_symlink() and not folder.exists():
                print(" ", folder.name, "dangling symlink")
            skill = folder / "SKILL.md"
            if skill.exists():
                names[folder.name] += 1
                policy = folder / "agents/openai.yaml"
                explicit = policy.exists() and "allow_implicit_invocation: false" in policy.read_text()
                print(" ", folder.name, skill.stat().st_size, "bytes", "explicit-only" if explicit else "discoverable")
    print("Duplicate folder names:", ", ".join(name for name, count in names.items() if count > 1) or "none")
    print("Custom agents:", ", ".join(p.stem for p in sorted((codex / "agents").glob("*.toml"))) or "none")
    print("MCP servers:")
    for name, spec in sorted(config.get("mcp_servers", {}).items()):
        print(" ", name, "enabled" if spec.get("enabled", True) else "disabled")
    print("Configured plugins:", ", ".join(config.get("plugins", {})) or "none")
    print("Plugin manifests:", len(list((codex / "plugins/cache").glob("**/.codex-plugin/plugin.json"))))
    print("Hook file:", "present" if (codex / "hooks.json").exists() else "absent")
    cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)
    tools = Counter()
    malformed = inaccessible = sessions = 0
    for path in (codex / "sessions").rglob("*.jsonl"):
        sessions += 1
        try:
            with path.open() as handle:
                for line in handle:
                    try:
                        record = json.loads(line)
                        stamp = datetime.fromisoformat(record.get("timestamp", "").replace("Z", "+00:00"))
                        if stamp.tzinfo is None:
                            stamp = stamp.replace(tzinfo=timezone.utc)
                        payload = record.get("payload", {})
                        if stamp >= cutoff and record.get("type") == "response_item" and payload.get("type") in ("function_call", "custom_tool_call"):
                            tools[payload.get("name", "unknown")] += 1
                    except (ValueError, TypeError, AttributeError):
                        malformed += 1
        except OSError:
            inaccessible += 1
    print(f"Observed tool calls, last {args.days} days ({sessions} local sessions):")
    for name, count in tools.most_common():
        print(" ", name, count)
    print(f"Skipped records: {malformed}; inaccessible transcripts: {inaccessible}")
    print("Coverage: local JSONL sessions only. Skill reads, plugin loading and deferred tools may not be separately observable; absent calls do not prove non-use.")


if __name__ == "__main__":
    main()
