"""Print local recall targets, most specific first. Does not contact Honcho."""
import json
from pathlib import Path
import subprocess

HOME = Path.home()
GROUPS = {
    'code/kube-lvl47': 'project-cluster-infra',
    'ansible': 'project-cluster-infra',
    'code/statsboard/statsboards-backend': 'project-statsboard',
    'code/statsboard/statsboards-frontend': 'project-statsboard',
}
ALIASES = {
    'code/ochistka-musoroprovoda.ru': 'ochistka-musoroprovoda-ru',
    'code/videooperator.su': 'videooperator-su',
    'code/portals/videosemka.su': 'portals--videosemka-su',
}


def targets(common):
    if common.name != '.git':
        return []
    root = common.parent
    if root not in (HOME / 'ansible', HOME / 'dotfiles') and HOME / 'code' not in root.parents:
        return []
    rel = str(root.relative_to(HOME))
    repo = rel.removeprefix('code/').replace('/', '--')
    if repo in {'linroot', 'pi-coordinator', 'code-wide'} or repo.startswith('project-'):
        return []
    if rel.startswith('code/') and (repo in {'ansible', 'dotfiles'} or '--' in rel):
        return []
    return [ALIASES.get(rel, repo), *([GROUPS[rel]] if rel in GROUPS else []), 'code-wide']


if __name__ == '__main__':
    git = subprocess.run(['/usr/bin/git', 'rev-parse', '--path-format=absolute', '--git-common-dir'],
                         capture_output=True, text=True, env={'HOME': str(HOME), 'PATH': '/usr/bin'})
    print(json.dumps(targets(Path(git.stdout.strip()).resolve()) if not git.returncode else []))
