import json
from pathlib import Path
import sys
import tempfile
import unittest

MODULE = Path(__file__).resolve().parents[1] / 'codex/.codex/honcho'
sys.path.insert(0, str(MODULE))
import server


class Remote:
    def __init__(self):
        self.calls = []

    def prepare_session(self, scope):
        self.prepared_scope = scope

    def call(self, name, arguments):
        self.calls.append((name, arguments))
        return server.content('fixture')


class HonchoTest(unittest.TestCase):
    def setUp(self):
        self.remote = Remote()
        self.scope = dict(workspace_id=server.WORKSPACE, peer_id=server.OBSERVER,
                          target_peer_id='kube-lvl47', session_id='probe', task='probe')

    def request(self, name, args, scope=None):
        return server.respond({'method': 'tools/call', 'params': {'name': name, 'arguments': args}}, scope, self.remote)

    def test_install_preserves_existing_environment_and_forwards_rbw_runtime(self):
        import importlib.util
        path = MODULE.parents[1] / 'honcho/install.py'
        spec = importlib.util.spec_from_file_location('honcho_install', path)
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
        existing = ['CUSTOM_SETTING', {'name': 'OTHER_SETTING', 'source': 'local'}]
        result = installer.runtime_env_vars(existing)
        self.assertEqual(result[:2], existing)
        self.assertIn('XDG_RUNTIME_DIR', result)
        self.assertEqual(existing, ['CUSTOM_SETTING', {'name': 'OTHER_SETTING', 'source': 'local'}])
        self.assertEqual(installer.runtime_env_vars(result), result)
        self.assertIn('XDG_RUNTIME_DIR', installer.runtime_env_vars(None))

    def test_hook_setup_preserves_approved_matcher_and_is_idempotent(self):
        import importlib.util
        path = MODULE.parents[1] / 'honcho/install.py'
        spec = importlib.util.spec_from_file_location('honcho_hook_install', path)
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
        own = {'type': 'command', 'command': 'codex-honcho-mcp --session-start'}
        other = {'type': 'command', 'command': 'unrelated-command'}
        hooks = {'hooks': {'SessionStart': [{'matcher': 'startup|resume|compact', 'hooks': [own, other]}]}}
        installer.configure_hooks(hooks)
        groups = hooks['hooks']['SessionStart']
        self.assertEqual(groups[0], {'matcher': 'startup|resume|compact', 'hooks': [own, other]})
        installer.configure_hooks(hooks)
        self.assertEqual(len(groups), 1)

    def test_default_connection_is_read_only(self):
        tools = server.respond({'method': 'tools/list'}, None, self.remote)['tools']
        self.assertEqual({t['name'] for t in tools}, {'recall', 'peer_card', 'list_conclusions'})
        self.assertTrue(all(t['annotations']['readOnlyHint'] for t in tools))
        for name in ('publish_verified', 'create_peer', 'delete_conclusion', 'create_conclusions'):
            self.assertTrue(self.request(name, {})['isError'])
        self.assertEqual(self.remote.calls, [])

    def test_recall_binds_workspace_and_observer(self):
        self.request('recall', {'target_peer_id': 'linroot', 'query': 'Editor preferences'})
        self.assertEqual(self.remote.calls, [('chat', dict(workspace_id=server.WORKSPACE,
                         peer_id=server.OBSERVER, target_peer_id='linroot', query='Editor preferences', reasoning_level='low'))])
        self.assertTrue(self.request('recall', {'target_peer_id': 'linroot', 'query': 'x', 'workspace_id': 'other'})['isError'])
        self.assertEqual(len(self.remote.calls), 1)

    def test_scope_cannot_be_widened(self):
        args = dict(scope={**self.scope, 'target_peer_id': 'linroot'}, candidate='revision',
                    checks='passed', verification='independent read', conclusion='probe')
        self.assertTrue(self.request('publish_verified', args, self.scope)['isError'])
        self.assertEqual(self.remote.calls, [])

    def test_verified_append_has_provenance(self):
        args = dict(scope=self.scope, candidate='revision', checks='passed',
                    verification='independent read', conclusion='probe')
        self.assertNotIn('isError', self.request('publish_verified', args, self.scope))
        name, bound = self.remote.calls[0]
        self.assertEqual(name, 'create_conclusions')
        self.assertEqual(bound['session_id'], 'probe')
        self.assertEqual(bound['target_peer_id'], 'kube-lvl47')
        self.assertIn('Candidate/source: revision', bound['conclusions'][0])
        self.assertEqual(self.remote.prepared_scope, self.scope)

    def test_repository_routes_follow_home_and_git_common_directory(self):
        from unittest.mock import patch
        import recall_scopes
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            with patch.object(recall_scopes, 'HOME', home):
                self.assertEqual(recall_scopes.targets(home / 'code/kube-lvl47/.git'),
                                 ['kube-lvl47', 'project-cluster-infra', 'code-wide'])
                self.assertEqual(recall_scopes.targets(home / 'dotfiles/.git'), ['dotfiles', 'code-wide'])
                self.assertEqual(recall_scopes.targets(home / 'unmapped/.git'), [])

    def test_peer_aliases_match_pi_and_automatic_grants(self):
        import importlib.util
        from unittest.mock import patch
        import automatic
        import recall_scopes
        path = MODULE.parents[2] / 'pi/.pi/agent/honcho-cli/recall-scopes.py'
        spec = importlib.util.spec_from_file_location('pi_recall_scopes', path)
        pi_routes = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pi_routes)
        aliases = {
            'ochistka-musoroprovoda.ru': 'ochistka-musoroprovoda-ru',
            'videooperator.su': 'videooperator-su',
            'portals/videosemka.su': 'portals--videosemka-su',
        }
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            with patch.object(recall_scopes, 'HOME', home), patch.object(pi_routes, 'HOME', home), patch.object(automatic, 'HOME', home):
                for repo, peer in aliases.items():
                    common = home / 'code' / repo / '.git'
                    expected = [peer, 'code-wide']
                    self.assertEqual(recall_scopes.targets(common), expected)
                    self.assertEqual(pi_routes.targets(common), expected)
                    self.assertEqual(automatic.route(common), peer)
                self.assertEqual(pi_routes.targets(home / 'code/statsboard/statsboards-backend/.git'),
                                 ['statsboard--statsboards-backend', 'project-statsboard', 'code-wide'])
                self.assertEqual(pi_routes.targets(home / 'code/portals--videosemka.su/.git'), [])

    def test_grant_requires_private_file_and_fixed_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'grant.json'
            path.write_text(json.dumps(self.scope))
            path.chmod(0o600)
            self.assertEqual(server.grant(path), self.scope)
            path.chmod(0o644)
            with self.assertRaises(ValueError):
                server.grant(path)
            path.chmod(0o600)
            path.write_text(json.dumps({**self.scope, 'workspace_id': 'other'}))
            with self.assertRaises(ValueError):
                server.grant(path)

class AutomaticGrantTest(unittest.TestCase):
    def test_parent_only_native_metadata_and_exact_worktree_route(self):
        from unittest.mock import patch
        import automatic
        import recall_scopes
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            common = home / 'code/sample/.git'
            common.mkdir(parents=True)
            private = home / '.codex/honcho-grants'
            event = dict(hook_event_name='SessionStart', source='startup', session_id='parent')
            with patch.object(automatic, 'HOME', home), patch.object(recall_scopes, 'HOME', home), patch.object(automatic, 'DIRECTORY', private):
                for source in ('resume', 'compact', 'clear'):
                    self.assertIsNone(automatic.register({**event, 'source': source, 'session_id': 'child'}, common))
                scope = automatic.register(event, common)
                for source in ('resume', 'compact', 'clear'):
                    self.assertEqual(automatic.register({**event, 'source': source}, common), scope)
                self.assertEqual(scope['target_peer_id'], 'sample')
                req = dict(method='tools/call', params=dict(name='get_grant', arguments={}, _meta={'threadId': 'parent'}))
                self.assertEqual(automatic.resolve(req), scope)
                result = server.respond(req, None, Remote(), auto=True)
                self.assertNotIn('isError', result)
                req['params']['_meta']['threadId'] = 'worker'
                self.assertTrue(server.respond(req, None, Remote(), auto=True)['isError'])
                req['params'].pop('_meta')
                self.assertTrue(server.respond(req, None, Remote(), auto=True)['isError'])
                for kind in ('fork', 'unknown'):
                    self.assertIsNone(automatic.register({**event, 'source': kind, 'session_id': kind}, common))
                self.assertIsNone(automatic.register({**event, 'hook_event_name': 'SubagentStart'}, common))
                self.assertIsNone(automatic.register(event, home / 'dotfiles/.git'))
                self.assertFalse((private / 'parent.json').exists())
                self.assertEqual(automatic.register(event, home / 'ansible/.git')['target_peer_id'], 'ansible')
                private.chmod(0o755)
                with self.assertRaises(server.Denied):
                    automatic.resolve(req)

    def test_unsafe_grant_directory_and_symlink_grant_are_denied(self):
        from unittest.mock import patch
        import automatic
        import recall_scopes
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            private = home / 'grants'
            private.mkdir(mode=0o700)
            common = home / 'code/sample/.git'
            event = dict(hook_event_name='SessionStart', source='startup', session_id='parent')
            with patch.object(automatic, 'HOME', home), patch.object(recall_scopes, 'HOME', home), patch.object(automatic, 'DIRECTORY', private):
                automatic.register(event, common)
                grant = private / 'parent.json'
                saved = private / 'saved.json'
                grant.rename(saved)
                grant.symlink_to(saved)
                with self.assertRaises(server.Denied):
                    automatic.resolve({'params': {'_meta': {'threadId': 'parent'}}})
                grant.unlink()
            linked = home / 'linked'
            linked.symlink_to(private)
            with patch.object(automatic, 'DIRECTORY', linked):
                with self.assertRaises(server.Denied):
                    automatic.directory()


if __name__ == '__main__':
    unittest.main()
