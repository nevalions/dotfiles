import contextlib
import email.message
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock, Thread
import unittest
from urllib.error import HTTPError
from unittest.mock import patch

GATEWAY = Path(__file__).resolve().parents[1] / "pi/.pi/agent/honcho-cli/gateway.py"
SCOPE = dict(workspace_id="pi-test", peer_id="pi-test-observer",
             target_peer_id="pi-test-repo", session_id="pi-test-session", task="pi-test-task")
EVIDENCE = dict(conclusion="Synthetic Pi publisher smoke marker.", candidate="fixture-v1",
                checks="Publisher scope test passed.", verification="Fixture checked exact upstream scope.")


@contextlib.contextmanager
def fixture():
    writes = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            method = request["method"]
            params = request.get("params", {})
            if (self.headers["Authorization"] != "Bearer fixture-token"
                    or self.headers["X-Honcho-Workspace-ID"] != SCOPE["workspace_id"]
                    or (method != "initialize" and self.headers.get("Mcp-Session-Id") != "fixture-session")):
                self.send_error(403)
                return
            if method == "initialize":
                result = {"protocolVersion": "2025-03-26", "capabilities": {},
                          "serverInfo": {"name": "Honcho protocol fixture", "version": "1"}}
            elif method == "notifications/initialized":
                self.send_response(202)
                self.end_headers()
                return
            elif method == "tools/call":
                args = params["arguments"]
                binding = {key: val for key, val in SCOPE.items() if key != "task"}
                if not all(args.get(key) == val for key, val in binding.items()):
                    self.send_error(403)
                    return
                if params["name"] == "create_conclusions" and set(args) == binding.keys() | {"conclusions"}:
                    writes.extend(args["conclusions"])
                    payload = "Created 1 conclusion"
                elif params["name"] == "list_conclusions" and set(args) == binding.keys() | {"size"}:
                    payload = json.dumps(writes)
                else:
                    self.send_error(403)
                    return
                result = {"content": [{"type": "text", "text": payload}]}
            else:
                self.send_error(400)
                return
            response = json.dumps(dict(jsonrpc="2.0", id=request["id"], result=result))
            self.send_response(200)
            self.send_header("Mcp-Session-Id", "fixture-session")
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(f"event: message\ndata: {response}\n\n".encode())

    with tempfile.TemporaryDirectory() as tmp, ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        token = Path(tmp, "token")
        grant = Path(tmp, "grant.json")
        for path, data in ((token, "fixture-token"), (grant, json.dumps(
            dict(url=f"http://127.0.0.1:{server.server_port}/mcp", token_file=str(token), scope=SCOPE)
        ))):
            path.touch(mode=0o600)
            path.write_text(data)
        try:
            yield grant, writes
        finally:
            server.shutdown()
            thread.join()


def _load_gateway():
    spec = importlib.util.spec_from_file_location("pi_honcho_gateway", GATEWAY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@contextlib.contextmanager
def session_fixture(
    *,
    init_session_id="mcp-sess-1",
    init_protocol="2025-03-26",
    init_body_override=None,
    init_errors=None,
    initialized_status=202,
    reply_session_id=None,
    delete_status=200,
    delete_delay=0.0,
    tool_http_error=None,
    append_body_override=None,
    append_content_type="application/json",
    require_session_on_post=True,
):
    lock = Lock()
    pending_init_errors = list(init_errors or ())
    state = {
        "active_sessions": set(),
        "posts": [],
        "tool_names": [],
        "deletes": [],
        "writes": [],
        "redirect_hits": 0,
    }

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send_raw(self, status, body, content_type="application/json", extra_headers=None):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            if extra_headers:
                for key, value in extra_headers.items():
                    self.send_header(key, value)
            self.end_headers()
            if body:
                self.wfile.write(body)

        def do_GET(self):
            if self.path == "/redirect-target":
                with lock:
                    state["redirect_hits"] += 1
            self._send_raw(200, b"ok")

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            method = request["method"]
            params = request.get("params", {})
            auth = self.headers.get("Authorization")
            workspace = self.headers.get("X-Honcho-Workspace-ID")
            sid = self.headers.get("Mcp-Session-Id")
            proto = self.headers.get("MCP-Protocol-Version")
            with lock:
                state["posts"].append({
                    "method": method,
                    "auth": auth,
                    "workspace": workspace,
                    "session_id": sid,
                    "protocol": proto,
                })
            if auth != "Bearer fixture-token" or workspace != SCOPE["workspace_id"]:
                self._send_raw(403, b"forbidden")
                return
            if method == "initialize":
                if pending_init_errors:
                    with lock:
                        err_status, err_body = pending_init_errors.pop(0) if pending_init_errors else (None, None)
                    if err_status is not None:
                        self._send_raw(err_status, err_body)
                        return
                if isinstance(init_session_id, str) and " " not in init_session_id and "\t" not in init_session_id:
                    with lock:
                        state["active_sessions"].add(init_session_id)
                if init_body_override is not None:
                    self.send_response(200)
                    if isinstance(init_session_id, (list, tuple)):
                        for sid_val in init_session_id:
                            self.send_header("Mcp-Session-Id", sid_val)
                    elif init_session_id is not None:
                        self.send_header("Mcp-Session-Id", init_session_id)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(init_body_override)))
                    self.end_headers()
                    self.wfile.write(init_body_override)
                    return
                result = {"protocolVersion": init_protocol, "capabilities": {},
                          "serverInfo": {"name": "Honcho protocol fixture", "version": "1"}}
                payload = json.dumps(dict(jsonrpc="2.0", id=request["id"], result=result)).encode()
                self.send_response(200)
                if isinstance(init_session_id, (list, tuple)):
                    for sid_val in init_session_id:
                        self.send_header("Mcp-Session-Id", sid_val)
                elif init_session_id is not None:
                    self.send_header("Mcp-Session-Id", init_session_id)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return

            if require_session_on_post and init_session_id is not None and sid != init_session_id:
                self._send_raw(403, b"wrong session")
                return

            if method == "notifications/initialized":
                self._send_raw(initialized_status, b"")
                return

            if method == "tools/call":
                with lock:
                    state["tool_names"].append(params.get("name"))
                if tool_http_error is not None:
                    self._send_raw(tool_http_error[0], tool_http_error[1])
                    return
                args = params["arguments"]
                if params["name"] == "create_conclusions":
                    if append_body_override is not None:
                        override = append_body_override(request) if callable(append_body_override) else append_body_override
                        extra = {}
                        if reply_session_id is not None:
                            extra["Mcp-Session-Id"] = reply_session_id
                        self._send_raw(200, override, content_type=append_content_type, extra_headers=extra)
                        return
                    with lock:
                        state["writes"].extend(args["conclusions"])
                    payload = "Created 1 conclusion"
                elif params["name"] == "list_conclusions":
                    with lock:
                        payload = json.dumps(state["writes"])
                else:
                    self._send_raw(403, b"bad tool")
                    return
                result = {"content": [{"type": "text", "text": payload}]}
                body = json.dumps(dict(jsonrpc="2.0", id=request["id"], result=result)).encode()
                extra = {}
                if reply_session_id is not None:
                    extra["Mcp-Session-Id"] = reply_session_id
                self._send_raw(200, body, extra_headers=extra)
                return

            self._send_raw(400, b"bad method")

        def do_DELETE(self):
            delay = delete_delay
            if delay > 0:
                time.sleep(delay)
            sid = self.headers.get("Mcp-Session-Id")
            with lock:
                state["deletes"].append({
                    "session_id": sid,
                    "protocol": self.headers.get("MCP-Protocol-Version"),
                    "auth": self.headers.get("Authorization"),
                    "workspace": self.headers.get("X-Honcho-Workspace-ID"),
                })
                if delete_status in (200, 202, 204):
                    state["active_sessions"].discard(sid)
            extra = None
            if delete_status in (301, 302, 303, 307, 308):
                extra = {"Location": f"http://127.0.0.1:{self.server.server_port}/redirect-target"}
            try:
                self._send_raw(delete_status, b"", extra_headers=extra)
            except (BrokenPipeError, ConnectionResetError):
                if delay <= 0:
                    raise

    with tempfile.TemporaryDirectory() as tmp, ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        token = Path(tmp, "token")
        grant = Path(tmp, "grant.json")
        for path, data in ((token, "fixture-token"), (grant, json.dumps(
            dict(url=f"http://127.0.0.1:{server.server_port}/mcp", token_file=str(token), scope=SCOPE)
        ))):
            path.touch(mode=0o600)
            path.write_text(data)
        try:
            yield grant, state
        finally:
            server.shutdown()
            thread.join()


class PublisherTest(unittest.TestCase):
    def test_tailnet_http_is_exact_opt_in(self):
        spec = importlib.util.spec_from_file_location("pi_honcho_gateway", GATEWAY)
        gateway = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gateway)
        with fixture() as (grant, writes):
            data = json.loads(grant.read_text())
            with patch.object(gateway, "require_tailnet_route") as route:
                for url, options in (
                    (gateway.TAILNET_URL, {}),
                    (gateway.TAILNET_URL, {"allow_tailnet_http": "true"}),
                    ("http://100.64.0.17:18080/mcp", {"allow_tailnet_http": True}),
                    (gateway.TAILNET_URL + "?x=1", {"allow_tailnet_http": True}),
                ):
                    with self.subTest(url=url, options=options):
                        grant.write_text(json.dumps({**data, "url": url, **options}))
                        with self.assertRaises(ValueError):
                            gateway.load_grant(str(grant))
                route.assert_not_called()
                grant.write_text(json.dumps({**data, "url": gateway.TAILNET_URL,
                                            "allow_tailnet_http": True}))
                _, upstream = gateway.load_grant(str(grant))
                route.assert_called_once()
                route.side_effect = gateway.Denied("route changed")
                with patch.object(upstream.opener, "open") as send:
                    with self.assertRaises(gateway.Denied):
                        upstream.rpc("initialize", {})
                    send.assert_not_called()
            self.assertEqual(writes, [])

    def test_tailnet_route_fails_closed(self):
        spec = importlib.util.spec_from_file_location("pi_honcho_gateway", GATEWAY)
        gateway = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gateway)
        with patch.object(gateway.subprocess, "run") as run:
            for response in (b'[{"dev":"eth0"}]', b'[]', b'not json', b'[null]'):
                run.return_value.stdout = response
                with self.assertRaises(gateway.Denied):
                    gateway.require_tailnet_route()
            run.side_effect = OSError("missing ip")
            with self.assertRaises(gateway.Denied):
                gateway.require_tailnet_route()
            run.side_effect = None
            run.return_value.stdout = b'[{"dev":"tailscale0"}]'
            gateway.require_tailnet_route()
            run.assert_called_with(["/usr/bin/ip", "-j", "route", "get", gateway.TAILNET_HOST],
                                   capture_output=True, check=True, timeout=2)

    def test_gateway_roundtrip(self):
        with fixture() as (grant, writes), subprocess.Popen(
            [sys.executable, GATEWAY, grant], text=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        ) as proc:

            def request(method, **params):
                proc.stdin.write(json.dumps(dict(jsonrpc="2.0", id=1, method=method, params=params)) + "\n")
                proc.stdin.flush()
                return json.loads(proc.stdout.readline())["result"]

            def call(name, **arguments):
                return request("tools/call", name=name, arguments=arguments)

            try:
                self.assertEqual({tool["name"] for tool in request("tools/list")["tools"]},
                                 {"get_grant", "readback", "publish_verified"})
                self.assertEqual(json.loads(call("get_grant")["content"][0]["text"]), SCOPE)
                for key in SCOPE:
                    result = call("publish_verified", scope={**SCOPE, key: "out-of-scope"}, **EVIDENCE)
                    self.assertTrue(result["isError"])
                    self.assertIn("Outside the approved", result["content"][0]["text"])
                self.assertTrue(call("publish_verified", scope=SCOPE, conclusion="unchecked")["isError"])
                self.assertTrue(call("delete_conclusion", scope=SCOPE)["isError"])
                self.assertTrue(call("create_conclusions", scope=SCOPE)["isError"])
                self.assertEqual(writes, [])
                self.assertFalse(call("publish_verified", scope=SCOPE, **EVIDENCE).get("isError"))
                note, = json.loads(call("readback", scope=SCOPE)["content"][0]["text"])
                for value in (SCOPE["task"], *EVIDENCE.values()):
                    self.assertIn(value, note)
                self.assertEqual(len(writes), 1)
            finally:
                proc.stdin.close()
                proc.wait(timeout=5)

    def test_public_grant_fails_closed(self):
        with fixture() as (grant, writes):
            grant.chmod(0o644)
            result = subprocess.run([sys.executable, GATEWAY, grant], capture_output=True, text=True, timeout=5)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("invalid or unreadable", result.stderr)
            self.assertEqual(writes, [])

    def test_gateway_main_eof_and_oversized_exit_delete_transport_session(self):
        with session_fixture(init_protocol="2025-06-18") as (grant, state):
            with subprocess.Popen(
                [sys.executable, GATEWAY, grant],
                text=True,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
            ) as proc:
                try:
                    proc.stdin.write(json.dumps({
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/call",
                        "params": {"name": "publish_verified", "arguments": {"scope": SCOPE, **EVIDENCE}},
                    }) + "\n")
                    proc.stdin.flush()
                    reply = json.loads(proc.stdout.readline())
                    self.assertFalse(reply["result"].get("isError"))
                finally:
                    proc.stdin.close()
                    rc = proc.wait(timeout=5)
            self.assertEqual(rc, 0)
            self.assertEqual(state["active_sessions"], set())
            self.assertEqual(state["deletes"], [{
                "session_id": "mcp-sess-1",
                "protocol": "2025-06-18",
                "auth": "Bearer fixture-token",
                "workspace": SCOPE["workspace_id"],
            }])

        with session_fixture(init_session_id="mcp-sess-oversize") as (grant, state):
            with subprocess.Popen(
                [sys.executable, GATEWAY, grant],
                text=True,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            ) as proc:
                try:
                    proc.stdin.write(json.dumps({
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/call",
                        "params": {"name": "readback", "arguments": {"scope": SCOPE}},
                    }) + "\n")
                    proc.stdin.flush()
                    reply = json.loads(proc.stdout.readline())
                    self.assertFalse(reply["result"].get("isError"))
                    proc.stdin.write("x" * (1024 * 1024 + 8) + "\n")
                    proc.stdin.flush()
                finally:
                    proc.stdin.close()
                    rc = proc.wait(timeout=5)
            self.assertNotEqual(rc, 0)
            self.assertEqual(state["active_sessions"], set())
            self.assertEqual(len(state["deletes"]), 1)
            self.assertEqual(state["deletes"][0]["session_id"], "mcp-sess-oversize")

    def test_close_cleans_failed_handshake_with_requested_protocol_fallback(self):
        gateway = _load_gateway()
        bound = gateway.bound_scope(SCOPE)

        with session_fixture(init_session_id="sess-body-fail", init_body_override=b"{bad") as (grant, state):
            _, upstream = gateway.load_grant(str(grant))
            try:
                with self.assertRaises(ValueError):
                    upstream.call("list_conclusions", {**bound, "size": 10})
                self.assertTrue(upstream._closed)
                self.assertIsNone(upstream.session_id)
                self.assertEqual(upstream.headers, {})
                self.assertFalse(upstream.ready)
                self.assertEqual(state["active_sessions"], set())
                self.assertEqual(state["deletes"], [{
                    "session_id": "sess-body-fail",
                    "protocol": "2025-03-26",
                    "auth": "Bearer fixture-token",
                    "workspace": SCOPE["workspace_id"],
                }])
                with self.assertRaises(ValueError):
                    upstream.call("list_conclusions", {**bound, "size": 10})
                with self.assertRaises(ValueError):
                    upstream.rpc("initialize", {})
                self.assertEqual([p["method"] for p in state["posts"]], ["initialize"])
            finally:
                upstream.close()
                upstream.close()
            self.assertEqual(state["active_sessions"], set())
            self.assertEqual(len(state["deletes"]), 1)
            with self.assertRaises(ValueError):
                upstream.rpc("tools/call", {})

        with session_fixture(init_session_id="sess-proto-fail", init_protocol="1999-01-01") as (grant, state):
            _, upstream = gateway.load_grant(str(grant))
            try:
                with self.assertRaises(ValueError):
                    upstream.call("list_conclusions", {**bound, "size": 10})
                self.assertTrue(upstream._closed)
                self.assertIsNone(upstream.session_id)
                self.assertEqual(state["active_sessions"], set())
                self.assertEqual(state["deletes"], [{
                    "session_id": "sess-proto-fail",
                    "protocol": "2025-03-26",
                    "auth": "Bearer fixture-token",
                    "workspace": SCOPE["workspace_id"],
                }])
                with self.assertRaises(ValueError):
                    upstream.call("list_conclusions", {**bound, "size": 10})
                self.assertEqual([p["method"] for p in state["posts"]], ["initialize"])
            finally:
                upstream.close()
            self.assertEqual(state["active_sessions"], set())
            self.assertEqual(len(state["deletes"]), 1)

        with session_fixture(
            init_session_id="sess-notif-fail",
            init_protocol="2025-06-18",
            initialized_status=500,
        ) as (grant, state):
            _, upstream = gateway.load_grant(str(grant))
            try:
                with self.assertRaises(HTTPError):
                    upstream.call("list_conclusions", {**bound, "size": 10})
                self.assertTrue(upstream._closed)
                self.assertIsNone(upstream.session_id)
                self.assertEqual(state["active_sessions"], set())
                self.assertEqual(state["deletes"], [{
                    "session_id": "sess-notif-fail",
                    "protocol": "2025-06-18",
                    "auth": "Bearer fixture-token",
                    "workspace": SCOPE["workspace_id"],
                }])
                with self.assertRaises(ValueError):
                    upstream.call("list_conclusions", {**bound, "size": 10})
                self.assertEqual(
                    [p["method"] for p in state["posts"]],
                    ["initialize", "notifications/initialized"],
                )
            finally:
                upstream.close()
            self.assertEqual(state["active_sessions"], set())
            self.assertEqual(len(state["deletes"]), 1)

        with session_fixture(init_session_id="sess-live-gw", init_protocol="1999-01-01") as (grant, state):
            with subprocess.Popen(
                [sys.executable, GATEWAY, grant],
                text=True,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
            ) as proc:
                try:
                    proc.stdin.write(json.dumps({
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/call",
                        "params": {"name": "readback", "arguments": {"scope": SCOPE}},
                    }) + "\n")
                    proc.stdin.flush()
                    reply1 = json.loads(proc.stdout.readline())
                    self.assertEqual(reply1["id"], 1)
                    self.assertTrue(reply1["result"]["isError"])
                    self.assertIsNone(proc.poll())
                    self.assertEqual(state["active_sessions"], set())
                    self.assertEqual(state["deletes"], [{
                        "session_id": "sess-live-gw",
                        "protocol": "2025-03-26",
                        "auth": "Bearer fixture-token",
                        "workspace": SCOPE["workspace_id"],
                    }])
                    proc.stdin.write(json.dumps({
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "tools/call",
                        "params": {"name": "readback", "arguments": {"scope": SCOPE}},
                    }) + "\n")
                    proc.stdin.flush()
                    reply2 = json.loads(proc.stdout.readline())
                    self.assertEqual(reply2["id"], 2)
                    self.assertTrue(reply2["result"]["isError"])
                    self.assertEqual([p["method"] for p in state["posts"]], ["initialize"])
                finally:
                    proc.stdin.close()
                    rc = proc.wait(timeout=5)
            self.assertEqual(rc, 0)
            self.assertEqual(len(state["deletes"]), 1)

        with session_fixture(
            init_session_id="sess-after-503",
            init_errors=[(503, b'{"detail":"Too many active sessions"}')],
        ) as (grant, state):
            _, upstream = gateway.load_grant(str(grant))
            try:
                with self.assertRaises(gateway.UpstreamHTTPStatus) as err_cm:
                    upstream.call("list_conclusions", {**bound, "size": 10})
                self.assertEqual(err_cm.exception.status, 503)
                self.assertFalse(upstream._closed)
                self.assertIsNone(upstream.session_id)
                self.assertEqual(state["deletes"], [])
                self.assertEqual([p["method"] for p in state["posts"]], ["initialize"])

                res = upstream.call("list_conclusions", {**bound, "size": 10})
                self.assertEqual(json.loads(res["content"][0]["text"]), [])
                self.assertEqual(upstream.session_id, "sess-after-503")
                self.assertTrue(upstream.ready)
            finally:
                upstream.close()
            self.assertEqual(state["active_sessions"], set())
            self.assertEqual(len(state["deletes"]), 1)

    def test_malformed_and_retargeted_session_ids_never_forwarded(self):
        gateway = _load_gateway()
        bound = gateway.bound_scope(SCOPE)

        self.assertIsNone(gateway._extract_session_id(email.message.Message()))

        dup_headers = email.message.Message()
        dup_headers.add_header("Mcp-Session-Id", "sess-a")
        dup_headers.add_header("Mcp-Session-Id", "sess-b")
        with self.assertRaises(ValueError):
            gateway._extract_session_id(dup_headers)

        for bad_sid in ("bad id", "bad\tid", "nonascii-\u00e9", "", "x" * 4097):
            msg = email.message.Message()
            msg["Mcp-Session-Id"] = bad_sid
            with self.subTest(bad_sid=bad_sid):
                with self.assertRaises(ValueError):
                    gateway._extract_session_id(msg)

        for bad_init_sid in ("bad id", ("sess-a", "sess-b")):
            with session_fixture(init_session_id=bad_init_sid, require_session_on_post=False) as (grant, state):
                _, upstream = gateway.load_grant(str(grant))
                try:
                    with self.assertRaises(ValueError):
                        upstream.call("list_conclusions", {**bound, "size": 10})
                finally:
                    upstream.close()
                self.assertEqual([p["method"] for p in state["posts"]], ["initialize"])
                self.assertTrue(all(post["session_id"] is None for post in state["posts"]))
                self.assertEqual(state["deletes"], [])

        for hijack in ("sess-hijack", "bad hijack\tid"):
            with session_fixture(
                init_session_id="sess-orig",
                reply_session_id=hijack,
                init_protocol="2025-06-18",
            ) as (grant, state):
                _, upstream = gateway.load_grant(str(grant))
                try:
                    upstream.call("list_conclusions", {**bound, "size": 10})
                    upstream.call("list_conclusions", {**bound, "size": 10})
                finally:
                    upstream.close()
                tool_posts = [p for p in state["posts"] if p["method"] != "initialize"]
                self.assertEqual(len(tool_posts), 3)
                self.assertTrue(all(p["session_id"] == "sess-orig" for p in tool_posts))
                self.assertEqual(state["deletes"][0]["session_id"], "sess-orig")
                self.assertEqual(state["deletes"][0]["protocol"], "2025-06-18")

    def test_close_stateless_405_timeout_redirect_and_tailnet_route_nonfatal(self):
        gateway = _load_gateway()
        bound = gateway.bound_scope(SCOPE)

        with session_fixture(init_session_id=None) as (grant, state):
            _, upstream = gateway.load_grant(str(grant))
            upstream.call("list_conclusions", {**bound, "size": 10})
            upstream.close()
            self.assertEqual(state["deletes"], [])
            self.assertEqual(upstream.headers, {})

        with session_fixture(delete_status=405) as (grant, state):
            _, upstream = gateway.load_grant(str(grant))
            upstream.call("list_conclusions", {**bound, "size": 10})
            upstream.close()
            self.assertEqual(len(state["deletes"]), 1)

        with session_fixture(delete_status=302) as (grant, state):
            _, upstream = gateway.load_grant(str(grant))
            upstream.call("list_conclusions", {**bound, "size": 10})
            upstream.close()
            self.assertEqual(len(state["deletes"]), 1)
            self.assertEqual(state["redirect_hits"], 0)

        with session_fixture(delete_delay=0.25) as (grant, state):
            _, upstream = gateway.load_grant(str(grant))
            upstream.call("list_conclusions", {**bound, "size": 10})
            with patch.object(gateway, "CLOSE_TIMEOUT", 0.05):
                upstream.close()
            self.assertEqual(upstream.headers, {})

        with patch.object(gateway, "require_tailnet_route", side_effect=gateway.Denied("no route")):
            tailnet_client = gateway.Honcho(gateway.TAILNET_URL, "tok", "ws", tailnet=True)
            tailnet_client.session_id = "sess-tailnet"
            tailnet_client._requested_protocol = "2025-03-26"
            with patch.object(tailnet_client.opener, "open") as send:
                tailnet_client.close()
            send.assert_not_called()
            self.assertEqual(tailnet_client.headers, {})

    def test_upstream_429_and_503_sanitized_no_retries_and_closes_httperror(self):
        gateway = _load_gateway()
        bound = gateway.bound_scope(SCOPE)

        cases = (
            (503, b'{"detail":"Too many active sessions","secret":"SECRET_BODY /etc/shadow"}',
             "too many active sessions", "503"),
            (503, b"RAW_503_LEAK /var/lib/secret", "service unavailable", "503"),
            (429, b"RAW_429_LEAK quota-token", "rate-limited", "429"),
        )
        for status, body, expected_fragment, expected_code in cases:
            with self.subTest(status=status, fragment=expected_fragment):
                with session_fixture(tool_http_error=(status, body)) as (grant, state):
                    _, upstream = gateway.load_grant(str(grant))
                    closed_codes = []
                    real_open = upstream.opener.open

                    def tracked_open(req, *args, **kwargs):
                        try:
                            return real_open(req, *args, **kwargs)
                        except HTTPError as exc:
                            code = int(exc.code)
                            orig_close = exc.close

                            def spy_close(code=code, orig_close=orig_close):
                                result = orig_close()
                                closed_codes.append(code)
                                return result

                            exc.close = spy_close
                            raise

                    try:
                        with patch.object(upstream.opener, "open", side_effect=tracked_open):
                            with self.assertRaises(gateway.UpstreamHTTPStatus) as err_cm:
                                upstream.call("list_conclusions", {**bound, "size": 10})
                        self.assertEqual(err_cm.exception.status, status)
                        self.assertIn(expected_fragment, err_cm.exception.reason)
                        self.assertIn(expected_code, err_cm.exception.reason)
                        self.assertEqual(closed_codes, [status])
                        tool_posts = [p for p in state["posts"] if p["method"] == "tools/call"]
                        self.assertEqual(len(tool_posts), 1)
                        dispatched = gateway.dispatch({
                            "method": "tools/call",
                            "params": {"name": "readback", "arguments": {"scope": SCOPE}},
                        }, SCOPE, upstream)
                        self.assertTrue(dispatched["isError"])
                        msg = dispatched["content"][0]["text"]
                        self.assertIn(expected_fragment, msg)
                        self.assertIn("read back before retrying", msg)
                        for leak in ("SECRET_BODY", "/etc/shadow", "RAW_503_LEAK", "RAW_429_LEAK", "quota-token"):
                            self.assertNotIn(leak, msg)
                            self.assertNotIn(leak, str(err_cm.exception))
                    finally:
                        upstream.close()

    def test_malformed_upstream_append_envelope_correlated_no_retry(self):
        def sse_event(payload):
            return b"event: message\ndata: " + payload + b"\n\n"

        cases = (
            ("json-null", "application/json", b"null"),
            ("json-list", "application/json", b"[]"),
            ("sse-null", "text/event-stream", sse_event(b"null")),
            ("sse-list", "text/event-stream", sse_event(b"[]")),
            ("json-wrong-version", "application/json",
             lambda req: json.dumps({
                 "jsonrpc": "1.0", "id": req["id"], "result": {"content": [{"type": "text", "text": "ok"}]},
             }).encode()),
            ("sse-wrong-version", "text/event-stream",
             lambda req: sse_event(json.dumps({
                 "jsonrpc": "1.0", "id": req["id"], "result": {"content": [{"type": "text", "text": "ok"}]},
             }).encode())),
            ("json-both-result-and-error", "application/json",
             lambda req: json.dumps({
                 "jsonrpc": "2.0", "id": req["id"],
                 "result": {"content": [{"type": "text", "text": "ok"}]},
                 "error": {"code": -32000, "message": "SECRET_ERR"},
             }).encode()),
            ("sse-both-result-and-error", "text/event-stream",
             lambda req: sse_event(json.dumps({
                 "jsonrpc": "2.0", "id": req["id"],
                 "result": {"content": [{"type": "text", "text": "ok"}]},
                 "error": {"code": -32000, "message": "SECRET_ERR"},
             }).encode())),
            ("json-error-only", "application/json",
             lambda req: json.dumps({
                 "jsonrpc": "2.0", "id": req["id"],
                 "error": {"code": -32000, "message": "SECRET_ERR"},
             }).encode()),
            ("sse-error-only", "text/event-stream",
             lambda req: sse_event(json.dumps({
                 "jsonrpc": "2.0", "id": req["id"],
                 "error": {"code": -32000, "message": "SECRET_ERR"},
             }).encode())),
            ("json-empty-tool-result", "application/json",
             lambda req: json.dumps({"jsonrpc": "2.0", "id": req["id"], "result": {}}).encode()),
            ("sse-empty-tool-result", "text/event-stream",
             lambda req: sse_event(json.dumps({"jsonrpc": "2.0", "id": req["id"], "result": {}}).encode())),
            ("json-nonbool-iserror", "application/json",
             lambda req: json.dumps({
                 "jsonrpc": "2.0", "id": req["id"], "result": {"content": [], "isError": "false"},
             }).encode()),
            ("sse-malformed-content-block", "text/event-stream",
             lambda req: sse_event(json.dumps({
                 "jsonrpc": "2.0", "id": req["id"], "result": {"content": [{"type": "text"}]},
             }).encode())),
            ("json-unknown-content-block-type", "application/json",
             lambda req: json.dumps({
                 "jsonrpc": "2.0", "id": req["id"], "result": {"content": [{"type": "bogus"}]},
             }).encode()),
            ("sse-unknown-content-block-type", "text/event-stream",
             lambda req: sse_event(json.dumps({
                 "jsonrpc": "2.0", "id": req["id"], "result": {"content": [{"type": "bogus"}]},
             }).encode())),
            ("json-nonobject-structured-content", "application/json",
             lambda req: json.dumps({
                 "jsonrpc": "2.0", "id": req["id"], "result": {"content": [], "structuredContent": False},
             }).encode()),
            ("sse-nonobject-structured-content", "text/event-stream",
             lambda req: sse_event(json.dumps({
                 "jsonrpc": "2.0", "id": req["id"], "result": {"content": [], "structuredContent": False},
             }).encode())),
        )
        for label, content_type, body in cases:
            with self.subTest(case=label, content_type=content_type):
                with session_fixture(
                    append_body_override=body,
                    append_content_type=content_type,
                ) as (grant, state):
                    with subprocess.Popen(
                        [sys.executable, GATEWAY, grant],
                        text=True,
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                    ) as proc:
                        try:
                            proc.stdin.write(json.dumps({
                                "jsonrpc": "2.0",
                                "id": 41,
                                "method": "tools/call",
                                "params": {"name": "publish_verified", "arguments": {"scope": SCOPE, **EVIDENCE}},
                            }) + "\n")
                            proc.stdin.flush()
                            reply = json.loads(proc.stdout.readline())
                            self.assertEqual(reply["id"], 41)
                            self.assertNotIn("error", reply)
                            self.assertTrue(reply["result"]["isError"])
                            msg = reply["result"]["content"][0]["text"]
                            self.assertIn("read back before retrying", msg)
                            self.assertNotIn("SECRET_ERR", msg)
                            self.assertEqual(state["tool_names"], ["create_conclusions"])
                            self.assertEqual(state["writes"], [])

                            proc.stdin.write(json.dumps({
                                "jsonrpc": "2.0",
                                "id": 42,
                                "method": "tools/call",
                                "params": {"name": "readback", "arguments": {"scope": SCOPE}},
                            }) + "\n")
                            proc.stdin.flush()
                            readback = json.loads(proc.stdout.readline())
                            self.assertEqual(readback["id"], 42)
                            self.assertFalse(readback["result"].get("isError"))
                            self.assertEqual(json.loads(readback["result"]["content"][0]["text"]), [])
                            self.assertEqual(state["tool_names"], ["create_conclusions", "list_conclusions"])
                            self.assertEqual(state["writes"], [])
                        finally:
                            proc.stdin.close()
                            rc = proc.wait(timeout=5)
                    self.assertEqual(rc, 0)
                    self.assertEqual(state["active_sessions"], set())
                    self.assertEqual(len(state["deletes"]), 1)

        gateway = _load_gateway()
        real_loads = json.loads

        def faulty_loads(raw, *args, **kwargs):
            if isinstance(raw, (bytes, bytearray)) and b"RECURSION_SECRET" in raw:
                raise RecursionError("maximum recursion depth exceeded: RECURSION_SECRET")
            return real_loads(raw, *args, **kwargs)

        stdin_bytes = (
            json.dumps({
                "jsonrpc": "2.0",
                "id": 41,
                "method": "tools/call",
                "params": {"name": "publish_verified", "arguments": {"scope": SCOPE, **EVIDENCE}},
            }) + "\n"
            + json.dumps({
                "jsonrpc": "2.0",
                "id": 42,
                "method": "tools/call",
                "params": {"name": "readback", "arguments": {"scope": SCOPE}},
            }) + "\n"
        ).encode()

        for content_type, body in (
            ("application/json", b'{"sentinel":"RECURSION_SECRET"}'),
            ("text/event-stream", sse_event(b'{"sentinel":"RECURSION_SECRET"}')),
        ):
            with self.subTest(case="recursion-fault", content_type=content_type):
                with session_fixture(
                    append_body_override=body,
                    append_content_type=content_type,
                ) as (grant, state):
                    fake_stdin = type("FakeStdin", (), {"buffer": io.BytesIO(stdin_bytes)})()
                    out_buf = io.StringIO()
                    with (
                        patch.object(sys, "argv", [str(GATEWAY), str(grant)]),
                        patch.object(sys, "stdin", fake_stdin),
                        patch.object(sys, "stdout", out_buf),
                        patch.object(gateway.json, "loads", side_effect=faulty_loads),
                    ):
                        gateway.main()
                    raw_output = out_buf.getvalue()
                    self.assertNotIn("RECURSION_SECRET", raw_output)
                    lines = raw_output.splitlines()
                    self.assertEqual(len(lines), 2)
                    reply = json.loads(lines[0])
                    readback = json.loads(lines[1])
                    self.assertEqual(reply["id"], 41)
                    self.assertNotIn("error", reply)
                    self.assertTrue(reply["result"]["isError"])
                    self.assertIn("read back before retrying", reply["result"]["content"][0]["text"])
                    self.assertEqual(readback["id"], 42)
                    self.assertFalse(readback["result"].get("isError"))
                    self.assertEqual(json.loads(readback["result"]["content"][0]["text"]), [])
                    self.assertEqual(state["tool_names"], ["create_conclusions", "list_conclusions"])
                    self.assertEqual(state["writes"], [])
                    self.assertEqual(state["active_sessions"], set())
                    self.assertEqual(len(state["deletes"]), 1)

    def test_upstream_rpc_envelope_bool_id_sse_skip_and_call_tool_result_forms(self):
        gateway = _load_gateway()
        bound = gateway.bound_scope(SCOPE)

        with session_fixture(
            init_body_override=json.dumps({
                "jsonrpc": "2.0",
                "id": True,
                "result": {"protocolVersion": "2025-03-26"},
            }).encode(),
        ) as (grant, state):
            _, upstream = gateway.load_grant(str(grant))
            try:
                with self.assertRaises(ValueError):
                    upstream.call("list_conclusions", {**bound, "size": 10})
            finally:
                upstream.close()
            self.assertEqual(state["active_sessions"], set())

        with self.assertRaises(ValueError):
            gateway._decode_rpc_envelope(
                b'{"jsonrpc":"2.0","id":true,"result":{}}', 1, allow_unrelated=True
            )
        with self.assertRaises(ValueError):
            gateway._decode_rpc_envelope(
                b'{"jsonrpc":"2.0","id":1.0,"result":{}}', 1, allow_unrelated=False
            )

        with session_fixture(
            append_content_type="text/event-stream",
            append_body_override=lambda req: (
                b'event: message\ndata: {"jsonrpc":"2.0","method":"notifications/progress","params":{"progress":1}}\n\n'
                b'event: message\ndata: {"jsonrpc":"2.0","id":999,"result":{"content":[]}}\n\n'
                + f'event: message\ndata: {json.dumps({"jsonrpc": "2.0", "id": req["id"], "result": {"content": [], "structuredContent": {"created": 1}, "_meta": {"trace": "ok"}}})}\n\n'.encode()
            ),
        ) as (grant, state):
            _, upstream = gateway.load_grant(str(grant))
            try:
                res = upstream.call("create_conclusions", {**bound, "conclusions": ["note"]})
                self.assertEqual(res["content"], [])
                self.assertEqual(res["structuredContent"], {"created": 1})
                self.assertEqual(state["tool_names"], ["create_conclusions"])
            finally:
                upstream.close()

        for valid in (
            {"content": []},
            {"content": [], "structuredContent": {"items": []}},
            {"content": [{"type": "text", "text": "ok"}], "isError": False, "extra": "ignored"},
            {"content": [{"type": "image", "data": "AA==", "mimeType": "image/png", "extra": 1}]},
            {"content": [{"type": "audio", "data": "AA==", "mimeType": "audio/wav", "extra": 1}]},
            {"content": [{"type": "resource", "resource": {"uri": "honcho://note/1", "text": "ok"}, "extra": 1}]},
            {"content": [{"type": "resource_link", "uri": "honcho://note/1", "name": "note", "extra": 1}]},
            {
                "content": [{"type": "text", "text": "ok", "annotations": {"audience": ["assistant"]}}],
                "structuredContent": {"created": 1},
                "_meta": {"trace": "ok"},
            },
        ):
            with self.subTest(valid=valid):
                self.assertEqual(gateway._validate_tool_result(valid), valid)

        with self.assertRaises(gateway.Denied):
            gateway._validate_tool_result({"content": [{"type": "text", "text": "denied"}], "isError": True})

        for invalid in (
            {},
            {"content": None},
            {"content": "ok"},
            {"content": ["ok"]},
            {"content": [{}]},
            {"content": [{"type": ""}]},
            {"content": [{"type": "bogus"}]},
            {"content": [{"type": ["unhashable"]}]},
            {"content": [{"type": {"unhashable": True}}]},
            {"content": [{"type": 123}]},
            {"content": [{"type": "text"}]},
            {"content": [{"type": "text", "text": 123}]},
            {"content": [{"type": "image", "data": "AA=="}]},
            {"content": [{"type": "audio", "mimeType": "audio/wav"}]},
            {"content": [{"type": "resource", "resource": "bad"}]},
            {"content": [{"type": "resource_link", "uri": 123}]},
            {"content": [], "structuredContent": None},
            {"content": [], "structuredContent": False},
            {"content": [], "structuredContent": True},
            {"content": [], "structuredContent": []},
            {"content": [], "structuredContent": "bad"},
            {"content": [], "structuredContent": False, "isError": True},
            {"content": [], "isError": "false"},
            {"content": [], "isError": 1},
            {"isError": True},
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    gateway._validate_tool_result(invalid)

        for fake_reply in (
            {"content": [{"type": "bogus"}]},
            {"content": [], "structuredContent": False},
        ):
            with self.subTest(fake_reply=fake_reply):
                fake_upstream = gateway.Honcho("https://honcho.example/mcp", "tok", SCOPE["workspace_id"])
                fake_upstream.ready = True
                with (
                    patch.object(fake_upstream.opener, "open") as send,
                    patch.object(fake_upstream, "rpc", return_value=fake_reply) as rpc_mock,
                ):
                    dispatched = gateway.dispatch({
                        "method": "tools/call",
                        "params": {"name": "publish_verified", "arguments": {"scope": SCOPE, **EVIDENCE}},
                    }, SCOPE, fake_upstream)
                send.assert_not_called()
                self.assertTrue(dispatched["isError"])
                self.assertIn("read back before retrying", dispatched["content"][0]["text"])
                rpc_mock.assert_called_once()
                self.assertEqual(rpc_mock.call_args.args[0], "tools/call")
                self.assertEqual(rpc_mock.call_args.args[1]["name"], "create_conclusions")

        for compat_reply in (
            {"content": []},
            {"content": [], "structuredContent": {"created": 1}, "_meta": {"trace": "ok"}},
            {"content": [{"type": "resource_link", "uri": "honcho://note/1", "extra": "ok"}]},
        ):
            with self.subTest(compat_reply=compat_reply):
                fake_upstream = gateway.Honcho("https://honcho.example/mcp", "tok", SCOPE["workspace_id"])
                fake_upstream.ready = True
                with (
                    patch.object(fake_upstream.opener, "open") as send,
                    patch.object(fake_upstream, "rpc", return_value=compat_reply) as rpc_mock,
                ):
                    dispatched = gateway.dispatch({
                        "method": "tools/call",
                        "params": {"name": "publish_verified", "arguments": {"scope": SCOPE, **EVIDENCE}},
                    }, SCOPE, fake_upstream)
                send.assert_not_called()
                self.assertFalse(dispatched.get("isError"))
                rpc_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
