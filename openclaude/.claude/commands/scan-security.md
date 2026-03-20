---
description: "Run Semgrep mcp security scan and file results to Vikunja (plan only, no code changes)"
agent: "plan"
---

Run a security scan with semgrep mcp of this repository using Semgrep MCP.

Requirements:
- Prefer high-signal rules (avoid noisy style-only findings).
- Focus on: auth/authz, injection, secrets, SSRF, path traversal, insecure crypto, misconfigurations.
- If possible, use a standard Semgrep ruleset appropriate for the stack (FastAPI/Python and Angular/TS if present).

After scanning:
1) Summarize findings (counts by severity and category).
2) Create a Vikunja parent task in the appropriate project:
   - If this is a frontend repo, use the frontend project.
   - If this is a backend repo, use the backend project.
   Title: "Security scan findings (Semgrep)"
3) Create child tasks (or a checklist under the parent) grouped by:
   - severity (Critical/High/Medium/Low)
   - and category (e.g. injection, auth, secrets)
4) For each finding include:
   - Semgrep rule id and message
   - File path and line numbers
   - Why it matters (brief)
   - Recommended remediation (safe and minimal)
   - Verification steps (tests, repro, or how to validate)
5) Do NOT change code. Do NOT auto-fix.

Finally, propose an execution order that minimizes risk (secrets/exploitable issues first, refactors last).
