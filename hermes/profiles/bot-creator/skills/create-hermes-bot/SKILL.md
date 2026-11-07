---
name: create-hermes-bot
description: Design and validate Hermes bots and their skills.
---

# Create a Hermes Bot

## When to Use

Use when asked to design, create, refine, or package a Hermes bot,
including its description, SOUL, skills, model, and required tools.

For a request for text or templates, return copyable artifacts.
Install or modify a profile only when that action is requested.

## Procedure

### 1. Define the Job

Identify:

- Who will use the bot.
- Its recurring tasks.
- Required inputs and expected outputs.
- Operations outside its scope.
- What successful behavior looks like.
- Whether the user wants a draft, installation, or update.

Use existing conversation context before asking questions.

Distinguish a Hermes profile, a Desktop bot entry, and a messaging bot
when the requested setup depends on that distinction.

### 2. Inspect Existing Components

Read applicable global and project instructions.

For dotfiles, synchronization, or cross-machine packaging, inspect the user's
existing Claude, Codex, and Hermes Stow packages and installer scripts before
proposing a layout. Prefer extending one existing deployment implementation
with tool-specific handlers over introducing a parallel sync system. Read the
repository's current instructions rather than copying its policies into this
skill. Follow [Dotfiles deployment](references/dotfiles-deployment.md) for
inspection order, symlink boundaries, and profile-target checks.

Discover relevant profiles and skills when access is available.
Read matching skills before proposing duplicates.

In this environment, potential existing components include:

- wiki-skill
- repo-scout
- feature-wiki
- committer
- skill-creator
- beads-coordinator

Verify their existence and capabilities. Names in conversation do not
prove installation.

Prefer:

1. Reusing a suitable component.
2. Improving an existing component within authorized scope.
3. Creating a new component with a distinct responsibility.

### 3. Establish Capabilities

Prepare a compact table:

| Capability | Tool, plugin, or skill | Status | Evidence or gap |
|---|---|---|---|

Distinguish:

- Available in the current session.
- Configured but not runtime-verified.
- Proposed dependency.
- Unavailable.

Inspect actual tool schemas and relevant installed-version help.
Consult official Hermes documentation when needed.

Never invent tool names, arguments, plugin identifiers, configuration
keys, or installation commands.

Verify availability in the intended profile. Another profile's tools
do not establish availability here.

Keep credential values out of inspection output.

### 4. Design the Bot

Place:

- Identity, values, and communication style in SOUL.md.
- Reusable procedures in skills.
- Models, providers, tools, and plugins in runtime configuration.
- Project-specific conventions in their maintained instruction sources.

Choose a model and reasoning effort appropriate to the work, not the model
used by the authoring assistant. For routine dotfiles synchronization and
installer maintenance, prefer Kimi Code for this user rather than inheriting
Astra; honor any explicit choice for the current bot. Verify the installed
provider/model identifiers before configuring them.

When the user changes the model, update both the live target profile and its
tracked defaults, then rerun the bounded smoke test on the selected provider.
A successful test on the previous model does not verify the replacement.
Check authentication in the consumer profile without exposing secrets; ask
before reusing another profile's credentials, and never substitute a different
model merely to make the test pass.

If the requested model is unavailable, report that fact rather than
silently substituting another model.

Skill prose does not change the running model.

Avoid adding multiple bots when one focused bot with a small skill set
can handle the workflow.

### 5. Create or Reuse Skills

Reuse author-skills when available for substantial skill authoring.

For each new skill, include:

- Valid name and description frontmatter.
- Clear activation conditions.
- Required inputs and prerequisites.
- Concrete procedure and decision points.
- Failure handling.
- Authorization boundaries.
- Output expectations.
- Meaningful verification.

Keep common instructions in SKILL.md.
Add references, scripts, or assets only when they serve a specific need.

Do not assume delegation or tool access exists merely because a skill
mentions it.

For Beads, follow the current canonical shared Beads skill:

- Tracking authorization.
- An actor unique to each session and stable within that session, never one shared identity across concurrent sessions.
- Atomic claims.
- Shared-worktree tracker discovery.

If canonical Beads instructions cannot be located, report the missing
prerequisite rather than inventing tracker-discovery or claim procedures.

When correcting an existing bot's procedure, inspect both its skills and
SOUL for contradictory wording. Updating this bot-authoring skill or a new
template alone does not apply that correction to the existing bot. Report
instruction changes separately from runtime enforcement and tracker changes.

For Git delivery, follow maintained Git and CI instructions.
Do not embed outdated copies of global policies.

### 6. Deliver the Package

Provide:

- Bot name and concise description.
- Recommended model and effort.
- Complete SOUL.md.
- Reused skills and complete new or changed skill contents.
- Required tools and plugins with availability status.
- Relevant destinations or verified setup instructions.
- Validation results and remaining requirements.

Label proposed configuration clearly.
Do not generate extra metadata files unless Hermes or the requested
distribution format requires them.

### 7. Install or Update When Requested

Resolve the exact target profile before writing. Distinguish the profile
that authors the package from the profile that must consume its skills;
installing into the authoring profile does not equip the target bot. Verify
the required skill files in the consumer's actual skill directory before
investigating chat refresh or restart behavior.

Inspect existing contents and preserve unrelated:

- Configuration.
- Skills.
- Memories.
- Sessions.
- Credentials.

Apply focused changes using supported management mechanisms.
Do not replace the entire profile or copy credentials by default.

Follow applicable repository isolation rules for tracked changes.

Installing a bot does not authorize connecting messaging accounts,
sending messages, publishing artifacts, or executing its task workflows.

Follow the installed version's reload or restart requirements.
Verify tools in the target profile's fresh runtime. Use a bounded read-only
smoke test that explicitly preloads the intended skill, executes a harmless
tool action, and checks an authorization boundary; a bot's self-description
alone is not evidence that its tools or skill loading work. Report profile
runtime verification separately from Desktop roster registration.

If a running process still requires restarting, report that limitation.
Do not claim activation from configuration changes alone.

## Pitfalls

- Instructions cannot supply missing runtime capabilities.
- Existing names do not prove installed profiles or skills.
- A profile may require additional registration for a particular UI.
- Broad skills activate for unrelated requests.
- Duplicated policies become stale and contradictory.
- Static validation does not establish successful runtime behavior.

## Verification

Perform applicable structural checks:

- Frontmatter parses.
- Names and paths are correct.
- Existing skill names do not collide.
- Referenced resources exist.
- Dependencies are available or explicitly identified as missing.
- Persona, procedure, and configuration remain separated.
- No secrets or unrelated changes are included.

Evaluate representative scenarios:

- A normal request produces the intended result.
- An overlapping request reuses existing capabilities.
- Missing tools produce a clear limitation.
- A draft-only request causes no installation.
- An update preserves unrelated profile contents.
- Tracker and Git operations respect ownership and requested stages.

For an installed bot:

- Confirm the selected profile.
- Verify actual model and tool availability.
- Load the intended skills.
- Run a harmless representative task when authorized.

Separate checks performed from proposed tests.

## Completion

Report:

- What was drafted or changed.
- What was installed, if applicable.
- Checks performed and observed results.
- Missing dependencies or untested behavior.

Do not claim the bot is ready until the required runtime checks support it.

This separation follows Hermes’ profile guidance, SOUL conventions, and skills format.
