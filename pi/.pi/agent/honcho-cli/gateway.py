"""Stdio MCP publisher; the launching OS user is the trusted principal."""
from http.client import HTTPException
import json
import os
import re
import stat
import subprocess
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

SCOPE = ("workspace_id", "peer_id", "target_peer_id", "session_id", "task")
TAILNET_HOST = "100.64.0.16"
TAILNET_URL = f"http://{TAILNET_HOST}:18080/mcp"
LIMIT = 1024 * 1024
CLOSE_TIMEOUT = 3
ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}")
SESSION_ID_RE = re.compile(r"[!-~]{1,4096}")
PROTOCOLS = {"2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25"}


class Denied(Exception):
    pass


class UpstreamHTTPStatus(URLError):
    """Sanitized upstream HTTP 429/503 failure with fixed operator-safe reason."""

    def __init__(self, status, reason):
        super().__init__(reason)
        self.status = status
        self.reason = reason

    def __str__(self):
        return self.reason


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
            ["/usr/bin/ip", "-j", "route", "get", TAILNET_HOST],
            capture_output=True, check=True, timeout=2,
        )
        routes = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        routes = None
    if (not isinstance(routes, list) or len(routes) != 1
            or not isinstance(routes[0], dict)
            or routes[0].get("dev") != "tailscale0"):
        raise Denied("Honcho tailnet HTTP requires an active route through tailscale0.")


def _reject_constant(value):
    raise ValueError(f"invalid JSON constant: {value}")


def parse_json_unique(text):
    def _pairs(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError("duplicate JSON key")
            obj[key] = value
        return obj

    return json.loads(text, object_pairs_hook=_pairs, parse_constant=_reject_constant)


def parse_grant_descriptor(raw_text):
    data = parse_json_unique(raw_text)
    required = {"url", "token_file", "scope"}
    if not isinstance(data, dict) or not required <= data.keys() <= required | {"allow_tailnet_http"}:
        raise ValueError("invalid grant")
    tailnet = data.get("allow_tailnet_http", False)
    if not isinstance(tailnet, bool) or (tailnet and data["url"] != TAILNET_URL):
        raise ValueError("invalid tailnet HTTP opt-in")
    scope = data["scope"]
    if (not isinstance(scope, dict) or set(scope) != set(SCOPE)
            or not all(isinstance(v, str) and ID.fullmatch(v) for v in scope.values())):
        raise ValueError("invalid scope")
    raw_url = data["url"]
    if not isinstance(raw_url, str):
        raise ValueError("invalid url")
    url = urlsplit(raw_url)
    if (not url.hostname or url.username or url.password or url.fragment or url.query
            or not (url.scheme == "https" or
                    (url.scheme == "http" and url.hostname in {"127.0.0.1", "::1"}) or tailnet)):
        raise ValueError("Honcho needs HTTPS, loopback HTTP, or explicit tailnet HTTP opt-in")
    token_file = data["token_file"]
    if not isinstance(token_file, str) or not os.path.isabs(token_file):
        raise ValueError("private file path must be absolute")
    return {
        "url": raw_url,
        "token_file": token_file,
        "scope": dict(scope),
        "allow_tailnet_http": tailnet,
    }


def load_grant_descriptor(path):
    raw = private_text(path)
    return raw, parse_grant_descriptor(raw)


def open_grant_client(descriptor):
    if descriptor["allow_tailnet_http"]:
        require_tailnet_route()
    token = private_text(descriptor["token_file"]).strip()
    if not re.fullmatch(r"[!-~]{1,4096}", token):
        raise ValueError("invalid bearer token")
    return Honcho(
        descriptor["url"],
        token,
        descriptor["scope"]["workspace_id"],
        tailnet=descriptor["allow_tailnet_http"],
    )


def load_grant(path):
    _, descriptor = load_grant_descriptor(path)
    return descriptor["scope"], open_grant_client(descriptor)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _decode_rpc_envelope(raw, expected_id, *, allow_unrelated=False):
    try:
        reply = json.loads(raw)
    except RecursionError:
        raise ValueError("invalid MCP reply") from None
    if not isinstance(reply, dict) or reply.get("jsonrpc") != "2.0":
        raise ValueError("invalid MCP reply")
    if "id" not in reply:
        if (allow_unrelated and isinstance(reply.get("method"), str) and reply["method"]
                and "result" not in reply and "error" not in reply):
            return False, None
        raise ValueError("unexpected MCP reply")
    msg_id = reply["id"]
    if isinstance(msg_id, bool) or not isinstance(msg_id, (int, str)):
        raise ValueError("invalid MCP reply")
    if type(msg_id) is not int or msg_id != expected_id:
        if allow_unrelated:
            return False, None
        raise ValueError("unexpected MCP reply")
    if "error" in reply or "result" not in reply:
        raise ValueError("invalid MCP reply")
    return True, reply["result"]


def _validate_tool_result(result):
    if not isinstance(result, dict):
        raise ValueError("invalid upstream MCP tool reply")
    blocks = result.get("content")
    if not isinstance(blocks, list):
        raise ValueError("invalid upstream MCP tool reply")
    for block in blocks:
        if not isinstance(block, dict):
            raise ValueError("invalid upstream MCP tool reply")
        block_type = block.get("type")
        if not isinstance(block_type, str):
            raise ValueError("invalid upstream MCP tool reply")
        if block_type == "text":
            if not isinstance(block.get("text"), str):
                raise ValueError("invalid upstream MCP tool reply")
        elif block_type in ("image", "audio"):
            if not isinstance(block.get("data"), str) or not isinstance(block.get("mimeType"), str):
                raise ValueError("invalid upstream MCP tool reply")
        elif block_type == "resource":
            if not isinstance(block.get("resource"), dict):
                raise ValueError("invalid upstream MCP tool reply")
        elif block_type == "resource_link":
            if not isinstance(block.get("uri"), str):
                raise ValueError("invalid upstream MCP tool reply")
        else:
            raise ValueError("invalid upstream MCP tool reply")
    if "structuredContent" in result and not isinstance(result["structuredContent"], dict):
        raise ValueError("invalid upstream MCP tool reply")
    if "isError" in result:
        is_error = result["isError"]
        if not isinstance(is_error, bool):
            raise ValueError("invalid upstream MCP tool reply")
        if is_error:
            raise Denied("Honcho rejected the request; check the workspace grant and provisioned scope.")
    return result


def _extract_session_id(headers):
    get_all = getattr(headers, "get_all", None)
    if callable(get_all):
        values = get_all("Mcp-Session-Id") or []
        if not values:
            return None
        if len(values) > 1:
            raise ValueError("duplicate MCP session ID")
        candidate = values[0]
    else:
        if "Mcp-Session-Id" not in headers:
            return None
        candidate = headers.get("Mcp-Session-Id")
    if isinstance(candidate, str) and SESSION_ID_RE.fullmatch(candidate):
        return candidate
    raise ValueError("invalid MCP session ID")


class Honcho:
    def __init__(self, url, token, workspace, *, tailnet=False):
        self.url = url
        self.tailnet = tailnet
        self.headers = {
            "Authorization": f"Bearer {token}",
            "X-Honcho-Workspace-ID": workspace,
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        self.opener = build_opener(ProxyHandler({}), NoRedirect())
        self.sequence = 0
        self.ready = False
        self.session_id = None
        self.protocol_version = None
        self._requested_protocol = None
        self._closed = False

    def rpc(self, method, params, notification=False):
        if self._closed:
            raise ValueError("Honcho client is closed")
        if method == "initialize" and (self.ready or self.session_id is not None):
            raise ValueError("Honcho client already initialized")
        if self.tailnet:
            require_tailnet_route()
        if method == "initialize" and isinstance(params, dict):
            requested = params.get("protocolVersion")
            if isinstance(requested, str) and requested in PROTOCOLS:
                self._requested_protocol = requested
        message = {"jsonrpc": "2.0", "method": method, "params": params}
        if not notification:
            self.sequence += 1
            message["id"] = self.sequence
        req = Request(self.url, json.dumps(message).encode(), dict(self.headers))
        try:
            with self.opener.open(req, timeout=20) as response:
                if method == "initialize" and self.session_id is None:
                    session = _extract_session_id(response.headers)
                    if session is not None:
                        self.session_id = session
                        self.headers["Mcp-Session-Id"] = session
                if notification:
                    return None
                if response.headers.get_content_type() == "text/event-stream":
                    for _ in range(128):
                        line = response.readline(LIMIT + 1)
                        if not line or len(line) > LIMIT:
                            break
                        if line.startswith(b"data:"):
                            matched, result = _decode_rpc_envelope(
                                line[5:], self.sequence, allow_unrelated=True
                            )
                            if matched:
                                return result
                    raise ValueError("missing MCP reply")
                _, result = _decode_rpc_envelope(response.read(LIMIT + 1), self.sequence)
                return result
        except HTTPError as exc:
            status = exc.code
            body = b""
            try:
                if status == 503:
                    body = exc.read(4096) or b""
            except (OSError, HTTPException, ValueError):
                body = b""
            finally:
                try:
                    exc.close()
                except Exception:
                    pass
            if status == 429:
                raise UpstreamHTTPStatus(429, "upstream MCP rate-limited (HTTP 429)") from None
            if status == 503:
                if b"too many active sessions" in body.lower():
                    raise UpstreamHTTPStatus(
                        503,
                        "upstream MCP service unavailable: too many active sessions (HTTP 503)",
                    ) from None
                raise UpstreamHTTPStatus(503, "upstream MCP service unavailable (HTTP 503)") from None
            raise

    def call(self, name, args):
        if self._closed:
            raise ValueError("Honcho client is closed")
        if not self.ready:
            if self.session_id is not None:
                raise ValueError("Honcho client handshake failed")
            try:
                result = self.rpc("initialize", {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "pi-honcho-publisher", "version": "1"},
                })
                if not isinstance(result, dict):
                    raise ValueError("invalid upstream MCP initialize reply")
                version = result.get("protocolVersion")
                if not isinstance(version, str) or version not in PROTOCOLS:
                    raise ValueError("unsupported upstream MCP protocol")
                self.protocol_version = version
                self.headers["MCP-Protocol-Version"] = version
                self.rpc("notifications/initialized", {}, notification=True)
                self.ready = True
            except BaseException:
                if self.session_id is not None:
                    self.close()
                else:
                    self.protocol_version = None
                    self.headers.pop("MCP-Protocol-Version", None)
                    self._requested_protocol = None
                raise
        result = self.rpc("tools/call", {"name": name, "arguments": args})
        return _validate_tool_result(result)

    def close(self):
        """Best-effort, idempotent cleanup of the server-issued MCP transport session."""
        if self._closed:
            return
        session_id = self.session_id
        protocol = self.protocol_version or self._requested_protocol
        auth = self.headers.get("Authorization")
        workspace = self.headers.get("X-Honcho-Workspace-ID")
        accept = self.headers.get("Accept")

        self._closed = True
        self.ready = False
        self.session_id = None
        self.protocol_version = None
        self._requested_protocol = None
        self.headers.clear()

        if not session_id:
            return

        try:
            if self.tailnet:
                require_tailnet_route()
            delete_headers = {}
            if auth:
                delete_headers["Authorization"] = auth
            if workspace:
                delete_headers["X-Honcho-Workspace-ID"] = workspace
            delete_headers["Mcp-Session-Id"] = session_id
            if protocol:
                delete_headers["MCP-Protocol-Version"] = protocol
            if accept:
                delete_headers["Accept"] = accept
            req = Request(self.url, headers=delete_headers, method="DELETE")
            with self.opener.open(req, timeout=CLOSE_TIMEOUT):
                pass
        except HTTPError as exc:
            try:
                exc.close()
            except Exception:
                pass
        except (Denied, URLError, HTTPException, OSError, ValueError):
            pass


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


def bound_scope(scope):
    return {key: scope[key] for key in SCOPE if key != "task"}


def format_note(scope, evidence):
    if not isinstance(evidence, dict) or not set(FIELDS) <= evidence.keys():
        raise Denied("Unexpected or missing arguments.")
    for key, length in FIELDS.items():
        value = evidence[key]
        if (not isinstance(value, str) or not value.strip() or len(value) > length
                or not value.isprintable()):
            raise Denied(f"Invalid {key}: supply nonempty, bounded, single-line evidence.")
    return (f"{evidence['conclusion']} [Task: {scope['task']}; Candidate/source: {evidence['candidate']}; "
            f"Checks: {evidence['checks']}; Verification: {evidence['verification']}]")


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
    bound = bound_scope(scope)
    if name == "readback":
        return upstream.call("list_conclusions", {**bound, "size": 10})
    note = format_note(scope, args)
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
        except UpstreamHTTPStatus as exc:
            return {**content(f"{exc.reason}; read back before retrying any append."), "isError": True}
        except (URLError, HTTPException, OSError, ValueError, KeyError, TypeError):
            return {**content("Upstream MCP failed; read back before retrying any append."), "isError": True}
    return None


def main():
    try:
        scope, upstream = load_grant(sys.argv[1])
    except Denied as exc:
        sys.exit(f"Honcho publisher: {exc}")
    except (IndexError, OSError, ValueError, TypeError):
        sys.exit("Honcho publisher: invalid or unreadable private grant.")
    try:
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
    finally:
        close_upstream = getattr(upstream, "close", None)
        if callable(close_upstream):
            try:
                close_upstream()
            except Exception:
                pass


if __name__ == "__main__":
    main()
