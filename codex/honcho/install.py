#!/usr/bin/python3
"""Deploy only Honcho settings, preserving existing Codex configuration."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import subprocess
import tomllib

PACKAGE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('codex_install', PACKAGE / 'install.py')
config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(config)


def write_private(path, data):
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name + '.')
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(data)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


RUNTIME_ENV_VARS = ['XDG_RUNTIME_DIR', 'HONCHO_CONFIG_PATH', 'HONCHO_BASE_URL', 'HONCHO_URL',
                    'HONCHO_ENDPOINT', 'HONCHO_API_KEY', 'HONCHO_WORKSPACE', 'HONCHO_WORKSPACE_ID']


def runtime_env_vars(existing):
    result = list(existing or [])
    for name in RUNTIME_ENV_VARS:
        if not any(item == name or isinstance(item, dict) and item.get('name') == name and
                   item.get('source', 'local') == 'local' for item in result):
            result.append(name)
    return result


def managed_relinks(target, previous, package):
    paths = ['.local/bin/codex-honcho-mcp', '.codex/hooks.json']
    modules = target / '.codex/honcho'
    if modules.is_symlink():
        paths.append('.codex/honcho')
    else:
        paths.extend('.codex/honcho/' + path.name for path in (package / '.codex/honcho').glob('*.py'))
    relinks = []
    for name in paths:
        live = target / name
        if live.is_symlink() and live.resolve() == (previous / name).resolve():
            relinks.append((live, os.readlink(live)))
        elif live.exists() and live.resolve() != (package / name).resolve():
            raise ValueError('Relink conflict; unrelated path preserved: ' + str(live))
    return relinks


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--target', type=Path, default=Path.home())
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--relink-existing', action='store_true', help='Relink only verified Honcho symlinks from another retained checkout.')
    args = parser.parse_args()
    target = args.target.expanduser().resolve()
    home = target / '.codex'
    live = home / 'config.toml'
    hook_file = home / 'hooks.json'
    launcher = target / '.local/bin/codex-honcho-mcp'
    source = PACKAGE / '.local/bin/codex-honcho-mcp'
    desired = {'command': str(launcher), 'startup_timeout_sec': 30, 'default_tools_approval_mode': 'writes'}
    settings = tomllib.loads(live.read_text()) if live.exists() else {}
    old = settings.get('mcp_servers', {}).get('honcho')
    if old and old.get('command') not in ('codex-honcho-mcp', str(launcher)):
        parser.error('An independently managed Honcho server exists; preserved.')
    settings.setdefault('mcp_servers', {})['honcho'] = {
        **desired, **(old or {}), 'command': str(launcher),
        'env_vars': runtime_env_vars((old or {}).get('env_vars'))}
    settings.setdefault('features', {}).setdefault('hooks', True)
    hooks = json.loads(hook_file.read_text()) if hook_file.exists() else {}
    groups = hooks.setdefault('hooks', {}).setdefault('SessionStart', [])
    command = 'codex-honcho-mcp --session-start'
    found = any(h.get('command') == command for g in groups for h in g.get('hooks', []))
    if not found:
        groups.append({'matcher': 'startup|resume|compact', 'hooks': [
            {'type': 'command', 'command': command, 'timeout': 30, 'additionalContextLimit': 3000}]})
    relinks = []
    previous = None
    if launcher.exists() or launcher.is_symlink():
        if not launcher.is_symlink():
            parser.error('Existing launcher is not a symlink; preserved.')
        if launcher.resolve() != source:
            old = launcher.resolve()
            if not args.relink_existing or old.parts[-3:] != ('.local', 'bin', 'codex-honcho-mcp'):
                parser.error('Existing launcher belongs to another installation; use --relink-existing for verified Honcho links.')
            previous = old.parents[2]
            if not (previous / 'honcho/install.py').is_file() or not (previous / '.codex/honcho/server.py').is_file():
                parser.error('Previous Honcho checkout cannot be verified; preserved.')
            try:
                relinks = managed_relinks(target, previous, PACKAGE)
            except ValueError as error:
                parser.error(str(error))
    generated_hook = PACKAGE / '.codex/hooks.json'
    if hook_file.is_symlink() and hook_file.resolve() != generated_hook and not previous:
        parser.error('Hooks are managed by another checkout; preserved.')
    if (generated_hook.exists() and hook_file.resolve() != generated_hook and
            generated_hook.read_text() != json.dumps(hooks, indent=2) + '\n'):
        parser.error('Generated hooks belong to another target; use a fresh checkout.')
    serialized = config.serialize(settings)
    tomllib.loads(serialized)
    print('Valid Honcho MCP registration and SessionStart hook. Other settings preserved.')
    if args.check:
        return
    home.mkdir(parents=True, exist_ok=True)
    backup = home / 'backups'
    for path in (live, hook_file):
        if path.exists():
            config.backup_config(path, backup, path.name + '.pre-honcho')
    write_private(live.resolve() if live.is_symlink() else live, serialized)
    generated_hook.parent.mkdir(parents=True, exist_ok=True)
    write_private(generated_hook, json.dumps(hooks, indent=2) + '\n')
    if hook_file.exists() and not hook_file.is_symlink():
        hook_file.unlink()
    for path, old_link in relinks:
        if not path.is_symlink() or os.readlink(path) != old_link:
            raise ValueError('Verified symlink changed; relink stopped.')
        path.unlink()
    ignore = r'^(?!\.codex$|\.codex/honcho(?:/|$)|\.codex/hooks\.json$|\.local$|\.local/bin$|\.local/bin/codex-honcho-mcp$).*'
    try:
        subprocess.run(['stow', '--dir', str(PACKAGE.parent), '--target', str(target), '--no-folding', '--ignore', ignore, 'codex'], check=True)
    except subprocess.CalledProcessError:
        for path, old_link in relinks:
            if not path.exists() and not path.is_symlink():
                path.symlink_to(old_link)
        raise
    print('Installed Honcho. New MCP discovery needs a new session; enable its hook in /hooks if required.')


if __name__ == '__main__':
    main()
