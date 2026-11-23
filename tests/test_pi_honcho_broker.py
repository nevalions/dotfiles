import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import unittest

DIR = Path(__file__).resolve().parents[1] / 'pi/.pi/agent/honcho-cli'
sys.path.insert(0, str(DIR))
import broker


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
