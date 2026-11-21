import contextlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
import unittest
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


if __name__ == "__main__":
    unittest.main()
