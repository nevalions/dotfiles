# Claude skills

Agent skills for Claude Code, stowed into `~/.claude/skills/`.

```bash
stow -t ~ claude-skills
```

Stow folds into the existing `~/.claude/skills/`, so only the skills listed here
are symlinked; skills installed by other means are left untouched.

Skills load into every session, so an upstream edit is a silent change to agent
behaviour with no review prompt. Vendored skills are therefore committed to this
repo and pinned below. Git is the review gate.

## Vendored skills

| Skill | Upstream | Pinned commit | SKILL.md sha256 | Adopted |
|-------|----------|---------------|-----------------|---------|
| `herdr` | [ogulcancelik/herdr](https://github.com/ogulcancelik/herdr) | `1491b7dd9c992ef0ad2b763f3e450befaf25c47f` | `0786182f02ebf92708e09d82d79e4614d1a9c30bfc337643cc2af1d0fb9db29f` | 2026-07-28 |

Installed by hand rather than via skills.sh: `SKILL.md` sits at the upstream repo
root, so the installer would have copied the whole 42M repository (Rust sources,
`vendor/`, four `package.json` manifests) into the skill directory. Only the
single markdown file is needed.

## Updating a vendored skill

```bash
curl -fsSL https://raw.githubusercontent.com/<upstream>/main/SKILL.md \
  -o claude-skills/.claude/skills/<name>/SKILL.md
git diff                     # read the change before adopting it
sha256sum claude-skills/.claude/skills/<name>/SKILL.md
```

Update the pin above, then commit. Skills are read at session start, so restart
Claude Code to pick up changes.
