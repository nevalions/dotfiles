"""Coordinator-only, session-lifetime relay. No upstream key is passed to Pi."""
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import threading
from urllib.request import ProxyHandler, Request, build_opener

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gateway import Denied, Honcho, LIMIT, NoRedirect, TAILNET_URL, dispatch, require_tailnet_route


VAULT_ITEM = 'Honcho Codex'


def upstream(scope):
    require_tailnet_route()
    try:
        raw = subprocess.check_output(['/usr/bin/rbw', 'get', VAULT_ITEM], stdin=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL, timeout=8).decode().strip()
    except subprocess.SubprocessError:
        raise Denied(f'Publisher credential unavailable in rbw: {VAULT_ITEM}') from None
    if not raw or not raw.isascii() or not raw.isprintable() or ' ' in raw:
        raise Denied('Invalid publisher credential')
    base = 'http://100.64.0.16:18000/v3/workspaces/' + scope['workspace_id']
    client = build_opener(ProxyHandler({}), NoRedirect())
    def request(path, body=None):
        require_tailnet_route()
        req = Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                      headers={'Authorization': 'Bearer ' + raw, 'Content-Type': 'application/json'})
        with client.open(req, timeout=8) as response:
            return json.loads(response.read(LIMIT))
    missing = {scope['peer_id'], scope['target_peer_id']}
    page = 1
    while missing:
        peers = request(f'/peers/list?page={page}&size=100', {})
        missing.difference_update(p['id'] for p in peers['items'])
        if missing and page >= peers['pages']:
            raise Denied('Unconfirmed peer')
        page += 1
    session = request('/sessions', {'id': scope['session_id'], 'peers': {p: {} for p in (scope['peer_id'], scope['target_peer_id'])}})
    if not isinstance(session, dict) or session.get('id') != scope['session_id']:
        raise Denied('Unconfirmed session')
    return Honcho(TAILNET_URL, raw, scope['workspace_id'], tailnet=True)


def parent(pid):
    return int(Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[1])


def serve(listener, coordinator, bind):
    while coordinator.poll() is None:
        try:
            conn, _ = listener.accept()
        except socket.timeout:
            continue
        except OSError:
            return
        with conn:
            remote = None
            try:
                pid, uid, _ = struct.unpack('3i', conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                if uid != os.getuid() or parent(pid) != coordinator.pid:
                    continue
                with conn.makefile('rwb', buffering=0) as stream:
                    header = stream.readline(130)
                    if not header.endswith(b'\n'):
                        continue
                    scope, remote = bind(header[:-1].decode('ascii'))
                    while line := stream.readline(LIMIT + 1):
                        if len(line) > LIMIT:
                            break
                        req = json.loads(line)
                        if not isinstance(req, dict) or 'id' not in req:
                            continue
                        result = dispatch(req, scope, remote)
                        reply = {'jsonrpc': '2.0', 'id': req['id']}
                        if result is None:
                            reply['error'] = {'code': -32601, 'message': 'Method not found'}
                        else:
                            reply['result'] = result
                        stream.write(json.dumps(reply).encode() + b'\n')
            except (Denied, OSError, ValueError, TypeError, KeyError, AttributeError):
                continue
            finally:
                if remote is not None:
                    close_remote = getattr(remote, 'close', None)
                    if callable(close_remote):
                        try:
                            close_remote()
                        except Exception:
                            pass


def relay(path, sid):
    with socket.socket(socket.AF_UNIX) as conn:
        conn.connect(path)
        conn.sendall(sid.encode('ascii') + b'\n')
        def send():
            try:
                for line in sys.stdin.buffer:
                    conn.sendall(line)
                conn.shutdown(socket.SHUT_WR)
            except OSError:
                pass
        threading.Thread(target=send, daemon=True).start()
        while chunk := conn.recv(65536):
            sys.stdout.buffer.write(chunk)
            sys.stdout.buffer.flush()


if __name__ == '__main__':
    relay(*sys.argv[1:])
