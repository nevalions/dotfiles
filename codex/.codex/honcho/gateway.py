"""Stdio MCP publisher; the launching OS user is the trusted principal."""
import json
import os
import re
import stat
import shutil
import subprocess
from urllib.error import URLError
from urllib.request import HTTPRedirectHandler

SCOPE = ("workspace_id", "peer_id", "target_peer_id", "session_id", "task")
TAILNET_HOST = "100.64.0.16"
LIMIT = 1024 * 1024
ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}")
PROTOCOLS = {"2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25"}


class Denied(Exception):
    pass


def private_text(path):
    if not isinstance(path, str) or not os.path.isabs(path):
        raise ValueError("private file path must be absolute")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, encoding="utf-8") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("expected an owner-only regular file")
        data = stream.read(16385)
        if len(data) > 16384:
            raise ValueError("private file too large")
        return data


def require_tailnet_route():
    try:
        result = subprocess.run(
            [shutil.which("ip") or "/usr/bin/ip", "-j", "route", "get", TAILNET_HOST],
            capture_output=True, check=True, timeout=2,
        )
        routes = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        routes = None
    if (not isinstance(routes, list) or len(routes) != 1
            or not isinstance(routes[0], dict)
            or routes[0].get("dev") != "tailscale0"):
        raise Denied("Honcho tailnet HTTP requires an active route through tailscale0.")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def object_schema(properties):
    return {"type": "object", "properties": properties, "required": list(properties),
            "additionalProperties": False}


def string(maximum):
    return {"type": "string", "minLength": 1, "maxLength": maximum}


SCOPE_SCHEMA = object_schema({key: string(128) for key in SCOPE})
FIELDS = {"candidate": 256, "checks": 900, "verification": 600, "conclusion": 1000}
TOOLS = [
    {"name": "get_grant", "description": "Read the launcher's exact authorized workspace, peers, session and task.",
     "inputSchema": object_schema({}), "annotations": {"readOnlyHint": True}},
    {"name": "readback", "description": "List recent conclusions for the exact granted session and peers.",
     "inputSchema": object_schema({"scope": SCOPE_SCHEMA}), "annotations": {"readOnlyHint": True}},
    {"name": "publish_verified", "description": "Append one verified conclusion. Supply the exact granted scope, "
     "immutable revision or primary source, checks and results, and review or independent verification evidence.",
     "inputSchema": object_schema({"scope": SCOPE_SCHEMA, **{k: string(n) for k, n in FIELDS.items()}}),
     "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False}},
]


def content(value):
    return {"content": [{"type": "text", "text": value}]}


def call(name, args, scope, upstream):
    if name == "get_grant" and args == {}:
        return content(json.dumps(scope))
    fields = FIELDS if name == "publish_verified" else {} if name == "readback" else None
    if fields is None:
        raise Denied("Operation not allowed.")
    if not isinstance(args, dict) or args.get("scope") != scope:
        raise Denied("Outside the approved Honcho grant.")
    if set(args) != {"scope", *fields}:
        raise Denied("Unexpected or missing arguments.")
    bound = {key: scope[key] for key in SCOPE if key != "task"}
    if name == "readback":
        return upstream.call("list_conclusions", {**bound, "size": 10})
    for key, length in fields.items():
        value = args[key]
        if (not isinstance(value, str) or not value.strip() or len(value) > length
                or not value.isprintable()):
            raise Denied(f"Invalid {key}: supply nonempty, bounded, single-line evidence.")
    note = (f"{args['conclusion']} [Task: {scope['task']}; Candidate/source: {args['candidate']}; "
            f"Checks: {args['checks']}; Verification: {args['verification']}]")
    upstream.prepare_session(scope)
    upstream.call("create_conclusions", {**bound, "conclusions": [note]})
    return content("Honcho accepted the append. Use readback to confirm the conclusion.")


def dispatch(request, scope, upstream):
    method = request.get("method")
    params = request.get("params", {})
    if method == "initialize":
        version = params.get("protocolVersion")
        return {"protocolVersion": version if version in PROTOCOLS else "2025-03-26",
                "serverInfo": {"name": "Codex Honcho publisher", "version": "1"},
                "capabilities": {"tools": {}}}
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "tools/call":
        try:
            return call(params.get("name"), params.get("arguments", {}), scope, upstream)
        except Denied as exc:
            return {**content(str(exc)), "isError": True}
        except (URLError, OSError, ValueError, KeyError, TypeError):
            return {**content("Upstream REST failed; read back before retrying any append."), "isError": True}
    return None
