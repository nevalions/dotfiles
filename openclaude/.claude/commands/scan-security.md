---
description: "Run Semgrep mcp security scan and file results to bd/beads (plan only, no code changes)"
agent: "plan"
---

Run a security scan with semgrep mcp of this repository using Semgrep MCP.

Requirements:
- Prefer high-signal rules (avoid noisy style-only findings).
- Focus on: auth/authz, injection, secrets, SSRF, path traversal, insecure crypto, misconfigurations.
- If possible, use a standard Semgrep ruleset appropriate for the stack (FastAPI/Python and Angular/TS if present).

After scanning:
1) Summarize findings (counts by severity and category).
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
6) Do NOT change code. Do NOT auto-fix.

Finally, propose an execution order that minimizes risk (secrets/exploitable issues first, refactors last).
