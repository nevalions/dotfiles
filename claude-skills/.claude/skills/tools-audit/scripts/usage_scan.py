#!/usr/bin/env python3
"""Inventory the Claude Code setup and count how much of it is actually used.

Reads only: ~/.claude (settings, skills, agents, hooks, plugins), ~/.claude.json
(MCP servers, project entries) and every session transcript under
~/.claude/projects. Prints a compact report; changes nothing.

Usage: usage_scan.py [--days N]   (N = window for the "recent" column, default 30)
"""
import collections
import datetime as dt
import glob
import json
import os
import re
import sys

HOME = os.path.expanduser("~")
CLAUDE = os.path.join(HOME, ".claude")
DAYS = 30
if "--days" in sys.argv:
    DAYS = int(sys.argv[sys.argv.index("--days") + 1])


def load_json(path, default=None):
    try:
        with open(path) as fh:
            return json.load(fh)
    except Exception:
        return default if default is not None else {}


def frontmatter(path):
    try:
        text = open(path, errors="ignore").read()
    except Exception:
        return {}
    m = re.match(r"---\n(.*?)\n---", text, re.S)
    if not m:
        return {}
    out = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip().strip('"')
    return out


# ---------------------------------------------------------------- usage scan
tools = collections.Counter()
recent = collections.Counter()
skills = collections.Counter()
agents = collections.Counter()
cutoff = (dt.datetime.now() - dt.timedelta(days=DAYS)).timestamp()
transcripts = glob.glob(os.path.join(CLAUDE, "projects", "*", "*.jsonl"))
for path in transcripts:
    is_recent = os.path.getmtime(path) > cutoff
    try:
        with open(path, errors="ignore") as fh:
            for line in fh:
                if '"tool_use"' not in line:
                    continue
                try:
                    msg = json.loads(line).get("message", {})
                except Exception:
                    continue
                content = msg.get("content") if isinstance(msg, dict) else None
                for c in content or []:
                    if not (isinstance(c, dict) and c.get("type") == "tool_use"):
                        continue
                    name = c.get("name", "")
                    inp = c.get("input") or {}
                    tools[name] += 1
                    if is_recent:
                        recent[name] += 1
                    if name == "Skill":
                        skills[inp.get("skill", "?")] += 1
                    elif name in ("Agent", "Task"):
                        agents[inp.get("subagent_type", "?")] += 1
    except Exception:
        pass

mcp_by_server = collections.Counter()
mcp_recent_by_server = collections.Counter()
for name, n in tools.items():
    if name.startswith("mcp__"):
        server = name.split("__")[1]
        mcp_by_server[server] += n
        mcp_recent_by_server[server] += recent[name]

print(f"# Claude Code usage scan  ({len(transcripts)} transcripts, recent = last {DAYS} days)\n")

# ---------------------------------------------------------------- MCP servers
cfg = load_json(os.path.join(HOME, ".claude.json"))
settings = load_json(os.path.join(CLAUDE, "settings.json"))
print("## MCP servers (user scope)          calls  recent")
for name, spec in sorted(cfg.get("mcpServers", {}).items()):
    key = name.replace(" ", "_").replace("-", "_")
    hits = [s for s in mcp_by_server if s.replace("-", "_") == key or s == name]
    n = sum(mcp_by_server[s] for s in hits)
    r = sum(mcp_recent_by_server[s] for s in hits)
    flag = "  <- never used" if n == 0 else ""
    print(f"  {name:32s} {n:6d} {r:6d}{flag}")
proj_mcp = {p: list(v.get("mcpServers", {})) for p, v in cfg.get("projects", {}).items() if v.get("mcpServers")}
if proj_mcp:
    print("  project-scoped:")
    for p, servers in sorted(proj_mcp.items()):
        gone = "" if os.path.isdir(p) else "  <- directory missing"
        print(f"    {p.replace(HOME, '~')}: {', '.join(servers)}{gone}")
print("  servers seen in transcripts:", ", ".join(f"{s}={n}" for s, n in mcp_by_server.most_common()))
stale_projects = [p for p in cfg.get("projects", {}) if not os.path.isdir(p)]
if stale_projects:
    print(f"  stale project entries ({len(stale_projects)}): " + ", ".join(p.replace(HOME, "~") for p in stale_projects))

# ---------------------------------------------------------------- plugins
print("\n## Plugins (enabledPlugins)          skills cmds agents  skill-calls  mcp-calls")
cache = os.path.join(CLAUDE, "plugins", "cache")
installed = load_json(os.path.join(CLAUDE, "plugins", "installed_plugins.json"))
for key, enabled in sorted(settings.get("enabledPlugins", {}).items()):
    pname = key.split("@")[0]
    entries = (installed.get("plugins") or installed).get(key) or []
    path = entries[0].get("installPath") if entries and isinstance(entries[0], dict) else None
    sk = cm = ag = 0
    if path and os.path.isdir(path):
        sk = len(glob.glob(os.path.join(path, "skills", "*", "SKILL.md")))
        cm = len(glob.glob(os.path.join(path, "commands", "*.md")))
        ag = len(glob.glob(os.path.join(path, "agents", "*.md")))
    scalls = sum(n for s, n in skills.items() if s.startswith(pname + ":"))
    mcalls = sum(n for s, n in mcp_by_server.items() if pname.replace("-", "_") in s.replace("-", "_"))
    state = "on " if enabled else "off"
    flag = "  <- enabled, never used" if enabled and scalls == 0 and mcalls == 0 and (sk or cm or ag) else ""
    print(f"  {state} {pname:26s} {sk:5d} {cm:5d} {ag:6d} {scalls:12d} {mcalls:10d}{flag}")

# ---------------------------------------------------------------- user skills / agents
print("\n## User skills (~/.claude/skills)     lines  calls  visibility")
for d in sorted(glob.glob(os.path.join(CLAUDE, "skills", "*"))):
    name = os.path.basename(d)
    sk = os.path.join(d, "SKILL.md")
    if not os.path.exists(sk):
        print(f"  {name:32s}  <- no SKILL.md" + ("  (dangling symlink)" if os.path.islink(d) and not os.path.exists(d) else ""))
        continue
    fm = frontmatter(sk)
    lines = sum(1 for _ in open(sk, errors="ignore"))
    vis = "hidden (user-invoked only)" if fm.get("disable-model-invocation") == "true" else "model-visible"
    n = skills.get(name, 0)
    flag = "  <- >500 lines, split into references/" if lines > 500 else ""
    print(f"  {name:32s} {lines:5d} {n:6d}  {vis}{flag}")

print("\n## User agents (~/.claude/agents)     model    dispatches")
for f in sorted(glob.glob(os.path.join(CLAUDE, "agents", "*.md"))):
    name = os.path.basename(f)[:-3]
    fm = frontmatter(f)
    n = agents.get(name, 0)
    flag = "  <- never dispatched" if n == 0 else ""
    print(f"  {name:32s} {fm.get('model', '-'):8s} {n:6d}{flag}")

# ---------------------------------------------------------------- hooks
print("\n## Hooks (settings.json)")
for event, matchers in settings.get("hooks", {}).items():
    for m in matchers:
        for h in m.get("hooks", []):
            cmd = h.get("command", "")
            paths = re.findall(r"(/[^\s\"']+)", cmd)
            missing = [p for p in paths if p.startswith("/") and "/" in p[1:] and not os.path.exists(p) and not p.startswith("/dev")]
            flag = f"  <- missing: {', '.join(missing)}" if missing else ""
            print(f"  {event:18s} {str(m.get('matcher', '*')):14s} {cmd[:70]}{flag}")
orphan_hooks = [f for f in glob.glob(os.path.join(CLAUDE, "hooks", "*")) if not any(os.path.basename(f) in h.get("command", "") for ms in settings.get("hooks", {}).values() for m in ms for h in m.get("hooks", []))]
if orphan_hooks:
    print("  files in ~/.claude/hooks not referenced by settings.json: " + ", ".join(os.path.basename(f) for f in orphan_hooks))

# ---------------------------------------------------------------- top usage
print("\n## Top skills:", ", ".join(f"{k}={v}" for k, v in skills.most_common(12)))
print("## Top agents:", ", ".join(f"{k}={v}" for k, v in agents.most_common(8)))
print("## Worktree tool loads:", sum(n for k, n in tools.items() if "Worktree" in k))
print("## Top MCP tools (all time / recent):")
for name, n in [(k, v) for k, v in tools.most_common() if k.startswith("mcp__")][:15]:
    print(f"  {n:6d} {recent[name]:6d}  {name}")
