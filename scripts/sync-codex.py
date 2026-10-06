import argparse
import datetime
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import tomllib
import uuid


ALLOWED_SETTINGS = {'model', 'model_reasoning_effort', 'personality', 'approval_policy', 'sandbox_mode', 'web_search'}


def merge_settings(text, settings):
    if not isinstance(settings, dict) or set(settings) - ALLOWED_SETTINGS:
        raise ValueError('Shared settings must contain only the documented portable settings.')
    if any(not isinstance(value, str) for value in settings.values()):
        raise ValueError('Shared settings must be strings.')
    original = tomllib.loads(text)
    expected = dict(original)
    expected.update(settings)
    if original == expected:
        return text
    lines = text.splitlines(keepends=True)
    end = next((i for i, line in enumerate(lines) if line.lstrip().startswith('[')), len(lines))
    prefix = ''.join(lines[:end])
    for key, value in settings.items():
        if original.get(key) == value:
            continue
        assignment = f'{key} = {json.dumps(value, ensure_ascii=False)}\n'
        pattern = rf'(?m)^[ \t]*{re.escape(key)}[ \t]*=.*(?:\n|$)'
        matches = list(re.finditer(pattern, prefix))
        if len(matches) > 1:
            raise ValueError(f'Ambiguous setting: {key}')
        if matches:
            prefix = re.sub(pattern, lambda match: assignment, prefix, count=1)
        elif key in original:
            raise ValueError(f'Unsupported assignment format for {key}; leave the local file unchanged.')
        else:
            prefix += ('\n' if prefix and not prefix.endswith('\n') else '') + assignment
    result = prefix + ''.join(lines[end:])
    if tomllib.loads(result) != expected:
        raise ValueError('Settings merge would alter unrelated values; leave the local file unchanged.')
    return result


def contained_source(repo, relative):
    path = (repo / relative).resolve()
    if not path.is_relative_to(repo.resolve()):
        raise ValueError('Source path must stay inside the dotfiles repository.')
    return path


def build_plan(repo, home, codex_home):
    settings = json.loads((repo / 'codex/settings.json').read_text(encoding='utf-8-sig'))
    config = codex_home / 'config.toml'
    original = config.read_bytes() if config.exists() else b''
    updated = merge_settings(original.decode('utf-8-sig'), settings)
    plan = []
    if updated != original.decode('utf-8-sig'):
        plan.append({'kind': 'config', 'destination': config, 'content': updated.encode('utf-8'), 'original': original, 'backup': 'config.toml'})
    agents = contained_source(repo, 'codex/.codex/AGENTS.md')
    if not agents.is_file():
        raise ValueError('Missing shared instructions.')
    links = [(agents, codex_home / 'AGENTS.md', 'AGENTS.md')]
    sources = json.loads((repo / 'codex/skills.json').read_text(encoding='utf-8-sig'))
    if not isinstance(sources, list) or any(not isinstance(item, str) for item in sources):
        raise ValueError('The skills manifest must be a list of repository-relative paths.')
    names = set()
    for relative in sources:
        source = contained_source(repo, relative)
        if not source.is_dir() or not (source / 'SKILL.md').is_file():
            raise ValueError(f'Missing skill: {relative}')
        if source.name in names or source.name in {'synced', '.system'}:
            raise ValueError(f'Duplicate or reserved skill directory: {source.name}')
        names.add(source.name)
        links.append((source, home / '.agents/skills' / source.name, f'skills/{source.name}'))
    for source, destination, backup in links:
        if destination.is_symlink() and destination.resolve() == source:
            continue
        if source == destination.resolve():
            raise ValueError('Source and destination overlap.')
        links_kind = 'directory link' if source.is_dir() else 'file link'
        plan.append({'kind': links_kind, 'source': source, 'destination': destination, 'backup': backup})
    return plan


def apply_plan(plan, codex_home):
    if not plan:
        return None
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup = codex_home / 'dotfiles-backups' / f'{stamp}-{uuid.uuid4().hex[:8]}'
    completed = []
    try:
        for item in plan:
            destination = item['destination']
            destination.parent.mkdir(parents=True, exist_ok=True)
            if item['kind'] == 'config':
                current = destination.read_bytes() if destination.exists() else b''
                if current != item['original']:
                    raise RuntimeError('Codex settings changed during sync; rerun the script.')
            saved = backup / item['backup']
            existed = os.path.lexists(destination)
            if existed:
                saved.parent.mkdir(parents=True, exist_ok=True)
                os.replace(destination, saved)
            completed.append((destination, saved if existed else None))
            if item['kind'] == 'config':
                with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as handle:
                    temporary = Path(handle.name)
                    handle.write(item['content'])
                try:
                    os.replace(temporary, destination)
                finally:
                    temporary.unlink(missing_ok=True)
            else:
                os.symlink(item['source'], destination, target_is_directory=item['source'].is_dir())
        return backup if backup.exists() else None
    except Exception:
        for destination, saved in reversed(completed):
            if os.path.lexists(destination):
                destination.unlink()
            if saved is not None:
                os.replace(saved, destination)
        raise


def main():
    parser = argparse.ArgumentParser(description='Deploy selected Codex settings and link curated skills without copying runtime data.')
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument('--home', type=Path, default=Path.home())
    parser.add_argument('--codex-home', type=Path)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    codex_home = args.codex_home or Path(os.environ.get('CODEX_HOME', str(args.home / '.codex')))
    plan = build_plan(args.repo.resolve(), args.home.resolve(), codex_home.resolve())
    for item in plan:
        print(f"{item['kind']}: {item['destination']}")
    if not args.apply:
        print(f'Dry run: {len(plan)} changes. Use -Apply to deploy.')
        return
    backup = apply_plan(plan, codex_home.resolve())
    remaining = build_plan(args.repo.resolve(), args.home.resolve(), codex_home.resolve())
    if remaining:
        raise RuntimeError('Verification failed: rerunning would still make changes.')
    print(f'Verified: {len(plan)} changes; rerun requires no changes.')
    if backup:
        print(f'Backups: {backup}')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(f'Sync failed ({type(error).__name__}). No configuration values are printed.', file=sys.stderr)
        sys.exit(1)
