#!/usr/bin/env python3
"""Deploy selected agent dotfiles, keeping tool-specific installers authoritative."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import runpy
from types import SimpleNamespace
import subprocess
import sys
import tempfile

REPO = Path(__file__).resolve().parent


def deploy_defaults(tools, target, *, check, skip_plugins):
    env = dict(os.environ, HOME=str(target), CODEX_HOME=str(target / '.codex'),
               HERMES_HOME=str(target / '.hermes'))
    for tool in tools:
        if tool == 'claude':
            cmd = ['stow', '--dir', str(REPO), '--target', str(target), 'openclaude', 'claude-skills']
            if check:
                cmd.append('--simulate')
        else:
            cmd = [sys.executable, str(REPO / tool / 'install.py')]
            cmd += ['--target', str(target)] if tool == 'codex' else ['--home', str(target / '.hermes')]
            if check:
                cmd.append('--check')
            if skip_plugins:
                cmd.append('--skip-plugins')
        subprocess.run(cmd, env=env, check=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tools', nargs='+', choices=('claude', 'codex', 'hermes'), required=True)
    parser.add_argument('--profiles', nargs='+', default=[])
    parser.add_argument('--target', type=Path, default=Path.home())
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--skip-plugins', action='store_true')
    args = parser.parse_args(argv)
    if args.profiles and 'hermes' not in args.tools:
        parser.error('--profiles requires --tools hermes')
    target = args.target.expanduser().resolve()
    links = []
    profile_settings = []
    hermes = None
    for name in dict.fromkeys(args.profiles):
        if name == 'default' or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', name):
            parser.error(f'invalid profile name: {name!r}')
        source = REPO / 'hermes/profiles' / name
        if source.is_symlink() or not (source / 'SOUL.md').is_file() or (source / 'SOUL.md').is_symlink():
            parser.error(f'profile requires a reviewed regular SOUL.md: {source}')
        dest = target / '.hermes/profiles' / name
        for directory in (target, target / '.hermes', target / '.hermes/profiles', dest, dest / 'skills'):
            if directory.is_symlink() or (directory.exists() and not directory.is_dir()):
                parser.error(f'profile directory conflict: {directory}')
        links.append((source / 'SOUL.md', dest / 'SOUL.md'))
        settings_file = source / 'config.base.yaml'
        if settings_file.exists() or settings_file.is_symlink():
            config = dest / 'config.yaml'
            if settings_file.is_symlink() or not settings_file.is_file() or config.is_symlink() or (config.exists() and not config.is_file()):
                parser.error(f'profile config conflict: expected regular files at {settings_file} and {config}')
            hermes = hermes or SimpleNamespace(**runpy.run_path(str(REPO / 'hermes/install.py')))
            profile_settings.append((dest, hermes.read_settings(settings_file)))
        skills = source / 'skills'
        if skills.is_symlink():
            parser.error(f'profile skills must be a real directory: {skills}')
        if skills.exists():
            for skill in sorted(skills.iterdir()):
                if skill.is_symlink() or not skill.is_dir() or not (skill / 'SKILL.md').is_file():
                    parser.error(f'profile skill requires a directory with SKILL.md: {skill}')
                links.append((skill, dest / 'skills' / skill.name))
    for source, dest in links:
        if dest.is_symlink():
            if dest.resolve() != source.resolve():
                parser.error(f'conflict: foreign link {dest}')
        elif dest.exists():
            parser.error(f'conflict: existing local path {dest}; preserve or move it explicitly')
    if hermes:
        for home, settings in profile_settings:
            hermes.apply_settings(home, settings, force=False, check=True)
    tools = [tool for tool in dict.fromkeys(args.tools) if tool != 'hermes' or not args.profiles]
    if tools:
        if target.exists():
            deploy_defaults(tools, target, check=True, skip_plugins=args.skip_plugins)
        else:
            with tempfile.TemporaryDirectory(prefix='agent-install-check-') as scratch:
                deploy_defaults(tools, Path(scratch), check=True, skip_plugins=args.skip_plugins)
        if not args.check:
            target.mkdir(parents=True, exist_ok=True)
            deploy_defaults(tools, target, check=False, skip_plugins=args.skip_plugins)
    for source, dest in links:
        print(f'link {dest} -> {source}')
        if not args.check:
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.is_symlink():
                dest.symlink_to(source, target_is_directory=source.is_dir())
    if hermes and not args.check:
        for home, settings in profile_settings:
            hermes.apply_settings(home, settings, force=False, check=False)
    return 0


if __name__ == '__main__':
    sys.exit(main())
