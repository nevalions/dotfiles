"""Local parent-thread grants, selected by Codex-authored tool-call metadata."""
import json
import os
from pathlib import Path
import stat
import tempfile

from gateway import Denied, ID, private_text
from recall_scopes import HOME, targets

DIRECTORY = Path.home() / '.codex/honcho-grants'


def directory():
    DIRECTORY.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = DIRECTORY.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise Denied('Automatic grant directory must be owner-only and not a symlink.')
    return DIRECTORY


def route(common):
    common = Path(common).resolve()
    root = common.parent
    if root != HOME / 'ansible' and HOME / 'code' not in root.parents:
        return None
    peers = targets(common)
    return peers[0] if peers else None


def register(event, common):
    if event.get('hook_event_name') != 'SessionStart' or event.get('source') not in {'startup', 'resume', 'compact', 'clear'}:
        return None
    sid = event.get('session_id')
    if not isinstance(sid, str) or not ID.fullmatch(sid):
        return None
    if event['source'] != 'startup':
        try:
            resolve({'params': {'_meta': {'threadId': sid}}})
        except Denied:
            return None
    target = route(common)
    if not target:
        (directory() / (sid + '.json')).unlink(missing_ok=True)
        return None
    scope = dict(workspace_id='hermes-personal', peer_id='pi-coordinator',
                 target_peer_id=target, session_id=sid, task=sid)
    payload = dict(scope=scope, common=str(Path(common).resolve()))
    dest = directory() / (sid + '.json')
    fd, tmp = tempfile.mkstemp(dir=dest.parent, prefix='.grant-')
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(payload, stream)
        os.replace(tmp, dest)
    finally:
        Path(tmp).unlink(missing_ok=True)
    return scope


def resolve(request):
    meta = request.get('params', {}).get('_meta', {})
    sid = meta.get('threadId') if isinstance(meta, dict) else None
    if not isinstance(sid, str) or not ID.fullmatch(sid):
        raise Denied('Automatic publishing requires native Codex thread metadata.')
    try:
        data = json.loads(private_text(str(directory() / (sid + '.json'))))
        scope = data['scope']
        if (set(data) != {'scope', 'common'} or scope != dict(workspace_id='hermes-personal',
                peer_id='pi-coordinator', target_peer_id=route(data['common']), session_id=sid, task=sid)
                or not scope['target_peer_id']):
            raise ValueError('invalid automatic scope')
        return scope
    except (OSError, ValueError, KeyError, TypeError):
        raise Denied('No matching parent-thread repository grant. Recall only.') from None
