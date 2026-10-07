# Pinned Beads client

Linux amd64 uses Beads 1.3.1. The installer verifies the release archive's pinned SHA-256, preserves any displaced bd executable under the installation prefix's lib/beads/backups, and installs a launcher that refuses another version before forwarding tracker commands.

```sh
python3 beads/install.py
sudo python3 beads/install.py --prefix /usr/local
command -v bd
bd version
env -i HOME="$HOME" PATH=/usr/local/bin:/usr/bin /bin/sh -c 'command -v bd; bd version'
```

Use `--archive /path/to/beads_1.3.1_linux_amd64.tar.gz` for an already downloaded release; the same checksum verification applies. User installation defaults to ~/.local. System installation covers invocation paths that include /usr/local/bin. It does not change shell or service environment settings. On Arch, also install the local package below so restricted PATH=/usr/bin and absolute /usr/bin/bd use a package-owned guard.

## Arch package

The configured sync databases do not contain a beads package. Build the checksum-pinned upstream release locally and upgrade the existing beads package with pacman, preserving ownership of /usr/bin/bd. Build as your ordinary user:

```sh
cd beads/arch
makepkg --noconfirm
old_digest=$(sha256sum /usr/bin/bd | cut -d ' ' -f 1)
install -Dm755 /usr/bin/bd "$HOME/.local/lib/beads/backups/bd-$old_digest"
sudo pacman -U ./beads-1.3.1-1-x86_64.pkg.tar.zst
pacman -Qo /usr/bin/bd
/usr/bin/bd version
env -i HOME="$HOME" PATH=/usr/bin /bin/sh -c 'command -v bd; bd version'
```

The package installs its guarded /usr/bin/bd and pinned /usr/lib/beads/1.3.1/bd. The launcher checks the client version before forwarding arguments. Build outputs and downloaded archives are ignored; retain the prior executable and package if you need recovery. Future package changes should be intentional, reviewed and followed by the same invocation checks; do not replace the guard with an older upstream package. A recoverable old binary is a backup, never an invocation path for modern trackers.

On other machines, run the installer locally, verify interactive, login, SSH, cron, systemd and CI invocation paths before accessing shared trackers, and stop any old-client jobs. This rollout does not operate on other machines. Preserve each database before a designated `bd migrate schema --force`, compare issue IDs and counts, sync without force-pushing, then verify a fresh clone independently. Do not reset, blanket-import or drop tracker data to resolve divergence.

Local verification (2026-10-07): clean sh, zsh login and a transient user-systemd job execute 1.3.1. An actual SSH command through a temporary localhost-only sshd resolves /usr/local/bin/bd 1.3.1. A real scheduled cron job in an isolated BusyBox container executes the same host launcher and pinned binary through read-only mounts; no permanent cron or SSH service settings were changed. The initial restricted SSH PATH=/usr/bin check exposed the old package client. The package upgrade and repeated restricted-PATH SSH/cron checks pass: /usr/bin/bd is owned by beads 1.3.1-1, and both default and restricted paths report 1.3.1. A restricted-PATH transient user-systemd job also passed. Every bd executable on the inspected local PATH reports 1.3.1; the old package executable is preserved outside PATH under /usr/local/lib/beads/backups/bd-53ba32f152d882889e346bf73157f23ea938c46a7e69414f528df385dee3d932. Audited repository CI workflows do not invoke bd. Remote SSH hosts and CI runners require their own installation and verification.
