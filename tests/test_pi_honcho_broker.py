import importlib.util
import json
import os
from pathlib import Path
import pty
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PI_AGENT = ROOT / 'pi/.pi/agent'
DIR = PI_AGENT / 'honcho-cli'
sys.path.insert(0, str(DIR))
import broker

SAMPLE_SUBAGENT_INDEX = (
    'import { spawn } from "node:child_process";\n'
    'import { discoverAgents } from "./agents.ts";\n'
    'interface SingleResult {\n'
    '\terrorMessage?: string;\n'
    '\tterminationSignal?: string;\n'
    '\tspawnError?: Error;\n'
    '\tcwd: string;\n'
    '}\n\n'
    'function resolveAgent(cwd: string, scope: string) {\n'
    '\tconst discovery = discoverAgents(effectiveCwd, scope);\n'
    '\treturn { cwd, available: discovery };\n'
    '}\n'
    'async function runSingleAgent(\n'
    '\tmakeDetails: (results: SingleResult[]) => SubagentDetails,\n'
    ') {}\n'
    'export default function (pi: ExtensionAPI) {\n'
    '\tconst discovery = discoverAgents(ctx.cwd, agentScope);\n'
    '\tconst effectiveCwd = resolvedAgent.cwd;\n'
    '\tconst args = ["--mode", "json", "-p", "--no-session"];\n'
    '\ttry {\n'
    '\t\tconst outcome = await new Promise((resolve) => {\n'
    '\t\t\tlet exited = false;\n'
    '\t\t\tlet closed = false;\n'
    '\t\t\tlet killTimer: ReturnType<typeof setTimeout> | undefined;\n'
    '\t\t\tproc.stdout?.on("data", (data) => {\n'
    '\t\t\t\tif (event.type !== "message_end") return;\n'
    '\t\t\t});\n'
    '\t\t\tproc.on("exit", () => {\n'
    '\t\t\t\texited = true;\n'
    '\t\t\t});\n'
    '\t\t\tconst finish = (result: any) => {\n'
    '\t\t\t\tclosed = true;\n'
    '\t\t\t\tif (killTimer) clearTimeout(killTimer);\n'
    '\t\t\t\tresolve(result);\n'
    '\t\t\t};\n'
    '\t\t\tconst abort = () => {\n'
    '\t\t\t\tif (closed || exited || proc.exitCode !== null || proc.signalCode !== null) return;\n'
    '\t\t\t\tif (!proc.kill("SIGTERM")) return;\n'
    '\t\t\t\twasAborted = true;\n'
    '\t\t\t\tkillTimer = setTimeout(() => {\n'
    '\t\t\t\t\tif (!closed && !exited) proc.kill("SIGKILL");\n'
    '\t\t\t\t}, 5000);\n'
    '\t\t\t};\n'
    '\t\t});\n'
    '\t\tif (wasAborted) {\n'
    '\t\t\tcurrentResult.status = "aborted";\n'
    '\t\t}\n'
    '\t\treturn currentResult;\n'
    '\t} finally {\n'
    '\t}\n'
    '}\n'
)


def load_prepare_subagent():
    spec = importlib.util.spec_from_file_location('prepare_subagent', PI_AGENT / 'team/prepare-subagent.py')
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BrokerTests(unittest.TestCase):
    def test_automatic_targets(self):
        import launch
        for repo in ('kube-lvl47', 'agent-ui', 'ansible', 'statsboard--statsboards-backend'):
            routes = [repo, 'project-example', 'code-wide']
            self.assertEqual(launch.choose(routes, None), repo)
            self.assertEqual(launch.choose(routes, repo), repo)
            for other in routes[1:]:
                with self.assertRaises(launch.Denied):
                    launch.choose(routes, other)
        self.assertIsNone(launch.choose([], None))
        self.assertIsNone(launch.choose(['dotfiles', 'code-wide'], None))

    def test_child_relay_and_unrelated_client(self):
        class Remote:
            notes = []

            def call(self, name, args):
                if name == 'create_conclusions':
                    self.notes.extend(args['conclusions'])
                elif name != 'list_conclusions':
                    raise AssertionError(name)
                return {'content': [{'type': 'text', 'text': json.dumps(self.notes)}]}

        remote = Remote()
        scope = dict(workspace_id='w', peer_id='pi-coordinator', target_peer_id='kube-lvl47', session_id='test', task='test')
        with tempfile.TemporaryDirectory() as tmp, socket.socket(socket.AF_UNIX) as server:
            path = tmp + '/rpc'
            server.bind(path)
            server.listen()
            server.settimeout(1)
            driver = 'import os,sys,subprocess; assert os.read(0,6)==b"start\\n"; subprocess.run(sys.argv[1:],stdin=sys.stdin,check=True)'
            with subprocess.Popen([sys.executable, '-c', driver, sys.executable, '-I', str(DIR / 'broker.py'), path, 'test'], stdin=subprocess.PIPE, stdout=subprocess.PIPE) as coordinator:
                def bind(sid):
                    self.assertEqual(sid, scope['session_id'])
                    return scope, remote
                thread = threading.Thread(target=broker.serve, args=(server, coordinator, bind), daemon=True)
                thread.start()
                with socket.socket(socket.AF_UNIX) as outsider:
                    outsider.settimeout(2)
                    outsider.connect(path)
                    self.assertEqual(outsider.recv(1), b'')
                coordinator.stdin.write(b'start\n')
                coordinator.stdin.flush()
                inputs = [('get_grant', {}), ('publish_verified', dict(scope=scope, candidate='rev', checks='pass', verification='review', conclusion='verified')), ('readback', dict(scope=scope))]
                for i, (name, args) in enumerate(inputs):
                    coordinator.stdin.write(json.dumps(dict(id=i, method='tools/call', params=dict(name=name, arguments=args))).encode() + b'\n')
                    coordinator.stdin.flush()
                    result = json.loads(coordinator.stdout.readline())['result']
                    self.assertFalse(result.get('isError'))
                    if name == 'readback':
                        self.assertIn('verified [Task:', result['content'][0]['text'])
                coordinator.stdin.close()
                self.assertEqual(coordinator.wait(timeout=3), 0)

    def test_relay_disconnect_closes_remote_session(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        import gateway

        deletes = []
        active = set()

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                return

            def do_POST(self):
                req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                method = req["method"]
                if method == "initialize":
                    active.add("broker-sess-1")
                    result = {"protocolVersion": "2025-06-18", "capabilities": {}}
                elif method == "notifications/initialized":
                    self.send_response(202)
                    self.end_headers()
                    return
                elif method == "tools/call":
                    result = {"content": [{"type": "text", "text": "[]"}]}
                else:
                    result = {}
                payload = json.dumps({"jsonrpc": "2.0", "id": req["id"], "result": result}).encode()
                self.send_response(200)
                self.send_header("Mcp-Session-Id", "broker-sess-1")
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def do_DELETE(self):
                sid = self.headers.get("Mcp-Session-Id")
                deletes.append({
                    "session_id": sid,
                    "protocol": self.headers.get("MCP-Protocol-Version"),
                    "auth": self.headers.get("Authorization"),
                    "workspace": self.headers.get("X-Honcho-Workspace-ID"),
                })
                active.discard(sid)
                self.send_response(200)
                self.send_header("Content-Length", "0")
                self.end_headers()

        scope = dict(workspace_id='w', peer_id='pi-coordinator', target_peer_id='kube-lvl47', session_id='test', task='test')
        with tempfile.TemporaryDirectory() as tmp, \
                ThreadingHTTPServer(("127.0.0.1", 0), Handler) as http_srv, \
                socket.socket(socket.AF_UNIX) as server:
            http_thread = threading.Thread(target=http_srv.serve_forever, daemon=True)
            http_thread.start()
            try:
                url = f"http://127.0.0.1:{http_srv.server_port}/mcp"
                path = tmp + '/rpc'
                server.bind(path)
                server.listen()
                server.settimeout(0.2)
                driver = 'import sys,subprocess; subprocess.run(sys.argv[1:],stdin=sys.stdin,check=True)'
                with subprocess.Popen(
                    [sys.executable, '-c', driver, sys.executable, '-I', str(DIR / 'broker.py'), path, 'test'],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                ) as relay_proc:
                    def bind(sid):
                        self.assertEqual(sid, scope['session_id'])
                        return scope, gateway.Honcho(url, 'broker-token', scope['workspace_id'])

                    thread = threading.Thread(target=broker.serve, args=(server, relay_proc, bind), daemon=True)
                    thread.start()
                    relay_proc.stdin.write(
                        json.dumps(dict(id=1, method='tools/call', params=dict(name='readback', arguments=dict(scope=scope)))).encode() + b'\n'
                    )
                    relay_proc.stdin.flush()
                    reply = json.loads(relay_proc.stdout.readline())
                    self.assertFalse(reply['result'].get('isError'))
                    self.assertEqual(active, {'broker-sess-1'})
                    relay_proc.stdin.close()
                    self.assertEqual(relay_proc.wait(timeout=3), 0)
                    thread.join(timeout=3)
                self.assertEqual(active, set())
                self.assertEqual(deletes, [{
                    "session_id": "broker-sess-1",
                    "protocol": "2025-06-18",
                    "auth": "Bearer broker-token",
                    "workspace": "w",
                }])
            finally:
                http_srv.shutdown()
                http_thread.join(timeout=2)

    def test_malformed_upstream_append_correlated_does_not_drop_broker(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        import gateway

        scope = dict(workspace_id='w', peer_id='pi-coordinator', target_peer_id='kube-lvl47', session_id='test', task='test')
        evidence = dict(candidate='rev', checks='pass', verification='review', conclusion='verified')
        cases = (
            ('application/json', b'null'),
            ('text/event-stream', b'event: message\ndata: []\n\n'),
        )
        for content_type, bad_body in cases:
            with self.subTest(content_type=content_type, bad_body=bad_body):
                deletes = []
                active = set()
                tool_calls = []

                class Handler(BaseHTTPRequestHandler):
                    def log_message(self, *args):
                        return

                    def do_POST(self):
                        req = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                        method = req['method']
                        if method == 'initialize':
                            active.add('broker-sess-malformed')
                            result = {'protocolVersion': '2025-06-18', 'capabilities': {}}
                        elif method == 'notifications/initialized':
                            self.send_response(202)
                            self.end_headers()
                            return
                        elif method == 'tools/call':
                            name = req['params']['name']
                            tool_calls.append(name)
                            if name == 'create_conclusions':
                                self.send_response(200)
                                self.send_header('Content-Type', content_type)
                                self.send_header('Content-Length', str(len(bad_body)))
                                self.end_headers()
                                self.wfile.write(bad_body)
                                return
                            if name == 'list_conclusions':
                                result = {'content': [{'type': 'text', 'text': '[]'}]}
                            else:
                                self.send_response(403)
                                self.end_headers()
                                return
                        else:
                            result = {}
                        payload = json.dumps({'jsonrpc': '2.0', 'id': req['id'], 'result': result}).encode()
                        self.send_response(200)
                        self.send_header('Mcp-Session-Id', 'broker-sess-malformed')
                        self.send_header('Content-Type', 'application/json')
                        self.send_header('Content-Length', str(len(payload)))
                        self.end_headers()
                        self.wfile.write(payload)

                    def do_DELETE(self):
                        sid = self.headers.get('Mcp-Session-Id')
                        deletes.append(sid)
                        active.discard(sid)
                        self.send_response(200)
                        self.send_header('Content-Length', '0')
                        self.end_headers()

                with tempfile.TemporaryDirectory() as tmp, \
                        ThreadingHTTPServer(('127.0.0.1', 0), Handler) as http_srv, \
                        socket.socket(socket.AF_UNIX) as server:
                    http_thread = threading.Thread(target=http_srv.serve_forever, daemon=True)
                    http_thread.start()
                    try:
                        url = f'http://127.0.0.1:{http_srv.server_port}/mcp'
                        path = tmp + '/rpc'
                        server.bind(path)
                        server.listen()
                        server.settimeout(0.2)
                        driver = 'import sys,subprocess; subprocess.run(sys.argv[1:],stdin=sys.stdin,check=True)'
                        with subprocess.Popen(
                            [sys.executable, '-c', driver, sys.executable, '-I', str(DIR / 'broker.py'), path, 'test'],
                            stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE,
                        ) as relay_proc:
                            def bind(sid):
                                self.assertEqual(sid, scope['session_id'])
                                return scope, gateway.Honcho(url, 'broker-token', scope['workspace_id'])

                            thread = threading.Thread(target=broker.serve, args=(server, relay_proc, bind), daemon=True)
                            thread.start()
                            relay_proc.stdin.write(json.dumps({
                                'id': 11,
                                'method': 'tools/call',
                                'params': {'name': 'publish_verified', 'arguments': {'scope': scope, **evidence}},
                            }).encode() + b'\n')
                            relay_proc.stdin.flush()
                            reply = json.loads(relay_proc.stdout.readline())
                            self.assertEqual(reply['id'], 11)
                            self.assertTrue(reply['result']['isError'])
                            self.assertIn('read back before retrying', reply['result']['content'][0]['text'])
                            self.assertEqual(tool_calls, ['create_conclusions'])

                            relay_proc.stdin.write(json.dumps({
                                'id': 12,
                                'method': 'tools/call',
                                'params': {'name': 'readback', 'arguments': {'scope': scope}},
                            }).encode() + b'\n')
                            relay_proc.stdin.flush()
                            readback = json.loads(relay_proc.stdout.readline())
                            self.assertEqual(readback['id'], 12)
                            self.assertFalse(readback['result'].get('isError'))
                            self.assertEqual(json.loads(readback['result']['content'][0]['text']), [])

                            relay_proc.stdin.close()
                            self.assertEqual(relay_proc.wait(timeout=3), 0)
                            thread.join(timeout=3)
                        self.assertEqual(active, set())
                        self.assertEqual(deletes, ['broker-sess-malformed'])
                    finally:
                        http_srv.shutdown()
                        http_thread.join(timeout=2)


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.home = self.base / 'home'
        self.agent = self.home / '.pi/agent'
        (self.agent / 'bin').mkdir(parents=True)
        (self.agent / 'agents').mkdir()
        (self.agent / 'extensions').mkdir()
        (self.agent / 'honcho-cli').mkdir()
        (self.agent / 'install').mkdir()
        (self.agent / 'bin/pi-team').symlink_to(PI_AGENT / 'bin/pi-team')
        (self.agent / 'bin/pi').symlink_to(PI_AGENT / 'bin/pi')
        (self.agent / 'honcho-cli/gateway.py').symlink_to(DIR / 'gateway.py')
        (self.agent / 'extensions/agy-worker.ts').write_text('export default function () {}\n')
        (self.agent / 'install/current-version').write_text('1.6.0\n')
        self.examples = (
            self.agent / 'install/releases/1.6.0/node_modules/@earendil-works/pi-coding-agent/examples/extensions'
        )
        (self.examples / 'subagent').mkdir(parents=True)
        (self.examples / 'todo.ts').write_text('export default function () {}\n')
        (self.examples / 'subagent/index.ts').write_text(SAMPLE_SUBAGENT_INDEX)
        self.recall_marker = self.home / 'recall-called'
        (self.agent / 'honcho-cli/recall-scopes.py').write_text(
            'from pathlib import Path\n'
            f'Path({json.dumps(str(self.recall_marker))}).write_text("1\\n")\n'
            'print("[]")\n'
        )
        self.capture_file = self.home / 'captured-argv.json'
        managed = self.agent / 'bin/pi.managed'
        managed.write_text(
            f'#!{sys.executable}\n'
            'import json, os, sys\n'
            'from pathlib import Path\n'
            'if target := os.environ.get("PI_TEST_CAPTURE"):\n'
            '    Path(target).write_text(json.dumps(sys.argv[1:]))\n'
        )
        managed.chmod(0o700)

    def capture_pi_team_argv(self, *extra):
        env = {
            'HOME': str(self.home),
            'PATH': os.environ.get('PATH', '/usr/bin:/bin'),
            'PI_TEST_CAPTURE': str(self.capture_file),
            'PI_OFFLINE': '1',
        }
        subprocess.run([str(self.agent / 'bin/pi-team'), *extra], env=env, check=True)
        return json.loads(self.capture_file.read_text())

    def run_pi_pty(self, args, extra_env=None):
        self.recall_marker.unlink(missing_ok=True)
        self.capture_file.unlink(missing_ok=True)
        env = {
            'HOME': str(self.home),
            'PATH': os.environ.get('PATH', '/usr/bin:/bin'),
            'PI_TEST_CAPTURE': str(self.capture_file),
        }
        if extra_env:
            env.update(extra_env)
        master, slave = pty.openpty()
        try:
            proc = subprocess.Popen(
                [str(self.agent / 'bin/pi'), *args],
                stdin=slave,
                stdout=slave,
                stderr=subprocess.PIPE,
                env=env,
                close_fds=True,
            )
            os.close(slave)
            slave = -1
            _, stderr = proc.communicate(timeout=5)
            return proc.returncode, stderr
        finally:
            if slave != -1:
                os.close(slave)
            os.close(master)

    def restore_baseline(self, argv):
        import launch

        version_file = self.agent / 'install/current-version'
        version_file.unlink(missing_ok=True)
        version_file.write_text('1.6.0\n')
        source = self.examples / 'subagent/index.ts'
        source.unlink(missing_ok=True)
        source.write_text(SAMPLE_SUBAGENT_INDEX)
        todo = self.examples / 'todo.ts'
        todo.unlink(missing_ok=True)
        todo.write_text('export default function () {}\n')
        cache = self.agent / 'install/team-cache'
        cache.mkdir(parents=True, exist_ok=True)
        dest = Path(argv[1])
        dest.unlink(missing_ok=True)
        prepared = load_prepare_subagent().prepare(source, cache)
        self.assertEqual(prepared, dest)
        with patch.object(launch, 'AGENT', self.agent):
            self.assertTrue(launch.plain(argv))

    def run_plain_with_timeout(self, argv, timeout=2):
        script = (
            'import json, sys; from pathlib import Path; '
            f'sys.path.insert(0, {json.dumps(str(DIR))}); '
            'import launch; '
            'launch.AGENT = Path(sys.argv[1]); '
            'print(json.dumps(launch.plain(json.loads(sys.argv[2]))))'
        )
        proc = subprocess.run(
            [sys.executable, '-c', script, str(self.agent), json.dumps(argv)],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=True,
        )
        return json.loads(proc.stdout)

    def run_prepare_with_timeout(self, fn_name, source, cache, timeout=2):
        script = (
            'import importlib.util, sys; '
            f'spec = importlib.util.spec_from_file_location("prepare_subagent", {json.dumps(str(PI_AGENT / "team/prepare-subagent.py"))}); '
            'mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); '
            f'getattr(mod, {json.dumps(fn_name)})(sys.argv[1], sys.argv[2])'
        )
        return subprocess.run(
            [sys.executable, '-c', script, str(source), str(cache)],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

    def test_render_is_pure_and_matches_prepare(self):
        prepare_subagent = load_prepare_subagent()
        source = self.examples / 'subagent/index.ts'
        cache = self.agent / 'install/team-cache'
        linked_source = self.base / 'source-link.ts'
        linked_source.symlink_to(source)
        linked_cache = self.base / 'cache-link'
        linked_cache.symlink_to(cache.parent)
        subcache = linked_cache / 'team-cache'

        dest, data = prepare_subagent.render(linked_source, subcache)
        self.assertFalse(cache.exists())
        self.assertEqual(dest.parent, cache.resolve())

        prepared = prepare_subagent.prepare(source, cache)
        self.assertEqual(prepared, dest)
        self.assertEqual(prepared.read_bytes(), data)

        (self.examples / 'subagent/index.ts').write_text(
            SAMPLE_SUBAGENT_INDEX + '//' + 'x' * (prepare_subagent.MAX_SOURCE_BYTES + 16)
        )
        with self.assertRaises(ValueError):
            prepare_subagent.render(source, cache)

        (self.examples / 'subagent/index.ts').write_text('broken layout\n')
        with self.assertRaises(ValueError):
            prepare_subagent.render(source, cache)
        source.unlink()
        with self.assertRaises(FileNotFoundError):
            prepare_subagent.render(source, cache)

    def test_render_normalizes_crlf_and_cr_to_identical_bytes_and_path(self):
        prepare_subagent = load_prepare_subagent()
        source = self.examples / 'subagent/index.ts'
        cache = self.agent / 'install/team-cache'

        lf_dest, lf_data = prepare_subagent.render(source, cache)

        source.write_bytes(SAMPLE_SUBAGENT_INDEX.replace('\n', '\r\n').encode('utf-8'))
        crlf_dest, crlf_data = prepare_subagent.render(source, cache)
        self.assertEqual(crlf_dest, lf_dest)
        self.assertEqual(crlf_data, lf_data)

        source.write_bytes(SAMPLE_SUBAGENT_INDEX.replace('\n', '\r').encode('utf-8'))
        cr_dest, cr_data = prepare_subagent.render(source, cache)
        self.assertEqual(cr_dest, lf_dest)
        self.assertEqual(cr_data, lf_data)

    def test_real_pi_team_invocation_and_selectors_accepted(self):
        import launch

        argv = self.capture_pi_team_argv()
        self.assertEqual(argv[4], '--append-system-prompt')
        self.assertTrue(argv[5].endswith('/bin/../team/workflow.md'))
        with patch.object(launch, 'AGENT', self.agent):
            self.assertTrue(launch.plain([]))
            self.assertTrue(launch.plain(argv))
            for selector in (
                ['-r'],
                ['--resume'],
                ['-c'],
                ['--continue'],
                ['--session', 'session-1'],
                ['--session-id', 'session-2'],
            ):
                self.assertTrue(launch.plain(selector), selector)
                self.assertTrue(launch.plain([*argv, *selector]), selector)

        code, stderr = self.run_pi_pty(argv)
        self.assertEqual(code, 0)
        self.assertEqual(stderr, b'')
        self.assertTrue(self.recall_marker.exists())
        self.assertEqual(json.loads(self.capture_file.read_text()), argv)

        for key in ('PI_OFFLINE', 'PI_HONCHO_NESTED', 'PI_HONCHO_PUBLISH_GRANT'):
            code, stderr = self.run_pi_pty(argv, extra_env={key: '1'})
            self.assertEqual(code, 0)
            self.assertEqual(stderr, b'')
            self.assertFalse(self.recall_marker.exists(), key)

        self.recall_marker.unlink(missing_ok=True)
        non_tty_env = {
            'HOME': str(self.home),
            'PATH': os.environ.get('PATH', '/usr/bin:/bin'),
            'PI_TEST_CAPTURE': str(self.capture_file),
        }
        non_tty = subprocess.run(
            [str(self.agent / 'bin/pi'), *argv],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            env=non_tty_env,
            timeout=5,
            check=False,
        )
        self.assertEqual(non_tty.returncode, 0)
        self.assertEqual(non_tty.stderr, b'')
        self.assertFalse(self.recall_marker.exists())

        (self.agent / 'install/current-version').write_text('1.6.0\nextra\n')
        try:
            multiline_argv = self.capture_pi_team_argv()
            self.assertEqual(multiline_argv, argv)
            with patch.object(launch, 'AGENT', self.agent):
                self.assertTrue(launch.plain(multiline_argv))
            code, stderr = self.run_pi_pty(multiline_argv)
            self.assertEqual(code, 0)
            self.assertEqual(stderr, b'')
            self.assertTrue(self.recall_marker.exists())
        finally:
            (self.agent / 'install/current-version').write_text('1.6.0\n')

    def test_tampered_variants_rejected_without_creating_or_repairing_cache(self):
        import launch

        argv = self.capture_pi_team_argv()
        dest = Path(argv[1])
        expected = dest.read_bytes()
        cache = self.agent / 'install/team-cache'
        outside_file = self.base / dest.name
        outside_file.write_bytes(expected)

        self.restore_baseline(argv)
        with patch.object(launch, 'AGENT', self.agent):
            raw = list(argv)
            raw[1] = str(self.examples / 'subagent/index.ts')
            self.assertFalse(launch.plain(raw))

        self.restore_baseline(argv)
        wrong_path = cache.resolve() / 'subagent-wrong.ts'
        wrong_path.write_bytes(expected)
        try:
            with patch.object(launch, 'AGENT', self.agent):
                wrong_name = list(argv)
                wrong_name[1] = str(wrong_path)
                self.assertFalse(launch.plain(wrong_name))
        finally:
            wrong_path.unlink(missing_ok=True)

        self.restore_baseline(argv)
        with patch.object(launch, 'AGENT', self.agent):
            out_of_cache = list(argv)
            out_of_cache[1] = str(outside_file)
            self.assertFalse(launch.plain(out_of_cache))

        self.restore_baseline(argv)
        link_arg_path = cache.resolve() / 'subagent-link.ts'
        link_arg_path.symlink_to(dest)
        try:
            with patch.object(launch, 'AGENT', self.agent):
                symlink_arg = list(argv)
                symlink_arg[1] = str(link_arg_path)
                self.assertFalse(launch.plain(symlink_arg))
        finally:
            link_arg_path.unlink(missing_ok=True)

        self.restore_baseline(argv)
        other_workflow = self.base / 'workflow.md'
        other_workflow.write_bytes((PI_AGENT / 'team/workflow.md').read_bytes())
        unrelated_workflow_link = self.base / 'unrelated-workflow.md'
        unrelated_workflow_link.symlink_to(PI_AGENT / 'team/workflow.md')
        canonical_workflow = str((PI_AGENT / 'team/workflow.md').resolve())
        with patch.object(launch, 'AGENT', self.agent):
            for bad_wf in (
                str(other_workflow),
                str(unrelated_workflow_link),
                canonical_workflow,
                str(self.base / 'missing.md'),
                'workflow.md',
            ):
                bad = list(argv)
                bad[5] = bad_wf
                self.assertFalse(launch.plain(bad), bad_wf)

        self.restore_baseline(argv)
        with patch.object(launch, 'AGENT', self.agent):
            for bad_extra in (
                [*argv, '--model', 'jev/auto'],
                [*argv, '--extension', str(self.examples / 'todo.ts')],
                [*argv, '--session', '-r'],
                [*argv, '-r', '-c'],
                argv[:-1],
            ):
                self.assertFalse(launch.plain(bad_extra), bad_extra)

        self.restore_baseline(argv)
        dest.write_bytes(b'tampered')
        with patch.object(launch, 'AGENT', self.agent):
            self.assertFalse(launch.plain(argv))
        self.assertEqual(dest.read_bytes(), b'tampered')
        code, stderr = self.run_pi_pty(argv)
        self.assertEqual(code, 0)
        self.assertEqual(stderr, b'')
        self.assertFalse(self.recall_marker.exists())
        self.assertEqual(dest.read_bytes(), b'tampered')

        self.restore_baseline(argv)
        flipped = bytearray(expected)
        flipped[-1] ^= 0x01
        flipped_bytes = bytes(flipped)
        self.assertEqual(len(flipped_bytes), len(expected))
        self.assertNotEqual(flipped_bytes, expected)
        dest.write_bytes(flipped_bytes)
        with patch.object(launch, 'AGENT', self.agent):
            self.assertFalse(launch.plain(argv))
        self.assertEqual(dest.read_bytes(), flipped_bytes)
        code, stderr = self.run_pi_pty(argv)
        self.assertEqual(code, 0)
        self.assertEqual(stderr, b'')
        self.assertFalse(self.recall_marker.exists())
        self.assertEqual(dest.read_bytes(), flipped_bytes)

        self.restore_baseline(argv)
        dest.unlink()
        dest.symlink_to(outside_file)
        with patch.object(launch, 'AGENT', self.agent):
            self.assertFalse(launch.plain(argv))
        self.assertTrue(dest.is_symlink())
        code, stderr = self.run_pi_pty(argv)
        self.assertEqual(code, 0)
        self.assertEqual(stderr, b'')
        self.assertFalse(self.recall_marker.exists())
        self.assertTrue(dest.is_symlink())

        self.restore_baseline(argv)
        shutil.rmtree(cache)
        with patch.object(launch, 'AGENT', self.agent):
            self.assertFalse(launch.plain(argv))
        self.assertFalse(cache.exists())
        code, stderr = self.run_pi_pty(argv)
        self.assertEqual(code, 0)
        self.assertEqual(stderr, b'')
        self.assertFalse(self.recall_marker.exists())
        self.assertFalse(cache.exists())

        for bad_version in (
            b'',
            b'1.6.0',
            b'1.6.0\r\n',
            b'1.6.0\r\nignored\n',
            b'\n',
            b'.\n',
            b'..\n',
            b'../1.6.0\n',
            b'1.6.0/sub\n',
            b'1.6.0 bad\n',
            b'1.6.0\x00\n',
            b'1.6.0\xc3\xa9\n',
            b'1.6.0\n' + b'a' * 300,
        ):
            self.restore_baseline(argv)
            (self.agent / 'install/current-version').write_bytes(bad_version)
            with patch.object(launch, 'AGENT', self.agent):
                self.assertFalse(launch.plain(argv), repr(bad_version))

        self.restore_baseline(argv)
        (self.agent / 'install/current-version').unlink()
        with patch.object(launch, 'AGENT', self.agent):
            self.assertFalse(launch.plain(argv))
        code, stderr = self.run_pi_pty(argv)
        self.assertEqual(code, 0)
        self.assertEqual(stderr, b'')
        self.assertFalse(self.recall_marker.exists())

        self.restore_baseline(argv)
        (self.examples / 'subagent/index.ts').write_text('broken anchor\n')
        with patch.object(launch, 'AGENT', self.agent):
            self.assertFalse(launch.plain(argv))
        self.assertEqual(dest.read_bytes(), expected)

        self.restore_baseline(argv)
        (self.examples / 'subagent/index.ts').write_text(
            SAMPLE_SUBAGENT_INDEX + '//' + 'x' * (load_prepare_subagent().MAX_SOURCE_BYTES + 16)
        )
        with patch.object(launch, 'AGENT', self.agent):
            self.assertFalse(launch.plain(argv))
        self.assertEqual(dest.read_bytes(), expected)

        self.restore_baseline(argv)
        (self.examples / 'subagent/index.ts').unlink()
        with patch.object(launch, 'AGENT', self.agent):
            self.assertFalse(launch.plain(argv))

        self.restore_baseline(argv)
        (self.examples / 'todo.ts').unlink()
        with patch.object(launch, 'AGENT', self.agent):
            self.assertFalse(launch.plain(argv))

        self.restore_baseline(argv)
        (self.examples / 'todo.ts').unlink()
        (self.examples / 'todo.ts').symlink_to(outside_file)
        with patch.object(launch, 'AGENT', self.agent):
            self.assertFalse(launch.plain(argv))

    def test_fifo_inputs_fail_closed_within_timeout(self):
        argv = self.capture_pi_team_argv()
        dest = Path(argv[1])
        expected = dest.read_bytes()
        version_file = self.agent / 'install/current-version'
        source_file = self.examples / 'subagent/index.ts'
        cache_dir = self.agent / 'install/team-cache'

        self.restore_baseline(argv)
        version_file.unlink()
        os.mkfifo(version_file)
        self.assertFalse(self.run_plain_with_timeout(argv))
        code, stderr = self.run_pi_pty(argv)
        self.assertEqual(code, 0)
        self.assertEqual(stderr, b'')
        self.assertFalse(self.recall_marker.exists())
        self.assertEqual(dest.read_bytes(), expected)

        self.restore_baseline(argv)
        source_file.unlink()
        os.mkfifo(source_file)
        render_proc = self.run_prepare_with_timeout('render', source_file, cache_dir)
        self.assertNotEqual(render_proc.returncode, 0)
        self.assertIn('ValueError', render_proc.stderr)
        self.assertFalse(self.run_plain_with_timeout(argv))
        code, stderr = self.run_pi_pty(argv)
        self.assertEqual(code, 0)
        self.assertEqual(stderr, b'')
        self.assertFalse(self.recall_marker.exists())
        self.assertEqual(dest.read_bytes(), expected)

        self.restore_baseline(argv)
        dest.unlink()
        os.mkfifo(dest)
        self.assertFalse(self.run_plain_with_timeout(argv))
        prepare_proc = self.run_prepare_with_timeout('prepare', source_file, cache_dir)
        self.assertNotEqual(prepare_proc.returncode, 0)
        self.assertIn('ValueError', prepare_proc.stderr)
        code, stderr = self.run_pi_pty(argv)
        self.assertEqual(code, 0)
        self.assertEqual(stderr, b'')
        self.assertFalse(self.recall_marker.exists())
        self.assertTrue(stat.S_ISFIFO(dest.lstat().st_mode))

    def test_run_coordinator_waits_for_ordinary_relay_close_within_timeout(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        import gateway
        import launch

        scope = dict(workspace_id='w', peer_id='pi-coordinator', target_peer_id='kube-lvl47', session_id='test', task='test')
        active = set()
        deletes = []
        events = []
        lock = threading.Lock()

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                return

            def do_POST(self):
                req = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                method = req['method']
                if method == 'initialize':
                    with lock:
                        active.add('launch-sess-1')
                        events.append('initialized')
                    result = {'protocolVersion': '2025-06-18', 'capabilities': {}}
                elif method == 'notifications/initialized':
                    self.send_response(202)
                    self.end_headers()
                    return
                elif method == 'tools/call':
                    result = {'content': [{'type': 'text', 'text': '[]'}]}
                else:
                    result = {}
                payload = json.dumps({'jsonrpc': '2.0', 'id': req['id'], 'result': result}).encode()
                self.send_response(200)
                self.send_header('Mcp-Session-Id', 'launch-sess-1')
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def do_DELETE(self):
                time.sleep(0.25)
                sid = self.headers.get('Mcp-Session-Id')
                with lock:
                    deletes.append(sid)
                    active.discard(sid)
                    events.append('deleted')
                self.send_response(200)
                self.send_header('Content-Length', '0')
                self.end_headers()

        coordinator_script = (
            'import json, subprocess, sys\n'
            'relay = subprocess.Popen([sys.executable, "-I", sys.argv[1], sys.argv[2], "test"], '
            'stdin=subprocess.PIPE, stdout=subprocess.PIPE)\n'
            'req = {"id": 1, "method": "tools/call", "params": {"name": "readback", "arguments": {"scope": json.loads(sys.argv[3])}}}\n'
            'relay.stdin.write(json.dumps(req).encode() + b"\\n")\n'
            'relay.stdin.flush()\n'
            'reply = json.loads(relay.stdout.readline())\n'
            'assert not reply["result"].get("isError")\n'
            'relay.stdin.close()\n'
            'relay.stdout.close()\n'
            'sys.exit(7)\n'
        )

        with ThreadingHTTPServer(('127.0.0.1', 0), Handler) as http_srv, socket.socket(socket.AF_UNIX) as listener:
            http_thread = threading.Thread(target=http_srv.serve_forever, daemon=True)
            http_thread.start()
            try:
                url = f'http://127.0.0.1:{http_srv.server_port}/mcp'
                sock_path = str(self.base / 'launch-close.rpc')
                listener.bind(sock_path)
                listener.listen(4)
                listener.settimeout(0.2)

                def bind(sid):
                    self.assertEqual(sid, scope['session_id'])
                    return scope, gateway.Honcho(url, 'launch-token', scope['workspace_id'])

                rc = launch.run_coordinator(
                    [sys.executable, '-c', coordinator_script, str(DIR / 'broker.py'), sock_path, json.dumps(scope)],
                    os.environ,
                    listener,
                    bind,
                )
                self.assertEqual(rc, 7)
                self.assertEqual(active, set())
                self.assertEqual(deletes, ['launch-sess-1'])
                self.assertEqual(events, ['initialized', 'deleted'])
            finally:
                http_srv.shutdown()
                http_thread.join(timeout=2)

    def test_run_coordinator_bounds_stuck_relay_shutdown(self):
        import launch

        blocker = threading.Event()
        entered = threading.Event()

        def stuck_serve(*_args):
            entered.set()
            blocker.wait(5)

        try:
            with socket.socket(socket.AF_UNIX) as listener:
                with patch.object(launch, 'serve', side_effect=stuck_serve):
                    t0 = time.monotonic()
                    rc = launch.run_coordinator(
                        [sys.executable, '-c', 'import sys; sys.exit(5)'],
                        os.environ,
                        listener,
                        lambda _sid: None,
                        shutdown_timeout=0.15,
                    )
                    elapsed = time.monotonic() - t0
                self.assertEqual(rc, 5)
                self.assertTrue(entered.is_set())
                self.assertLess(elapsed, 1.0)
        finally:
            blocker.set()

        pid_file = self.base / 'stuck-relay.pid'
        child_script = (
            'import json, os, pathlib, socket, sys, time\n'
            'pathlib.Path(sys.argv[2]).write_text(str(os.getpid()))\n'
            'with socket.socket(socket.AF_UNIX) as conn:\n'
            '    conn.connect(sys.argv[1])\n'
            '    conn.sendall(b"test\\n")\n'
            '    conn.sendall((json.dumps({"id": 1, "method": "ping"}) + "\\n").encode())\n'
            '    line = b""\n'
            '    while not line.endswith(b"\\n"):\n'
            '        chunk = conn.recv(1024)\n'
            '        if not chunk:\n'
            '            break\n'
            '        line += chunk\n'
            '    sys.stdout.write("ready\\n")\n'
            '    sys.stdout.flush()\n'
            '    time.sleep(10)\n'
        )
        coordinator_script = (
            'import subprocess, sys\n'
            'child = subprocess.Popen([sys.executable, "-c", sys.argv[1], sys.argv[2], sys.argv[3]], stdout=subprocess.PIPE)\n'
            'assert child.stdout.readline() == b"ready\\n"\n'
            'sys.exit(9)\n'
        )
        scope = dict(workspace_id='w', peer_id='pi-coordinator', target_peer_id='kube-lvl47', session_id='test', task='test')
        sock_path = str(self.base / 'stuck.rpc')
        try:
            with socket.socket(socket.AF_UNIX) as listener:
                listener.bind(sock_path)
                listener.listen(4)
                listener.settimeout(0.1)
                t0 = time.monotonic()
                rc = launch.run_coordinator(
                    [sys.executable, '-c', coordinator_script, child_script, sock_path, str(pid_file)],
                    os.environ,
                    listener,
                    lambda _sid: (scope, object()),
                    shutdown_timeout=0.2,
                )
                elapsed = time.monotonic() - t0
            self.assertEqual(rc, 9)
            self.assertLess(elapsed, 1.0)
        finally:
            if pid_file.exists():
                try:
                    os.kill(int(pid_file.read_text()), signal.SIGKILL)
                except (OSError, ValueError):
                    pass


class RecallScopesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name).resolve()

    def load_recall_scopes(self):
        spec = importlib.util.spec_from_file_location('recall_scopes', DIR / 'recall-scopes.py')
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def init_repo(self, rel, origin=None, *, commit=False):
        repo = self.home / rel
        repo.mkdir(parents=True, exist_ok=True)
        subprocess.run(['/usr/bin/git', 'init', str(repo)], check=True, capture_output=True)
        if origin is not None:
            subprocess.run(
                ['/usr/bin/git', '-C', str(repo), 'remote', 'add', 'origin', origin],
                check=True,
                capture_output=True,
            )
        if commit:
            subprocess.run(
                [
                    '/usr/bin/git',
                    '-C',
                    str(repo),
                    '-c',
                    'user.name=Test',
                    '-c',
                    'user.email=test@example.com',
                    'commit',
                    '--allow-empty',
                    '-m',
                    'init',
                ],
                check=True,
                capture_output=True,
            )
        return repo

    def run_cli(self, cwd):
        proc = subprocess.run(
            [sys.executable, '-I', str(DIR / 'recall-scopes.py')],
            cwd=cwd,
            env={'HOME': str(self.home), 'PATH': '/usr/bin:/bin'},
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(proc.stdout)

    def test_identity_aliases_positive_cli_and_url_forms(self):
        recall_scopes = self.load_recall_scopes()
        cases = (
            ('code/purpleflow', 'nevalions/hermes-flow', 'hermes-flow'),
            ('code/portals/videooperator.su', 'nevalions/videooperator.su', 'videooperator-su'),
            ('code/portals/ochistka-musoroprovoda.ru', 'nevalions/ochistka-musoroprovoda.ru', 'ochistka-musoroprovoda-ru'),
            ('code/portals/portal-contact', 'nevalions/portal-contact', 'portal-contact'),
        )
        templates = (
            'ssh://git@git.butakov.su:2222/{path}.git',
            'ssh://git@git.butakov.su:2222/{path}',
            'ssh://git.butakov.su:2222/{path}.git',
            'ssh://git.butakov.su:2222/{path}',
            'git@git.butakov.su:{path}.git',
            'git@git.butakov.su:{path}',
            'git.butakov.su:{path}.git',
            'git.butakov.su:{path}',
            'https://git.butakov.su/{path}.git',
            'https://git.butakov.su/{path}',
        )
        for rel, repo_path, peer in cases:
            repo = self.init_repo(rel, templates[0].format(path=repo_path))
            self.assertEqual(self.run_cli(repo), [peer, 'code-wide'], rel)
            with patch.object(recall_scopes, 'HOME', self.home):
                for template in templates:
                    url = template.format(path=repo_path)
                    subprocess.run(
                        ['/usr/bin/git', '-C', str(repo), 'remote', 'set-url', 'origin', url],
                        check=True,
                        capture_output=True,
                    )
                    self.assertEqual(recall_scopes.targets(repo / '.git'), [peer, 'code-wide'], (rel, url))

    def test_identity_aliases_fail_closed_on_invalid_missing_ambiguous_or_rewrites(self):
        recall_scopes = self.load_recall_scopes()
        repo = self.init_repo('code/purpleflow')
        self.assertEqual(self.run_cli(repo), [])

        bad_origins = (
            'ssh://git@github.com:2222/nevalions/hermes-flow.git',
            'ssh://git@git.butakov.su.evil.test:2222/nevalions/hermes-flow.git',
            'https://git.butakov.su.evil.test/nevalions/hermes-flow.git',
            'ssh://git@git.butakov.su:2222/other/hermes-flow.git',
            'ssh://git@git.butakov.su:2222/nevalions/purpleflow.git',
            'ssh://git@git.butakov.su:2222/nevalions/hermes-flow/extra.git',
            'https://git.butakov.su/nevalions/hermes-flow.git/',
            'ssh://git@git.butakov.su/nevalions/hermes-flow.git',
            'ssh://git@git.butakov.su:22/nevalions/hermes-flow.git',
            'http://git.butakov.su/nevalions/hermes-flow.git',
            'https://git.butakov.su:8443/nevalions/hermes-flow.git',
            'https://user:pass@git.butakov.su/nevalions/hermes-flow.git',
            'https://token@git.butakov.su/nevalions/hermes-flow.git',
            'https://git@git.butakov.su/nevalions/hermes-flow.git',
            'ssh://other@git.butakov.su:2222/nevalions/hermes-flow.git',
            'ssh://git:pass@git.butakov.su:2222/nevalions/hermes-flow.git',
            'other@git.butakov.su:nevalions/hermes-flow.git',
            'https://git.butakov.su/nevalions/hermes-flow.git?foo=1',
            'https://git.butakov.su/nevalions/hermes-flow.git#frag',
            'https://git.butakov.su/nevalions/hermes-flow.git\n',
            'https://git.butakov.su/nevalions/hermes-flow.git' + 'a' * 256,
            '',
        )
        config = repo / '.git/config'
        with patch.object(recall_scopes, 'HOME', self.home):
            for url in bad_origins:
                subprocess.run(
                    ['/usr/bin/git', 'config', '--file', str(config), 'remote.origin.url', url],
                    check=True,
                    capture_output=True,
                )
                self.assertEqual(recall_scopes.targets(repo / '.git'), [], repr(url))

        config.write_text(
            '[remote "origin"]\n\turl = "https://git.butakov.su/nevalions/hermes-flow.git\\n"\n',
            encoding='utf-8',
        )
        self.assertEqual(self.run_cli(repo), [])

        config.write_text(
            '[remote "origin"]\n'
            '\turl = https://git.butakov.su/nevalions/hermes-flow.git\n'
            '\turl = ssh://git@git.butakov.su:2222/nevalions/hermes-flow.git\n',
            encoding='utf-8',
        )
        self.assertEqual(self.run_cli(repo), [])

        included = self.home / 'included.gitconfig'
        included.write_text('[remote "origin"]\n\turl = https://git.butakov.su/nevalions/hermes-flow.git\n', encoding='utf-8')
        config.write_text(f'[include]\n\tpath = {included}\n', encoding='utf-8')
        self.assertEqual(self.run_cli(repo), [])

        (self.home / '.gitconfig').write_text(
            '[url "https://git.butakov.su/nevalions/hermes-flow.git"]\n\tinsteadOf = alias:\n',
            encoding='utf-8',
        )
        config.write_text('[remote "origin"]\n\turl = alias:\n', encoding='utf-8')
        self.assertEqual(self.run_cli(repo), [])

        portal = self.init_repo('code/portals/portal-contact', 'ssh://git@git.butakov.su:2222/nevalions/videooperator.su.git')
        self.assertEqual(self.run_cli(portal), [])

    def test_linked_worktree_cli_uses_common_config(self):
        repo = self.init_repo(
            'code/purpleflow',
            'ssh://git@git.butakov.su:2222/nevalions/hermes-flow.git',
            commit=True,
        )
        wt = self.home / 'worktrees/purpleflow-wt'
        wt.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ['/usr/bin/git', '-C', str(repo), 'worktree', 'add', str(wt), '-b', 'wt-test'],
            check=True,
            capture_output=True,
        )
        self.assertEqual(self.run_cli(wt), ['hermes-flow', 'code-wide'])

        subprocess.run(
            ['/usr/bin/git', '-C', str(repo), 'remote', 'set-url', 'origin', 'https://git.butakov.su/nevalions/purpleflow.git'],
            check=True,
            capture_output=True,
        )
        self.assertEqual(self.run_cli(wt), [])

    def test_unrelated_and_legacy_routes_unchanged(self):
        expected = (
            ('code/hermes-flow', ['hermes-flow', 'code-wide']),
            ('code/portal-contact', ['portal-contact', 'code-wide']),
            ('code/stoma science', ['stoma_science', 'code-wide']),
            ('code/ochistka-musoroprovoda.ru', ['ochistka-musoroprovoda-ru', 'code-wide']),
            ('code/videooperator.su', ['videooperator-su', 'code-wide']),
            ('code/portals/videosemka.su', ['portals--videosemka-su', 'code-wide']),
            ('code/portals/other', ['portals--other', 'code-wide']),
            ('code/kube-lvl47', ['kube-lvl47', 'project-cluster-infra', 'code-wide']),
            ('ansible', ['ansible', 'project-cluster-infra', 'code-wide']),
            ('dotfiles', ['dotfiles', 'code-wide']),
            ('code/videooperator-su', []),
            ('code/ochistka-musoroprovoda-ru', []),
            ('code/portals--videosemka-su', []),
            ('code/linroot', []),
            ('code/project-demo', []),
            ('code/foo--bar', []),
        )
        for rel, want in expected:
            repo = self.init_repo(rel)
            self.assertEqual(self.run_cli(repo), want, rel)
