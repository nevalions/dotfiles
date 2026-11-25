import importlib.util
import json
import os
from pathlib import Path
import pty
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import threading
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
    'export default function (pi: ExtensionAPI) {\n'
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
