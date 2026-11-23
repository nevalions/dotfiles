#!/usr/bin/python3 -I
"""Top-level interactive launcher; the publisher is never globally registered."""
import json
import os
from pathlib import Path
import re
import socket
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
TEAM = AGENT / 'team/workflow.md'


def plain(args):
    if args[-1:] in (['-r'], ['--resume'], ['-c'], ['--continue']):
        args = args[:-1]
    elif len(args) >= 2 and args[-2] in ('--session', '--session-id') and not args[-1].startswith('-'):
        args = args[:-2]
    if not args:
        return True
    version = (AGENT / 'install/current-version').read_text().strip()
    examples = AGENT / 'install/releases' / version / 'node_modules/@earendil-works/pi-coding-agent/examples/extensions'
    return args == ['--extension', str(examples / 'subagent/index.ts'), '--extension', str(examples / 'todo.ts'),
                    '--append-system-prompt', str(TEAM), '--agy-team']


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
