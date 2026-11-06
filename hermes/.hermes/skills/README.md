# Hermes skills

Hermes ships its bundled skills into this directory and manages them with
`hermes update`; they are not tracked in dotfiles.

Custom skills belong here anyway, one directory per skill:

```
hermes/.hermes/skills/<category>/<skill-name>/SKILL.md
```

Create them with `skill_manage` while running Hermes (it writes through the
stow link into this repo) or by hand, then re-run `stow hermes`. Stow folds
each skill directory into a single link, so files a skill adds later stay in
the repo too.
