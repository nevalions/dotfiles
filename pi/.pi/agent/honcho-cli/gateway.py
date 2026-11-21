"""Stdio MCP publisher; the launching OS user is the trusted principal."""
import json
import os
import re
import stat
import sys
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

SCOPE = ("workspace_id", "peer_id", "target_peer_id", "session_id", "task")
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


def load_grant(path):
    data = json.loads(private_text(path))
    if set(data) != {"url", "token_file", "scope"}:
        raise ValueError("invalid grant")
    scope = data["scope"]
    if set(scope) != set(SCOPE) or not all(isinstance(v, str) and ID.fullmatch(v) for v in scope.values()):
        raise ValueError("invalid scope")
    url = urlsplit(data["url"])
    if (not url.hostname or url.username or url.password or url.fragment or url.query
            or not (url.scheme == "https" or
                    (url.scheme == "http" and url.hostname in {"127.0.0.1", "::1"}))):
        raise ValueError("Honcho needs HTTPS or an explicit numeric loopback endpoint")
    token = private_text(data["token_file"]).strip()
    if not re.fullmatch(r"[!-~]{1,4096}", token):
        raise ValueError("invalid bearer token")
    return scope, Honcho(data["url"], token, scope["workspace_id"])


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Honcho:
    def __init__(self, url, token, workspace):
        self.url = url
        self.headers = {
            "Authorization": f"Bearer {token}",
            "X-Honcho-Workspace-ID": workspace,
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        self.opener = build_opener(ProxyHandler({}), NoRedirect())
        self.sequence = 0
        self.ready = False

    def rpc(self, method, params, notification=False):
        message = {"jsonrpc": "2.0", "method": method, "params": params}
        if not notification:
            self.sequence += 1
            message["id"] = self.sequence
        req = Request(self.url, json.dumps(message).encode(), self.headers)
        with self.opener.open(req, timeout=20) as response:
            session = response.headers.get("Mcp-Session-Id")
            if session:
                self.headers["Mcp-Session-Id"] = session
            if notification:
                return None
            if response.headers.get_content_type() == "text/event-stream":
                for _ in range(128):
                    line = response.readline(LIMIT + 1)
                    if not line or len(line) > LIMIT:
                        break
                    if line.startswith(b"data:"):
                        reply = json.loads(line[5:])
                        if reply.get("id") == self.sequence:
                            return reply["result"]
                raise ValueError("missing MCP reply")
            reply = json.loads(response.read(LIMIT + 1))
            if reply.get("id") != self.sequence:
                raise ValueError("unexpected MCP reply")
            return reply["result"]

    def call(self, name, args):
        if not self.ready:
            result = self.rpc("initialize", {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "pi-honcho-publisher", "version": "1"},
            })
            version = result["protocolVersion"]
            if version not in PROTOCOLS:
                raise ValueError("unsupported upstream MCP protocol")
            self.headers["MCP-Protocol-Version"] = version
            self.rpc("notifications/initialized", {}, notification=True)
            self.ready = True
        result = self.rpc("tools/call", {"name": name, "arguments": args})
        if result.get("isError"):
            raise Denied("Honcho rejected the request; check the workspace grant and provisioned scope.")
        return result


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
    upstream.call("create_conclusions", {**bound, "conclusions": [note]})
    return content("Honcho accepted the append. Use readback to confirm the conclusion.")


def dispatch(request, scope, upstream):
    method = request.get("method")
    params = request.get("params", {})
    if method == "initialize":
        version = params.get("protocolVersion")
        return {"protocolVersion": version if version in PROTOCOLS else "2025-03-26",
                "serverInfo": {"name": "Pi Honcho publisher", "version": "1"},
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
            return {**content("Upstream MCP failed; read back before retrying any append."), "isError": True}
    return None


def main():
    try:
        scope, upstream = load_grant(sys.argv[1])
    except (IndexError, OSError, ValueError, TypeError):
        sys.exit("Honcho publisher: invalid or unreadable private grant.")
    while line := sys.stdin.buffer.readline(LIMIT + 1):
        if len(line) > LIMIT:
            sys.exit("Honcho publisher: request too large.")
        try:
            request = json.loads(line)
            if not isinstance(request, dict) or "id" not in request:
                continue
            response = {"jsonrpc": "2.0", "id": request["id"]}
            result = dispatch(request, scope, upstream)
            if result is None:
                response["error"] = {"code": -32601, "message": "Method not found"}
            else:
                response["result"] = result
        except (ValueError, TypeError, AttributeError):
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid request"}}
        print(json.dumps(response), flush=True)


if __name__ == "__main__":
    main()
