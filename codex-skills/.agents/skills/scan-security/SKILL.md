---
name: scan-security
description: Use when a repository security scan or security review is requested or necessary for the task. Finding remediation and issue filing require authorization.
---

## Authorization

Automatic selection loads this workflow; it does not authorize mutations. Execute only the Git stages, remote writes, release actions, or issue filing covered by the user’s request and applicable repository instructions. Complete authorized read-only preparation before seeking any missing authorization.

## Model selection

Default: `gpt-6.1-sol / high` (review). Scanner execution/counts only: easy; hardest threat reasoning: deep. Apply the task routes and runtime limits in `~/.codex/model-policy.md` when available; skill text does not switch the session model.



Run a security scan of this repository with the `semgrep` CLI. Prefer the repo's own entry point when it has one (`make security-scan`, `scripts/semgrep-scan.sh`, `scripts/pre-push-security.sh`); otherwise `semgrep scan --config auto --json --quiet .`.

Requirements:
- Use a standard Semgrep ruleset for the stack (FastAPI/Python and Angular/TS where present) with high-signal rules; skip style-only findings.
- Focus on: auth/authz, injection, secrets, SSRF, path traversal, insecure crypto, misconfigurations.

After scanning:
1) Summarize findings (counts by severity and category).
   Continue to issue filing only when the user has authorized recording the findings in bd; otherwise report findings and stop before steps 2–5.
2) Confirm bd is initialized here (`bd ready` or a `.beads/` dir). If not, note it and skip filing.
3) Create a bd (beads) parent issue in this repo and capture the returned id:
   `bd create "Security scan findings (Semgrep)" -l security -p 1`
4) Create one child issue per finding (or grouped by category), linked to the parent:
   `bd create "<finding title>" --parent <parent-id> -l security,<category> -p <0-4>`
   bd priority is 0=highest — map Critical→0, High→1, Medium→2, Low→3.
5) For each finding include in the description (`-d`, plain text/markdown):
   - Semgrep rule id and message
   - File path and line numbers
   - Why it matters (brief)
   - Recommended remediation (safe and minimal)
   - Verification steps (tests, repro, or how to validate)

Finally, propose an execution order that minimizes risk (secrets/exploitable issues first, refactors last).
