#!/usr/bin/env python3
import argparse
import hashlib
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request

VERSION = '1.3.1'
ARCHIVE_SHA256 = '3219443a9734b89b93fb16ee8d65844759fa1b3cd3cf139c606b7353cfb0715c'
URL = f'https://github.com/steveyegge/beads/releases/download/v{VERSION}/beads_{VERSION}_linux_amd64.tar.gz'


def main():
    parser = argparse.ArgumentParser(description='Install the checksum-pinned Linux amd64 Beads client and version guard.')
    parser.add_argument('--prefix', type=Path, default=Path.home() / '.local')
    parser.add_argument('--archive', type=Path)
    args = parser.parse_args()
    if os.uname().sysname != 'Linux' or os.uname().machine != 'x86_64':
        parser.error('This pinned archive supports Linux amd64 only.')
    prefix = args.prefix.resolve()
    with tempfile.TemporaryDirectory(prefix='beads-install-') as scratch:
        archive = args.archive
        if archive is None:
            archive = Path(scratch) / 'release.tar.gz'
            urllib.request.urlretrieve(URL, archive)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != ARCHIVE_SHA256:
            raise SystemExit('Beads archive checksum mismatch; nothing installed.')
        candidate = Path(scratch) / 'bd'
        with tarfile.open(archive) as release:
            members = [m for m in release.getmembers() if m.name in ('bd', './bd') and m.isfile()]
            if len(members) != 1:
                raise SystemExit('Release must contain exactly one regular bd executable.')
            with release.extractfile(members[0]) as source, candidate.open('wb') as target:
                shutil.copyfileobj(source, target)
        candidate.chmod(0o755)
        version = subprocess.check_output([str(candidate), 'version'], text=True).splitlines()[0]
        if not version.startswith(f'bd version {VERSION} '):
            raise SystemExit(f'Unexpected release version: {version}')
        target = prefix / 'lib' / 'beads' / VERSION / 'bd'
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and target.read_bytes() != candidate.read_bytes():
            raise SystemExit(f'Refusing to replace different pinned executable: {target}')
        if not target.exists():
            shutil.copy2(candidate, target)
        launcher = prefix / 'bin' / 'bd'
        launcher.parent.mkdir(parents=True, exist_ok=True)
        script = f'''#!/bin/sh
set -eu
client={shlex.quote(str(target))}
version=$("$client" version) || {{ printf '%s\\n' 'bd guard: pinned client unavailable' >&2; exit 78; }}
case "$version" in
  'bd version {VERSION} '*) ;;
  *) printf '%s\\n' "bd guard: expected {VERSION}; refusing $version before opening a tracker" >&2; exit 78 ;;
esac
exec "$client" "$@"
'''
        if launcher.exists() or launcher.is_symlink():
            if launcher.is_symlink() or launcher.read_bytes() != script.encode():
                backups = prefix / 'lib' / 'beads' / 'backups'
                backups.mkdir(parents=True, exist_ok=True)
                digest = hashlib.sha256(launcher.read_bytes()).hexdigest()
                backup = backups / f'bd-{digest}'
                if not backup.exists():
                    shutil.copy2(launcher, backup)
                print(f'Previous client preserved: {backup}')
        temporary = launcher.with_name('bd.installing')
        if temporary.exists():
            raise SystemExit(f'Refusing to overwrite existing temporary launcher: {temporary}')
        temporary.write_text(script)
        temporary.chmod(0o755)
        temporary.replace(launcher)
        print(f'Installed guarded bd {VERSION}: {launcher}')


if __name__ == '__main__':
    main()
