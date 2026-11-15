"""Installer regression: dry-run no-write, local override preservation, --force backup.

Covers the profile-local override contract: an unforced install must
preserve (never replace) a profile-local real file that differs from the
tracked copy; --force is the deliberate replacement path with backup.
Also covers the full-entrypoint --check no-write property (R5).

Run from the candidate root in a sterile env::

    env -i HOME=<scratch>/home HERMES_HOME=<scratch>/home/.hermes \
        TMPDIR=<scratch>/tmp PYTHONDONTWRITEBYTECODE=1 \
        python3 -m unittest hermes.tests.test_install_profiles -v
"""
import os
from pathlib import Path
import subprocess
import sys
import unittest

CANDIDATE = Path(__file__).resolve().parents[2]
INSTALLER = CANDIDATE / "hermes" / "install.py"
TRACKED_SOUL = CANDIDATE / "hermes" / "profiles" / "cluster-operator" / "SOUL.md"

ROOT = Path(os.environ["HOME"]).parent
assert Path(os.environ["HERMES_HOME"]).resolve().is_relative_to(ROOT.resolve())
assert Path(os.environ["TMPDIR"]).resolve().is_relative_to(ROOT.resolve())


def run_installer(home: Path, hermes_home: Path, *extra: str, profiles: str = "cluster-operator") -> subprocess.CompletedProcess:
    env = dict(os.environ, HOME=str(home), HERMES_HOME=str(hermes_home))
    return subprocess.run(
        [sys.executable, str(INSTALLER), "--home", str(hermes_home),
         "--profiles", profiles, "--skip-plugins", *extra],
        env=env, cwd=CANDIDATE, text=True, capture_output=True, timeout=300,
    )


class ProfileOverrideContract(unittest.TestCase):
    def setUp(self):
        self.home = ROOT / (self.id().rsplit(".", 1)[-1] + "-" + os.environ["TMPDIR"].rstrip("/").rsplit("/", 1)[-1]) / "home"
        self.hermes_home = self.home / ".hermes"
        folder = self.hermes_home / "profiles" / "cluster-operator"
        folder.mkdir(parents=True)
        (folder / "SOUL.md").write_text("local observer override sentinel\n")

    def soul(self) -> Path:
        return self.hermes_home / "profiles" / "cluster-operator" / "SOUL.md"

    def test_check_creates_nothing_for_real_file(self):
        before = sorted(p.relative_to(self.home).as_posix() for p in self.home.rglob("*"))
        result = run_installer(self.home, self.hermes_home, "--check")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("dry run: nothing written", result.stdout)
        self.assertIn("would fail closed", result.stdout)
        after = sorted(p.relative_to(self.home).as_posix() for p in self.home.rglob("*"))
        self.assertEqual(after, before)
        self.assertFalse(self.soul().is_symlink())
        self.assertEqual(self.soul().read_text(), "local observer override sentinel\n")

    def test_apply_without_force_fails_closed_and_preserves_override(self):
        result = run_installer(self.home, self.hermes_home)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not replacing it without --force", result.stderr)
        self.assertFalse(self.soul().is_symlink())
        self.assertEqual(self.soul().read_text(), "local observer override sentinel\n")
        dotfiles_backups = self.hermes_home / "profiles" / "cluster-operator" / "backups" / "dotfiles"
        self.assertFalse(dotfiles_backups.exists())

    def test_apply_force_backs_up_real_file_and_links(self):
        result = run_installer(self.home, self.hermes_home, "--force")
        self.assertEqual(result.returncode, 0, result.stderr)
        profile = self.hermes_home / "profiles" / "cluster-operator"
        self.assertEqual((profile / "SOUL.md").resolve(), TRACKED_SOUL.resolve())
        backups = list((profile / "backups" / "dotfiles").iterdir())
        soul_backups = [b for b in backups if b.name.startswith("SOUL.md.")]
        self.assertEqual(len(soul_backups), 1)
        self.assertEqual(soul_backups[0].read_text(), "local observer override sentinel\n")


class FreshInstallAndSelection(unittest.TestCase):
    def setUp(self):
        self.home = ROOT / (self.id().rsplit(".", 1)[-1] + "-fresh") / "home"
        self.hermes_home = self.home / ".hermes"

    def test_fresh_install_then_repeat_is_idempotent(self):
        first = run_installer(self.home, self.hermes_home)
        self.assertEqual(first.returncode, 0, first.stderr)
        soul = self.hermes_home / "profiles" / "cluster-operator" / "SOUL.md"
        self.assertEqual(soul.resolve(), TRACKED_SOUL.resolve())
        skill = self.hermes_home / "profiles" / "cluster-operator" / "skills" / "cluster-operations"
        self.assertTrue(skill.is_symlink())
        second = run_installer(self.home, self.hermes_home)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("already points at", second.stdout)
        # F17-1 dependency resolution: installing the dotfiles-sync consumer
        # together with the two owner profiles must resolve the consumer's
        # declared skills.external_dirs entries from THIS candidate's tracked
        # trees, never from live source profiles.
        third = run_installer(
            self.home, self.hermes_home, profiles="dotfiles-sync,bot-creator,git-puller"
        )
        self.assertEqual(third.returncode, 0, third.stderr)
        for skill, owner in (("pipeline-contract", "bot-creator"),
                             ("git-freshness", "git-puller")):
            installed = self.hermes_home / "profiles" / owner / "skills" / skill
            tracked = CANDIDATE / "hermes" / "profiles" / owner / "skills" / skill
            self.assertTrue(installed.is_symlink(), installed)
            self.assertEqual(installed.resolve(), tracked.resolve())
            self.assertTrue((installed / "SKILL.md").is_file())
        # F19-1: the repo's regression tree must never be stowed into HOME;
        # top-level tests/ is installer tooling, not an installed package.
        leaked = self.home / "tests"
        self.assertFalse(leaked.exists() or leaked.is_symlink(), leaked)

    def test_unknown_profile_is_rejected(self):
        env = dict(os.environ, HOME=str(self.home), HERMES_HOME=str(self.hermes_home))
        result = subprocess.run(
            [sys.executable, str(INSTALLER), "--home", str(self.hermes_home),
             "--profiles", "no-such-profile", "--skip-plugins"],
            env=env, cwd=CANDIDATE, text=True, capture_output=True, timeout=300,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unknown profile", result.stderr)

    def test_inherited_hermes_home_env_is_used(self):
        env = dict(os.environ, HOME=str(self.home), HERMES_HOME=str(self.hermes_home))
        result = subprocess.run(
            [sys.executable, str(INSTALLER), "--profiles", "cluster-operator", "--skip-plugins"],
            env=env, cwd=CANDIDATE, text=True, capture_output=True, timeout=300,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        soul = self.hermes_home / "profiles" / "cluster-operator" / "SOUL.md"
        self.assertEqual(soul.resolve(), TRACKED_SOUL.resolve())

    def test_foreign_symlink_unforced_fails_closed_and_preserves_link(self):
        folder = self.hermes_home / "profiles" / "cluster-operator"
        folder.mkdir(parents=True)
        elsewhere = self.home / "elsewhere"
        elsewhere.mkdir()
        foreign_target = elsewhere / "SOUL.md"
        foreign_target.write_text("foreign target content\n")
        soul = folder / "SOUL.md"
        soul.symlink_to(foreign_target)
        result = run_installer(self.home, self.hermes_home)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not replacing it without --force", result.stderr)
        # Link identity is preserved: still a symlink at the same path,
        # pointing at the same foreign target; target bytes untouched.
        self.assertTrue(soul.is_symlink())
        self.assertEqual(os.readlink(soul), str(foreign_target))
        self.assertEqual(soul.resolve(), foreign_target.resolve())
        self.assertEqual(foreign_target.read_text(), "foreign target content\n")
        backups = self.hermes_home / "profiles" / "cluster-operator" / "backups" / "dotfiles"
        self.assertFalse(backups.exists())

    def test_foreign_symlink_check_mode_warns_without_writes(self):
        folder = self.hermes_home / "profiles" / "cluster-operator"
        folder.mkdir(parents=True)
        elsewhere = self.home / "elsewhere"
        elsewhere.mkdir()
        foreign_target = elsewhere / "SOUL.md"
        foreign_target.write_text("foreign target content\n")
        soul = folder / "SOUL.md"
        soul.symlink_to(foreign_target)
        result = run_installer(self.home, self.hermes_home, "--check")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("would fail closed", result.stdout)
        self.assertTrue(soul.is_symlink())
        self.assertEqual(os.readlink(soul), str(foreign_target))

    def test_foreign_symlink_force_replaces_and_backs_up_the_link(self):
        folder = self.hermes_home / "profiles" / "cluster-operator"
        folder.mkdir(parents=True)
        elsewhere = self.home / "elsewhere"
        elsewhere.mkdir()
        foreign_target = elsewhere / "SOUL.md"
        foreign_target.write_text("foreign target content\n")
        soul = folder / "SOUL.md"
        soul.symlink_to(foreign_target)
        result = run_installer(self.home, self.hermes_home, "--force")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(soul.resolve(), TRACKED_SOUL.resolve())
        # The foreign target itself is never touched.
        self.assertEqual(foreign_target.read_text(), "foreign target content\n")
        # The old link identity is preserved as a backed-up symlink.
        backups = self.hermes_home / "profiles" / "cluster-operator" / "backups" / "dotfiles"
        link_backups = [b for b in backups.iterdir() if b.name.startswith("SOUL.md.link.")]
        self.assertEqual(len(link_backups), 1)
        self.assertTrue(link_backups[0].is_symlink())
        self.assertEqual(os.readlink(link_backups[0]), str(foreign_target))


if __name__ == "__main__":
    unittest.main(verbosity=2)
