#!/usr/bin/python3 -I
"""Top-level interactive launcher; the publisher is never globally registered."""
import importlib.util
import json
import os
from pathlib import Path
import re
import socket
import stat
import subprocess
import threading
import sys
import tempfile

AGENT = Path.home() / '.pi/agent'
DIR = AGENT / 'honcho-cli'
sys.path.insert(0, str(DIR))
from gateway import Denied
sys.path.insert(0, str(Path(__file__).resolve().parent))
from broker import serve, upstream

SPACE = 'hermes-personal'
OBSERVER = 'pi-coordinator'
TEAM = Path(__file__).resolve().parent.parent / 'team/workflow.md'
VERSION_RE = re.compile(r'[0-9A-Za-z._+-]+', re.ASCII)
MAX_VERSION_BYTES = 256
MAX_CACHE_BYTES = 2 * 1024 * 1024


def _read_regular_bytes(path, max_bytes, *, follow_symlinks=False):
    flags = os.O_RDONLY | os.O_NONBLOCK
    if not follow_symlinks:
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > max_bytes:
            raise ValueError('expected bounded regular file')
        data = stream.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError('file exceeds size limit')
    return data


def _read_version(path):
    raw = _read_regular_bytes(path, MAX_VERSION_BYTES, follow_symlinks=True)
    if b'\n' not in raw:
        return None
    version = raw.split(b'\n', 1)[0].decode('ascii')
    if version in ('', '.', '..') or not VERSION_RE.fullmatch(version):
        return None
    return version


def _load_prepare_subagent(path):
    spec = importlib.util.spec_from_file_location('prepare_subagent', path)
    if spec is None or spec.loader is None:
        raise ImportError(f'Cannot load {path}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def plain(args):
    args = list(args)
    if args[-1:] in (['-r'], ['--resume'], ['-c'], ['--continue']):
        args = args[:-1]
    elif len(args) >= 2 and args[-2] in ('--session', '--session-id') and args[-1] and not args[-1].startswith('-'):
        args = args[:-2]
    if not args:
        return True
    if len(args) != 7 or args[0] != '--extension' or args[2] != '--extension' or args[4] != '--append-system-prompt' or args[6] != '--agy-team':
        return False
    _, subagent_arg, _, todo_arg, _, workflow_arg, _ = args
    try:
        version = _read_version(AGENT / 'install/current-version')
        if version is None:
            return False
        examples = AGENT / 'install/releases' / version / 'node_modules/@earendil-works/pi-coding-agent/examples/extensions'
        todo = examples / 'todo.ts'
        if todo_arg != str(todo) or not stat.S_ISREG(os.lstat(todo).st_mode):
            return False
        base_dir = Path(__file__).resolve().parent.parent
        bin_dir = base_dir / 'bin'
        team_dir = base_dir / 'team'
        pi_team = (AGENT / 'bin/pi-team').resolve(strict=True)
        if pi_team.parent != bin_dir or pi_team.name != 'pi-team':
            return False
        if workflow_arg != f'{pi_team.parent}/../team/workflow.md':
            return False
        workflow_file = team_dir / 'workflow.md'
        if team_dir.is_symlink() or not stat.S_ISREG(os.lstat(workflow_file).st_mode):
            return False
        prepare_subagent = _load_prepare_subagent(team_dir / 'prepare-subagent.py')
        dest, expected = prepare_subagent.render(examples / 'subagent/index.ts', AGENT / 'install/team-cache')
        if subagent_arg != str(dest) or len(expected) > MAX_CACHE_BYTES:
            return False
        return _read_regular_bytes(dest, len(expected), follow_symlinks=False) == expected
    except (OSError, ValueError, ImportError, SyntaxError, RuntimeError):
        return False


def choose(routes, selection):
    if not routes or routes[0] == 'dotfiles':
        return None
    if selection not in (None, routes[0]):
        raise Denied('Requested target is not the repository peer')
    return routes[0]


def prepare(directory):
    ext = directory / 'publisher.ts'
    config = dict(command='/usr/bin/python3', args=['-I', str(Path(__file__).resolve().with_name('broker.py')), str(directory / 'rpc')], exposure='deferred',
                  description='Inspect the exact grant, publish verified conclusions, and read them back.')
    ext.write_text('import { realpathSync } from "node:fs";\n'
                   'export default pi => pi.on("session_start", (_event, ctx) => {\n'
                   '  if (realpathSync(ctx.cwd) !== ' + json.dumps(str(Path.cwd().resolve())) + ') return;\n'
                   '  const id = ctx.sessionManager.getSessionId();\n'
                   '  if (!/^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$/.test(id)) return;\n'
                   '  const config = ' + json.dumps(config) + ';\n'
                   '  config.args.push(id); pi.registerMcpServer("honcho_publish", config);\n'
                   '});\n')
    return ext


def main():
    args = sys.argv[1:]
    original = str(AGENT / 'bin/pi.managed')
    nested = any(k in os.environ for k in ('PI_HONCHO_NESTED', 'PI_HONCHO_PUBLISH_GRANT', 'PI_OFFLINE'))
    env = dict(os.environ, PI_HONCHO_NESTED='1')
    if not nested and sys.stdin.isatty() and sys.stdout.isatty() and plain(args):
        old = os.umask(0o077)
        try:
            raw = subprocess.check_output(['/usr/bin/python3', '-I', str(DIR / 'recall-scopes.py')], timeout=4)
            routes = json.loads(raw)
            target = choose(routes, os.getenv('PI_HONCHO_TARGET'))
            if target:
                if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}', target):
                    raise ValueError('invalid target')
                with tempfile.TemporaryDirectory(dir=f'/run/user/{os.getuid()}', prefix='pi-memory-') as tmp:
                    def bind(sid):
                        if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}', sid):
                            raise ValueError('invalid session')
                        scope = dict(workspace_id=SPACE, peer_id=OBSERVER, target_peer_id=target, session_id=sid, task=sid)
                        return scope, upstream(scope)
                    ext = prepare(Path(tmp))
                    with socket.socket(socket.AF_UNIX) as listener:
                        listener.bind(str(Path(tmp) / 'rpc'))
                        listener.listen(4)
                        listener.settimeout(1)
                        os.umask(old)
                        with subprocess.Popen([original, *args, '--extension', str(ext)], env=env) as proc:
                            threading.Thread(target=serve, args=(listener, proc, bind), daemon=True).start()
                            print(f'Honcho: scoped publisher for {SPACE}/{target}.', flush=True)
                            return proc.wait()
        except (Denied, OSError, ValueError, subprocess.SubprocessError) as exc:
            reason = str(exc) if isinstance(exc, Denied) else type(exc).__name__
            print(f'Honcho: setup failed ({reason}); recall only.', file=sys.stderr)
        finally:
            os.umask(old)
    os.execve(original, [original, *args], env)


if __name__ == '__main__':
    sys.exit(main())
