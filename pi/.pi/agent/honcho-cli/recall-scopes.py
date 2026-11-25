"""Print local recall targets, most specific first. Does not contact Honcho."""
import json
import os
from pathlib import Path
import re
import stat
import subprocess

HOME = Path.home()
GROUPS = {
    'code/kube-lvl47': 'project-cluster-infra',
    'ansible': 'project-cluster-infra',
    'code/statsboard/statsboards-backend': 'project-statsboard',
    'code/statsboard/statsboards-frontend': 'project-statsboard',
}
ALIASES = {
    'code/stoma science': 'stoma_science',
    'code/ochistka-musoroprovoda.ru': 'ochistka-musoroprovoda-ru',
    'code/videooperator.su': 'videooperator-su',
    'code/portals/videosemka.su': 'portals--videosemka-su',
}
FORGEJO_HOST = 'git.butakov.su'
MAX_ORIGIN_LEN = 256


def _origin_matchers(repo_path):
    """Return compiled exact-match regexes for accepted Forgejo origin URLs."""
    host = re.escape(FORGEJO_HOST)
    path = re.escape(repo_path)
    return (
        re.compile(rf'ssh://(?:git@)?{host}:2222/{path}(?:\.git)?', re.ASCII),
        re.compile(rf'(?:git@)?{host}:{path}(?:\.git)?', re.ASCII),
        re.compile(rf'https://{host}/{path}(?:\.git)?', re.ASCII),
    )


IDENTITY_ALIASES = {
    'code/purpleflow': ('hermes-flow', _origin_matchers('nevalions/hermes-flow')),
    'code/portals/videooperator.su': ('videooperator-su', _origin_matchers('nevalions/videooperator.su')),
    'code/portals/ochistka-musoroprovoda.ru': (
        'ochistka-musoroprovoda-ru',
        _origin_matchers('nevalions/ochistka-musoroprovoda.ru'),
    ),
    'code/portals/portal-contact': ('portal-contact', _origin_matchers('nevalions/portal-contact')),
}


def _read_origin(common):
    """Read a single local remote.origin.url from common/config without includes or rewrites."""
    config = common / 'config'
    try:
        info = os.lstat(config)
    except OSError:
        return None
    if not stat.S_ISREG(info.st_mode):
        return None
    try:
        git = subprocess.run(
            ['/usr/bin/git', 'config', '--null', '--file', str(config), '--no-includes', '--get-all', 'remote.origin.url'],
            capture_output=True,
            env={'HOME': str(HOME), 'PATH': '/usr/bin'},
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if git.returncode != 0:
        return None
    if not git.stdout.endswith(b'\x00'):
        return None
    raw = git.stdout[:-1]
    if b'\x00' in raw:
        return None
    try:
        return raw.decode('utf-8')
    except UnicodeDecodeError:
        return None


def _identity_target(rel, common):
    """Resolve an identity-bound alias only when local origin matches unambiguously."""
    alias, matchers = IDENTITY_ALIASES[rel]
    origin = _read_origin(common)
    if origin is None or len(origin) > MAX_ORIGIN_LEN:
        return None
    if not any(matcher.fullmatch(origin) for matcher in matchers):
        return None
    return alias


def targets(common):
    if common.name != '.git':
        return []
    root = common.parent
    if root not in (HOME / 'ansible', HOME / 'dotfiles') and HOME / 'code' not in root.parents:
        return []
    rel = str(root.relative_to(HOME))
    if rel in IDENTITY_ALIASES:
        target = _identity_target(rel, common)
        if target is None:
            return []
        return [target, *([GROUPS[rel]] if rel in GROUPS else []), 'code-wide']
    repo = rel.removeprefix('code/').replace('/', '--')
    if repo in {'linroot', 'pi-coordinator', 'code-wide'} or repo.startswith('project-'):
        return []
    if rel.startswith('code/') and (repo in {'ansible', 'dotfiles'} or '--' in rel):
        return []
    if rel not in ALIASES and repo in ALIASES.values():
        return []
    return [ALIASES.get(rel, repo), *([GROUPS[rel]] if rel in GROUPS else []), 'code-wide']


if __name__ == '__main__':
    git = subprocess.run(['/usr/bin/git', 'rev-parse', '--path-format=absolute', '--git-common-dir'],
                         capture_output=True, text=True, env={'HOME': str(HOME), 'PATH': '/usr/bin'})
    print(json.dumps(targets(Path(git.stdout.strip()).resolve()) if not git.returncode else []))
