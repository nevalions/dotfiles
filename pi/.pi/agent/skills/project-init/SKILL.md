---
name: project-init
description: Set up Pi guidance for an existing Git repository. Use to create or update root AGENTS.md with project context, repository conventions, and evidence-backed setup and validation commands.
disable-model-invocation: true
---

# Initialize Pi project guidance

This workflow documents an existing project. It does not scaffold an app, install tooling, or configure Pi extensions, credentials, or services.

1. **Identify the project.** Resolve the Git root from the requested directory or current checkout. If there is no Git root or the intended repository is unclear, ask before proceeding. Check the working tree and read applicable `AGENTS.md` files, including any root file and scoped files relevant to the requested area. Follow existing repository instructions, including any task worktree requirement. Preserve unrelated changes and do not edit nested guidance.
2. **Inspect without running project code.** Use tracked files to locate the README, contributor docs, manifests and lockfiles, task runners, and CI definitions. Identify the main components, their locations, required tools, and supported setup, build, test, lint, and format commands. Cross-check working directories, flags, and prerequisites against actual scripts or CI. If sources disagree, report the conflict rather than guessing. Do not read secrets or copy private host details into guidance.
3. **Draft only what an agent needs.** Propose a concise root `AGENTS.md` or a focused patch to the existing one. Include a short repository map, routine developer commands with their working directories and prerequisites, and project-specific constraints or conventions backed by repository evidence. Link to canonical docs instead of duplicating them. Preserve existing wording and structure where practical; if guidance is already sufficient, report that and propose no change. For each proposed command, state its evidence and whether it was run successfully, failed, or was not run. Finding a command in CI is not the same as running it.
4. **Get approval before writing.** Show the exact proposed content or diff and the evidence for it. Ask for explicit approval before applying it (use `ask_user` where available). If an interactive answer is unavailable, stop at the proposal. Do not install dependencies, start services, make network calls, or run commands with unclear side effects just to verify guidance. If execution is useful, review the commands and seek separate approval for any such side effects.
5. **Apply and check.** After approval, recheck for concurrent changes and apply only the agreed root `AGENTS.md` edit. Inspect the resulting diff (or read back a new file), check whitespace, and confirm documented paths and command targets exist where applicable. Report the path, what was validated, and what remains untested. Do not commit or push unless separately requested.
