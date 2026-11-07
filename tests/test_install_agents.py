import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(path):
    spec = importlib.util.spec_from_file_location('installer', path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class HermesSafetyTests(unittest.TestCase):
    def test_check_never_invokes_hermes_cli(self):
        installer = load(ROOT / 'hermes/install.py')
        with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']) as tmp:
            home = Path(tmp) / '.hermes'
            home.mkdir()
            (home / 'config.yaml').write_text('plugins:\n  enabled:\n    - local\n')
            with patch.object(installer, 'hermes_bin', return_value='hermes'), patch.object(installer.subprocess, 'run') as run:
                installer.apply_settings(home, [('plugins.enabled', '["tracked"]')], force=False, check=True)
                installer.enable_plugins(home, check=True)
                run.assert_not_called()

    def test_default_conflict_rejected_before_settings_or_soul(self):
        installer = load(ROOT / 'hermes/install.py')
        with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']) as tmp:
            home = Path(tmp) / '.hermes'
            home.mkdir()
            (home / 'plugins').write_text('local conflict')
            with patch.object(installer, 'apply_settings') as settings, patch.object(installer, 'link_soul') as soul:
                with self.assertRaises(installer.InstallError):
                    installer.main(['--home', str(home), '--skip-plugins'])
                settings.assert_not_called()
                soul.assert_not_called()
            self.assertFalse((home / 'skills').exists())

    def test_default_redirected_home_or_config_rejected_before_settings(self):
        installer = load(ROOT / 'hermes/install.py')
        with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']) as tmp:
            base = Path(tmp)
            outside = base / 'outside/.hermes'
            outside.mkdir(parents=True)
            home = base / '.hermes'
            home.symlink_to(outside, target_is_directory=True)
            with patch.object(installer, 'apply_settings') as settings:
                with self.assertRaises(installer.InstallError):
                    installer.main(['--home', str(home), '--skip-stow', '--skip-plugins'])
                settings.assert_not_called()
            home.unlink()
            home.mkdir()
            (home / 'config.yaml').symlink_to(base / 'private.yaml')
            with patch.object(installer, 'apply_settings') as settings:
                with self.assertRaises(installer.InstallError):
                    installer.main(['--home', str(home), '--skip-stow', '--skip-plugins'])
                settings.assert_not_called()

    def test_invalid_home_rejected_before_any_write(self):
        installer = load(ROOT / 'hermes/install.py')
        with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']) as tmp:
            home = Path(tmp) / 'profiles' / 'unsafe'
            with patch.object(installer, 'apply_settings') as settings, patch.object(installer, 'link_soul') as soul:
                with self.assertRaises(installer.InstallError):
                    installer.main(['--home', str(home), '--skip-plugins'])
                settings.assert_not_called()
                soul.assert_not_called()
            self.assertFalse(home.exists())


class UnifiedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ['TMPDIR'])
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.bin = self.base / 'bin'
        self.bin.mkdir()
        hermes = self.bin / 'hermes'
        hermes.write_text('#!/bin/sh\nprintf "Unexpected Hermes CLI execution in fixture\\n" >&2\nexit 99\n')
        hermes.chmod(0o700)
        self.repo = self.base / 'repo'
        self.repo.mkdir()
        script = ROOT / 'install-agents.py'
        if script.exists():
            shutil.copy2(script, self.repo / script.name)
        self.home = self.base / 'home'
        self.profile = self.repo / 'hermes/profiles/example'
        (self.profile / 'skills/demo').mkdir(parents=True)
        (self.profile / 'SOUL.md').write_text('Reviewed soul\n')
        (self.profile / 'skills/demo/SKILL.md').write_text('Reviewed skill\n')

    def run_install(self, *args):
        env = dict(os.environ, HERMES_HOME=str(self.base / 'unrelated'), HOME=str(self.home),
                   PATH=str(self.bin) + os.pathsep + os.environ['PATH'])
        return subprocess.run([sys.executable, str(self.repo / 'install-agents.py'), *args], env=env, text=True, capture_output=True)

    def copy_package(self, name):
        shutil.copytree(ROOT / name, self.repo / name, symlinks=True, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('__pycache__'))

    def test_claude_and_codex_real_stow_repeated_with_explicit_target(self):
        for package in ('openclaude', 'claude-skills', 'codex', 'codex-skills'):
            self.copy_package(package)
        generated = self.repo / 'codex/.codex/config.toml'
        if generated.exists():
            generated.unlink()
        target = self.base / 'explicit'
        args = ['--tools', 'claude', 'codex', '--target', str(target), '--skip-plugins']
        result = self.run_install(*args, '--check')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(target.exists())
        self.assertFalse(generated.exists())
        for _ in range(2):
            result = self.run_install(*args)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((target / '.claude/CLAUDE.md').is_symlink())
        self.assertTrue((target / '.codex/agents').is_symlink())
        self.assertTrue((target / '.codex/config.toml').is_symlink())
        self.assertFalse((target / '.codex').is_symlink())
        self.assertFalse(self.home.exists())

    def test_named_settings_native_cli_after_conflicts_and_no_check_writes(self):
        self.copy_package('hermes')
        (self.profile / 'config.base.yaml').write_text('model.default: reviewed\nagent.reasoning_effort: medium\n')
        dest = self.home / '.hermes/profiles/example'
        dest.mkdir(parents=True)
        (dest / 'config.yaml').write_text('model:\n  default: local\n')
        installer = load(self.repo / 'install-agents.py')
        args = ['--tools', 'hermes', '--profiles', 'example', '--target', str(self.home)]
        with patch('shutil.which', return_value='hermes'), patch('subprocess.run', return_value=subprocess.CompletedProcess([], 0, 'medium\n', '')) as run:
            installer.main(args + ['--check'])
            self.assertEqual(run.call_count, 0)
            self.assertFalse((dest / 'SOUL.md').exists())
            (dest / 'SOUL.md').write_text('conflicting soul')
            with self.assertRaises(SystemExit), patch('sys.stderr'):
                installer.main(args)
            self.assertEqual(run.call_count, 0)
            (dest / 'SOUL.md').unlink()
            installer.main(args)
            calls = [call for call in run.call_args_list if call.args[0][1:3] == ['config', 'set']]
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0].args[0][-2:], ['agent.reasoning_effort', 'medium'])
            self.assertEqual(calls[0].kwargs['env']['HERMES_HOME'], str(dest))
        self.assertEqual((dest / 'config.yaml').read_text(), 'model:\n  default: local\n')

    def test_default_hermes_stow_excludes_named_packages(self):
        self.copy_package('hermes')
        installer = load(self.repo / 'hermes/install.py')
        home = self.home / '.hermes'
        installer.stow(home, check=False)
        installer.stow(home, check=False)
        result = self.run_install('--tools', 'hermes', '--skip-plugins', '--check')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.home / 'profiles').exists())
        self.assertFalse((home / 'profiles').exists())
        self.assertFalse((home / 'skills').is_symlink())

    def test_named_config_directory_conflict_before_linking(self):
        self.copy_package('hermes')
        (self.profile / 'config.base.yaml').write_text('model.default: reviewed\n')
        dest = self.home / '.hermes/profiles/example'
        (dest / 'config.yaml').mkdir(parents=True)
        result = self.run_install('--tools', 'hermes', '--profiles', 'example')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((dest / 'SOUL.md').exists())

    def test_later_tool_conflict_leaves_earlier_tool_untouched(self):
        for package in ('openclaude', 'claude-skills', 'codex', 'codex-skills'):
            self.copy_package(package)
        (self.home / '.codex').mkdir(parents=True)
        (self.home / '.codex/agents').write_text('private conflict')
        result = self.run_install('--tools', 'claude', 'codex', '--skip-plugins')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.home / '.claude').exists())
        self.assertEqual((self.home / '.codex/agents').read_text(), 'private conflict')

    def test_other_profile_conflict_leaves_all_profiles_untouched(self):
        second = self.repo / 'hermes/profiles/second'
        shutil.copytree(self.profile, second)
        dest = self.home / '.hermes/profiles/second'
        dest.mkdir(parents=True)
        (dest / 'SOUL.md').write_text('private')
        result = self.run_install('--tools', 'hermes', '--profiles', 'example', 'second')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.home / '.hermes/profiles/example').exists())
        self.assertEqual((dest / 'SOUL.md').read_text(), 'private')

    def test_invalid_profiles_and_redirected_parents_rejected(self):
        for name in ('../example', '.', '..', '/example', 'bad/name', 'bad name', 'default', 'missing'):
            with self.subTest(name=name):
                result = self.run_install('--tools', 'hermes', '--profiles', name)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('profile', result.stderr.lower())
                self.assertFalse(self.home.exists())
        self.home.mkdir()
        outside = self.base / 'outside'
        outside.mkdir()
        (self.home / '.hermes').symlink_to(outside, target_is_directory=True)
        result = self.run_install('--tools', 'hermes', '--profiles', 'example')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(list(outside.iterdir()), [])
        result = self.run_install('--tools', 'claude', '--profiles', 'example')
        self.assertNotEqual(result.returncode, 0)

    def test_conflicts_preflight_all_links(self):
        dest = self.home / '.hermes/profiles/example'
        (dest / 'skills').mkdir(parents=True)
        conflict = dest / 'skills/demo'
        conflict.symlink_to(self.base / 'foreign')
        for check in ([], ['--check']):
            result = self.run_install('--tools', 'hermes', '--profiles', 'example', *check)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('conflict', result.stderr.lower())
            self.assertFalse((dest / 'SOUL.md').exists())
            self.assertEqual(os.readlink(conflict), str(self.base / 'foreign'))
        conflict.unlink()
        (dest / 'SOUL.md').write_text('local soul')
        result = self.run_install('--tools', 'hermes', '--profiles', 'example')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((dest / 'SOUL.md').read_text(), 'local soul')
        self.assertFalse(conflict.exists())

    def test_named_profile_check_apply_repeat_preserves_state(self):
        args = ['--tools', 'hermes', '--profiles', 'example']
        result = self.run_install(*args, '--check')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.home.exists())
        dest = self.home / '.hermes/profiles/example'
        dest.mkdir(parents=True)
        for name in ('.env', 'auth.json', 'state.db', 'config.yaml'):
            (dest / name).write_text('private')
        for _ in range(2):
            result = self.run_install(*args)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((dest / 'SOUL.md').resolve(), self.profile / 'SOUL.md')
        self.assertEqual((dest / 'skills/demo').resolve(), self.profile / 'skills/demo')
        for name in ('.env', 'auth.json', 'state.db', 'config.yaml'):
            self.assertEqual((dest / name).read_text(), 'private')
        self.assertFalse((self.base / 'unrelated').exists())


if __name__ == '__main__':
    unittest.main()
