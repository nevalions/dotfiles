---
name: bot-delegation
description: "Use when triggering or delegating to another Hermes bot."
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [bots, profiles, delegation, chat, oneshot]
    related_skills: [hermes-agent]
---

# Delegate to a Hermes Bot Profile

## When to Use

Activate for "trigger a bot", "delegate to a bot", "message another profile", or "run another bot" when the target is a Hermes profile, locally or on a registered peer.
Do not activate for ordinary human messaging, creating a bot, scheduling a routine, or generic subagent delegation without a profile target.

## Prerequisites and Boundaries

Identify the exact target profile or peer/agent, authorized task, context, deliverable path, and acceptance checks. Confirm local names with `hermes profile list`; do not create a profile to compensate for a typo. Ask only for missing information that changes routing or scope.

Follow the team convention: message the target profile to perform its work rather than doing that work in the default profile. A generic `delegate_task` child is not evidence of messaging that named profile. Do not delegate beyond the user's authority or a restricted bot's access boundaries. Authoring these instructions does not authorize launching a bot.

## Procedure

### 1. Choose an available transport

- In Bot Mode, @mentions resolve to agent profiles, but the relay depends on the `message_agent` tool. Inspect the current session's exposed tools: it is not always present and was absent in the validated default desktop session. If absent, agent messaging through that path is unavailable. Do not invent a tool call or claim that typing an @mention delivered a message. If present, inspect its actual schema before invoking it.
- For a local profile, use the working one-shot mechanism below. No `message_agent` tool is required.
- For another machine, use the peer transport under Cross-machine variant. Do not confuse a local profile name with a registered peer name.

### 2. Compose a fully self-contained message

Assume the target knows nothing of this conversation. Include:

- Task and all required background, input locations, and literal identifiers.
- Exact deliverable, absolute output path, and requested format.
- Scope limits, allowed side effects, and operations explicitly excluded.
- Verification commands or observable acceptance criteria.
- A request to return the artifact path or external handle, checks actually run, and any failure or blocker.

Do not use "as discussed" or rely on chat attachments the target cannot access. Local paths on your machine are not automatically available on a remote peer. Keep credentials out of prompts.

### 3. Launch the local profile one-shot in the background

Confirm flags with `hermes --help`, then run:

```bash
hermes -p <profile> -z "<message>"
```

This is the local twin of `hermes -p <profile> chat`. `-z/--oneshot` sends one prompt and prints ONLY the final response text to stdout, not the banner, spinner, or tool previews. Treat stderr and a nonzero exit separately from the final answer. Tools, profile rules, memory, and working-directory instructions still load. One-shot automatically bypasses approvals: constrain the prompt and working directory to the authorized task; do not treat it as a sandbox.

For long messages, write the body with the available file-writing tool to a file in the session's scratch directory, then pass it as one quoted argument:

```bash
hermes -p <profile> -z "$(cat /path/to/msg.txt)"
```

Backticks, quotes, and dollar signs inside the file survive this quoted command substitution as data; they are not re-evaluated as shell syntax. Quote the file path inside the substitution if it contains spaces. Command substitution strips trailing newlines and command-line size limits still apply. Do not interpolate raw message text into shell source or use `eval`. The direct short-message form requires normal shell escaping.

Invoke the actual terminal tool with the composed command and explicit settings:

```text
terminal(command='hermes -p <profile> -z "$(cat /path/to/msg.txt)"', background=true, notify=true)
```

Use a suitable authorized working directory; save the returned `session_id`. This is a tool-call illustration, not a shell command.

### 4. Wait without launching a duplicate

Discover/load `process_manage` if necessary. Wait on the returned ID:

```text
process_manage(action="wait", session_id="<returned-id>", timeout=180)
```

The validated runtime clamps waits to 180 seconds regardless of a larger requested timeout. Installed implementations may derive that cap from `TERMINAL_TIMEOUT` (180 by default); inspect the returned clamp note rather than assuming a longer request works. A wait timeout is not process failure and does not itself stop the bot. Repeat `wait` or `poll` on the same session until exit, an actual error, cancellation, or the authorized deadline. Do not resubmit a task merely because one wait expired. Report ongoing work honestly if it remains running.

### 5. Independently verify the result

Read the process output and exit status, then inspect the actual deliverable. A bot's self-report, even with exit code zero, is not proof of its side effects.

For disk artifacts, verify the exact path exists and read the content; compare it with the requested format, scope, and acceptance checks. For external changes, read back the exact target using its returned URL or ID. Remote filesystem paths require an authorized remote read mechanism; if unavailable, report the result as unverified rather than claiming success. Stop and report blockers or partial results; do not fabricate missing output or blindly retry operations that might duplicate effects.

Report the target profile/peer, actual artifact path or handle, independent checks, and unresolved limitations.

## Cross-machine Variant

Confirm syntax with `hermes peer --help`, `hermes peer dm --help`, and `hermes peer add --help`.

```bash
hermes peer list
hermes peer add <name> --url http://host:port --key <API_SERVER_KEY>
hermes peer dm <peer>[/<agent>] "<message>"
```

Registered peers may be empty by default; inspect rather than assuming registration. The destination must run the `api_server` platform and be registered first. `<peer>/<agent>` selects a named agent on a multiplexed peer; `<peer>` uses that peer's default target. Register or change credentials only when authorized. Treat the key as a secret; placeholders are not usable credentials, and command-line keys may be visible in process lists/history. Use the environment's approved secret handling, and prefer a trusted encrypted connection outside a trusted local network.

Apply the same self-contained prompt, quoted file substitution for long messages, background launch (`background=true`, `notify=true`), wait loop, and independent verification. If no peer is registered or the server is unreachable, report that prerequisite rather than claiming delivery.

## Cross-profile Skill Installation

`skill_manage` writes only to the ACTIVE profile's skills tree; it does not install into another profile. Confirm the real destination and inspect existing contents before copying. Do not overwrite a competing skill silently.

For an authorized named-profile installation, copy the complete package into an existing category directory:

```bash
cp -r <skill-dir> ~/.hermes/profiles/<name>/skills/<category>/
```

For the DEFAULT profile, the destination is different:

```bash
cp -r <skill-dir> ~/.hermes/skills/<category>/
```

Ensure the destination category exists and the resulting skill directory is not accidentally nested inside an existing copy. Verify every copied file against the source, including supporting resources, and report the exact on-disk path. Installation on disk is distinct from discovery in an already-running chat.

## Review Cases

- Positive: "Delegate to a bot: ask reviewer to inspect /absolute/repo and write /absolute/report.txt." Resolve `reviewer`, send complete context, wait, and independently inspect that report.
- Negative: "Message my teammate on Slack." Do not route this through a bot profile.
- Missing-tool edge: an @mention with no `message_agent` must not be reported as delivered; use authorized local one-shot when applicable.
- Timeout edge: a wait expires while the process is running; wait again on the same ID, not a new launch.
- Verification edge: the bot says "file written" but the file is absent or wrong; report failure or incomplete work, not success.
