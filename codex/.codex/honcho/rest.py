"""Small allowlisted Honcho v3 REST adapter using Pi's local API-key settings."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from urllib.error import HTTPError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import ProxyHandler, Request, build_opener

from gateway import Denied, ID, LIMIT, NoRedirect, content, require_tailnet_route

TAILNET_API = 'http://100.64.0.16:18000'
VALIDATION_LIMIT = 65536


def validation_detail(error):
    try:
        raw = error.read(VALIDATION_LIMIT)
        if len(raw) >= VALIDATION_LIMIT:
            return ''
        details = json.loads(raw).get('detail')
        if not isinstance(details, list):
            return ''
        fields = {'body', 'conclusions', 'content', 'observer_id', 'observed_id', 'session_id',
                  'id', 'metadata', 'peers', 'observe_me', 'observe_others', 'configuration'}
        types = {'value_error', 'missing', 'string_type', 'string_too_long', 'string_too_short',
                 'list_type', 'dict_type', 'bool_type', 'extra_forbidden', 'string_pattern_mismatch',
                 'too_long', 'too_short'}
        messages = []
        for item in details[:3]:
            if not isinstance(item, dict):
                continue
            loc, kind = item.get('loc'), item.get('type')
            if (not isinstance(loc, list) or not 1 <= len(loc) <= 8 or
                    any(not (isinstance(part, str) and part in fields or
                             type(part) is int and 0 <= part <= 100) for part in loc) or kind not in types):
                continue
            message = 'validation failed'
            match = re.fullmatch(r'(?:Value error, )?Content exceeds maximum embedding token limit of '
                                 r'([0-9]{1,9}) \(got ([0-9]{1,9}) tokens\)', str(item.get('msg', '')))
            if kind == 'value_error' and loc == ['body', 'conclusions', 0] and match:
                message = f'embedding token limit {match[1]}, actual {match[2]} tokens'
            messages.append(f'{".".join(map(str, loc))} ({kind}): {message}')
        return '; '.join(messages)
    except (OSError, ValueError, TypeError, AttributeError, RecursionError):
        return ''


def resolve_connection(env=None, config_path=None):
    env = os.environ if env is None else env
    path = Path(config_path or env.get('HONCHO_CONFIG_PATH') or Path.home() / '.honcho/config.json').expanduser()
    try:
        data = json.loads(path.read_text()) if path.exists() else {}
        pi = data.get('hosts', {}).get('pi', {})
        if not isinstance(data, dict) or not isinstance(pi, dict):
            raise ValueError('invalid config')
        def endpoint(block):
            legacy = block.get('endpoint', {})
            return (block.get('baseUrl') or block.get('environmentUrl') or
                    (legacy if isinstance(legacy, str) else legacy.get('baseUrl')))
        url = (env.get('HONCHO_BASE_URL') or env.get('HONCHO_URL') or env.get('HONCHO_ENDPOINT') or
               endpoint(pi) or endpoint(data) or TAILNET_API)
        workspace = env.get('HONCHO_WORKSPACE') or env.get('HONCHO_WORKSPACE_ID') or pi.get('workspace') or data.get('workspace') or 'hermes-personal'
        key = env.get('HONCHO_API_KEY') or pi.get('apiKey') or pi.get('auth', {}).get('apiKey')
        oauth = data.get('oauth') or data.get('auth', {}).get('oauth')
        if not key and oauth:
            raise Denied('This integration needs the existing Pi API key; OAuth refresh is not supported.')
        key = key or data.get('apiKey') or data.get('auth', {}).get('apiKey')
        if not key:
            rbw = shutil.which('rbw')
            if not rbw:
                raise Denied('No Pi API key configured and rbw is unavailable.')
            key = subprocess.check_output([rbw, 'get', 'Honcho Codex'], stdin=subprocess.DEVNULL,
                                          stderr=subprocess.DEVNULL, timeout=8).decode().strip()
        if not isinstance(key, str):
            raise ValueError('invalid key')
        key = re.sub(r'\$\{([^}]+)\}', lambda match: env.get(match[1], match[0]), key).strip()
        if not re.fullmatch(r'[!-~]{1,4096}', key) or '${' in key:
            raise ValueError('invalid key')
        if not isinstance(url, str) or not isinstance(workspace, str) or not ID.fullmatch(workspace):
            raise ValueError('invalid settings')
        return url.rstrip('/'), key, workspace
    except Denied:
        raise
    except (OSError, ValueError, TypeError, AttributeError, subprocess.SubprocessError):
        raise Denied('Cannot read Honcho connection settings; check the local Pi config or unlock rbw.') from None


class RestHoncho:
    def __init__(self, url, token, workspace):
        parsed = urlsplit(url)
        self.tailnet = url == TAILNET_API
        if (not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or
                not (parsed.scheme == 'https' or self.tailnet or
                     parsed.scheme == 'http' and parsed.hostname in {'localhost', '127.0.0.1', '::1'})):
            raise Denied('Honcho requires HTTPS, loopback HTTP, or the existing tailnet API route.')
        self.workspace = workspace
        self.base = url + '/v3/workspaces/' + quote(workspace, safe='')
        self.headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json', 'Accept': 'application/json'}
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def request(self, method, path, body=None):
        if self.tailnet:
            require_tailnet_route()
        req = Request(self.base + path, data=json.dumps(body).encode() if body is not None else None,
                      method=method, headers=self.headers)
        try:
            with self.opener.open(req, timeout=25) as response:
                raw = response.read(LIMIT + 1)
                if len(raw) > LIMIT:
                    raise ValueError('oversized response')
                return json.loads(raw)
        except HTTPError as exc:
            detail = validation_detail(exc) if exc.code == 422 else ''
            suffix = f' Validation: {detail}.' if detail else ''
            raise Denied(f'Honcho REST request denied or failed (HTTP {exc.code}); no credential or transport fallback was attempted.{suffix}') from None

    def binding(self, args):
        if args.get('workspace_id') != self.workspace:
            raise Denied('Outside the configured workspace.')
        for field in ('peer_id', 'target_peer_id'):
            if not isinstance(args.get(field), str) or not ID.fullmatch(args[field]):
                raise Denied('Invalid peer binding.')
        return args['peer_id'], args['target_peer_id']

    def prepare_session(self, scope):
        observer, target = self.binding(scope)
        sid = scope['session_id']
        if not isinstance(sid, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', sid):
            raise Denied('Invalid content session ID.')
        for peer in dict.fromkeys((observer, target)):
            found = self.request('POST', '/peers/list?page=1&size=1', {'filters': {'id': peer}})
            if not any(item.get('id') == peer for item in found.get('items', [])):
                raise Denied('The granted peer does not exist. No peers were created.')
        found = self.request('POST', '/sessions/list?page=1&size=1', {'filters': {'id': sid}})
        sessions = found.get('items', [])
        if sessions:
            session = sessions[0]
            if (session.get('id') != sid or session.get('workspace_id') != self.workspace or
                    session.get('metadata', {}).get('codex_task', scope['task']) != scope['task']):
                raise Denied('Existing session does not match the exact task grant.')
            return
        session = self.request('POST', '/sessions', {
            'id': sid, 'metadata': {'source': 'codex', 'codex_task': scope['task'], 'purpose': 'verified conclusions only'},
            'peers': {peer: {'observe_me': False, 'observe_others': False} for peer in (observer, target)}})
        if session.get('id') != sid or session.get('workspace_id') != self.workspace:
            raise Denied('Unconfirmed content session. Read back before retrying publication.')

    def call(self, name, args):
        observer, target = self.binding(args)
        peer = '/peers/' + quote(observer, safe='')
        if name == 'get_peer_card':
            value = self.request('GET', peer + '/card?' + urlencode({'target': target}))
        elif name == 'chat':
            value = self.request('POST', peer + '/chat', {'target': target, 'query': args['query'],
                                                         'reasoning_level': args.get('reasoning_level', 'low'), 'stream': False})
        elif name == 'list_conclusions':
            filters = {'observer_id': observer, 'observed_id': target}
            if args.get('session_id'):
                filters['session_id'] = args['session_id']
            value = self.request('POST', '/conclusions/list?page=1&size=10', {'filters': filters})
        elif name == 'create_conclusions':
            if len(args['conclusions']) != 1 or not args.get('session_id'):
                raise Denied('Only one exact-session conclusion is allowed.')
            value = self.request('POST', '/conclusions', {'conclusions': [{
                'content': args['conclusions'][0], 'observer_id': observer,
                'observed_id': target, 'session_id': args['session_id']}]})
        else:
            raise Denied('REST operation not allowed.')
        return content(json.dumps(value))
