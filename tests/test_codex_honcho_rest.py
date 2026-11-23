import json
from io import BytesIO
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'codex/.codex/honcho'))
from gateway import Denied, dispatch
from rest import RestHoncho, resolve_connection


class Fixture(RestHoncho):
    def __init__(self):
        super().__init__('http://127.0.0.1:18000', 'fixture', 'hermes-personal')
        self.calls = []
        self.session = None
        self.missing = False
        self.fail_append = False

    def request(self, method, path, body=None):
        self.calls.append((method, path, body))
        if path.startswith('/peers/list'):
            return {'items': [] if self.missing else [{'id': body['filters']['id']}]}
        if path.startswith('/sessions/list'):
            return {'items': [self.session] if self.session else []}
        if path == '/sessions':
            self.session = {'id': body['id'], 'workspace_id': self.workspace, 'metadata': body['metadata']}
            return self.session
        if path == '/conclusions' and self.fail_append:
            raise URLError('ambiguous append response')
        return {'items': []}


class RestTests(unittest.TestCase):
    def setUp(self):
        self.remote = Fixture()
        self.scope = dict(workspace_id='hermes-personal', peer_id='pi-coordinator',
                          target_peer_id='dotfiles', session_id='task-session', task='task-id')
        self.bound = {k: v for k, v in self.scope.items() if k != 'task'}

    def test_read_routes_and_filters_never_create_sessions(self):
        self.remote.call('get_peer_card', self.bound)
        self.remote.call('chat', {**self.bound, 'query': 'Prior decisions?'})
        self.remote.call('list_conclusions', self.bound)
        self.assertEqual(self.remote.calls[0][:2], ('GET', '/peers/pi-coordinator/card?target=dotfiles'))
        self.assertEqual(self.remote.calls[1][2], {'target': 'dotfiles', 'query': 'Prior decisions?', 'reasoning_level': 'low', 'stream': False})
        self.assertEqual(self.remote.calls[2][2]['filters'], {'observer_id': 'pi-coordinator', 'observed_id': 'dotfiles', 'session_id': 'task-session'})
        self.assertIsNone(self.remote.session)

    def test_private_pi_key_and_endpoint_precede_vault(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            path.write_text(json.dumps({'environmentUrl': 'http://127.0.0.1:18000', 'hosts': {'pi': {
                'workspace': 'hermes-personal', 'apiKey': 'fixture-key'}}}))
            with patch('rest.subprocess.check_output') as vault:
                self.assertEqual(resolve_connection(env={}, config_path=path),
                                 ('http://127.0.0.1:18000', 'fixture-key', 'hermes-personal'))
                vault.assert_not_called()

    def test_publish_preparation_is_exact_metadata_only_and_idempotent(self):
        self.remote.prepare_session(self.scope)
        self.remote.prepare_session(self.scope)
        creates = [body for _, path, body in self.remote.calls if path == '/sessions']
        self.assertEqual(len(creates), 1)
        self.assertEqual(set(creates[0]), {'id', 'metadata', 'peers'})
        self.assertEqual(creates[0]['id'], self.scope['session_id'])
        self.assertEqual(creates[0]['metadata']['codex_task'], self.scope['task'])
        self.assertEqual(creates[0]['peers'], {peer: {'observe_me': False, 'observe_others': False}
                                             for peer in ['pi-coordinator', 'dotfiles']})
        self.remote.session['metadata']['codex_task'] = 'another-task'
        with self.assertRaises(Denied):
            self.remote.prepare_session(self.scope)
        self.remote.missing = True
        with self.assertRaises(Denied):
            self.remote.prepare_session({**self.scope, 'session_id': 'new-session'})
        self.assertEqual(len([1 for _, path, _ in self.remote.calls if path == '/sessions']), 1)
        self.assertFalse(any(path == '/peers' for _, path, _ in self.remote.calls))

    def test_http_denial_does_not_retry_or_switch_credentials_or_transport(self):
        remote = RestHoncho('http://127.0.0.1:18000', 'fixture', 'hermes-personal')
        with patch.object(remote.opener, 'open', side_effect=HTTPError('fixture', 403, '', {}, None)) as request:
            with self.assertRaisesRegex(Denied, 'HTTP 403'):
                remote.call('get_peer_card', self.bound)
            self.assertEqual(request.call_count, 1)

    def validation_failure(self, body, status=422):
        remote = RestHoncho('http://127.0.0.1:18000', 'fixture', 'hermes-personal')
        stream = BytesIO(body)
        error = HTTPError('fixture', status, '', {}, stream)
        try:
            with patch.object(remote.opener, 'open', side_effect=error) as request:
                with self.assertRaises(Denied) as caught:
                    remote.request('POST', '/conclusions', {'conclusions': []})
                self.assertEqual(request.call_count, 1)
            return str(caught.exception), stream.tell()
        finally:
            error.close()

    def test_embedding_validation_reports_counts_without_private_details(self):
        body = json.dumps({'detail': [{'loc': ['body', 'conclusions', 0], 'type': 'value_error',
            'msg': 'Value error, Content exceeds maximum embedding token limit of 512 (got 531 tokens)',
            'input': 'SECRET-NOTE', 'ctx': {'error': 'SECRET-CONTEXT'}}]}).encode()
        message, _ = self.validation_failure(body)
        self.assertIn('body.conclusions.0 (value_error): embedding token limit 512, actual 531 tokens', message)
        self.assertNotIn('SECRET', message)

    def test_validation_rejects_reflected_content_and_malformed_bodies(self):
        for detail in (
            [{'loc': ['body', 'conclusions', 0, 'content'], 'type': 'string_type', 'msg': 'SECRET-NOTE'}],
            [{'loc': ['body', 'SECRET-FIELD'], 'type': 'value_error', 'msg': 'SECRET-NOTE'}],
            [{'loc': ['body'], 'type': 'SECRET-TYPE', 'msg': 'SECRET-NOTE'}],
            [{'loc': ['body'], 'type': [], 'msg': 'SECRET-NOTE'}],
            'SECRET-NOTE',
        ):
            with self.subTest(detail=detail):
                message, _ = self.validation_failure(json.dumps({'detail': detail}).encode())
                self.assertNotIn('SECRET', message)
        message, _ = self.validation_failure(b'not json SECRET-NOTE')
        self.assertNotIn('Validation:', message)
        message, consumed = self.validation_failure(b' ' * 65537)
        self.assertNotIn('Validation:', message)
        self.assertEqual(consumed, 65536)

    def test_non_validation_error_does_not_read_or_expose_body(self):
        message, consumed = self.validation_failure(b'SECRET-NOTE', status=403)
        self.assertEqual(message, 'Honcho REST request denied or failed (HTTP 403); no credential or transport fallback was attempted.')
        self.assertEqual(consumed, 0)

    def test_ambiguous_append_is_not_retried_and_readback_is_read_only(self):
        self.remote.fail_append = True
        request = {'method': 'tools/call', 'params': {'name': 'publish_verified', 'arguments': {
            'scope': self.scope, 'candidate': 'source', 'checks': 'passed',
            'verification': 'independent verification', 'conclusion': 'synthetic test'}}}
        self.assertTrue(dispatch(request, self.scope, self.remote)['isError'])
        self.assertEqual(len([1 for _, path, _ in self.remote.calls if path == '/conclusions']), 1)
        dispatch({'method': 'tools/call', 'params': {'name': 'readback', 'arguments': {'scope': self.scope}}}, self.scope, self.remote)
        self.assertEqual(len([1 for _, path, _ in self.remote.calls if path == '/conclusions']), 1)
        self.assertEqual(self.remote.calls[-1][2]['filters']['session_id'], self.scope['session_id'])


if __name__ == '__main__':
    unittest.main()
