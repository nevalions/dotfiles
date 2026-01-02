# Base Agent Instructions (Global)

These instructions apply to all projects unless explicitly overridden
by a project-specific agents.md.

---

## Mandatory

As an autonomous agent you will:

1. Call vibe_check agter planning and before major actionns.
2. Provide the full user request and your current plan.
3. Optionally, record resolved issues with vibe_learn.

---

## Canary

AGENTS_MD_GLOBAL_LOADED

---

## GitHub (solo owner)

- Assume the user is the repository owner.
- GitHub write actions are allowed when explicitly requested.
- Do not modify repository settings or secrets unless explicitly stated.
- Prefer planning before execution for PRs and merges.
- Always link related Linear issues when applicable.
- Never auto-merge unless CI is green.

---

## Semgrep usage

- Use Semgrep MCP for:
  - Security scanning
  - Code pattern detection
  - OWASP and framework-specific issues
- Prefer Semgrep before manual security review.
- Do not auto-fix findings unless explicitly instructed.
- Create Linear issues for medium/high severity findings.

**Arch Linux installation:**

```bash
pipx install semgrep
```

---

## Context7 usage (official documentation)

Use **Context7 MCP** as the **primary source** for:

- Official framework documentation
- Library APIs and configuration
- Idiomatic usage patterns
- Version-accurate guidance

Examples:

- FastAPI routing, dependencies, lifespan
- SQLAlchemy async sessions and transactions
- Angular, NgRx, ESLint rules
- Postgres configuration and SQL behavior

Context7 SHOULD be used when:

- Implementing or modifying code
- Verifying API correctness
- Following framework-recommended patterns

Context7 SHOULD NOT be used for:

- Ecosystem comparisons
- Release/news tracking
- Security advisories outside official docs
- Opinionated or forward-looking guidance

If Context7 information is insufficient or outdated, explicitly switch to Perplexity.

---

## Perplexity usage (web-backed research)

Use **Perplexity MCP** only when up-to-date or web-based information is required.

Examples:

- Security standards and guidance (CSP, OAuth, OWASP, browser changes)
- Ecosystem updates (framework releases, breaking changes, migrations)
- Accessibility standards and tooling
- Comparative analysis (tool A vs tool B)

Do NOT use Perplexity for:

- Reading or understanding the local codebase
- Implementing framework APIs when official docs are already available locally
- Guessing versions, APIs, or defaults

Always summarize conclusions clearly and avoid speculation.

---

## Research commands

Prefer the following commands over ad-hoc questions:

- **/research-plan**  
  Research a topic using Perplexity, then:
  - Extract concrete rules or constraints
  - Propose a safe implementation plan
  - Identify what should NOT be automated
  - List verification steps

- **/research-ecosystem**  
  Research the current state of a tool or framework:
  - Check release notes and recent announcements
  - Identify breaking changes
  - Identify recommended defaults
  - Note migration considerations

- **/research-security**  
  Research latest security guidance:
  - Prefer official standards (RFCs, W3C, OWASP, browser vendors)
  - Note recent changes or deprecations
  - Provide Do / Don’t lists and production recommendations

- **/research**  
  General up-to-date research using authoritative sources.

---

## Source prioritization

When multiple sources are available, prefer in this order:

1. Official standards and specifications
2. Official framework or vendor documentation
3. Widely accepted community guidance
4. Blogs and secondary commentary (clearly marked as such)

Always call out uncertainty or disagreements between sources.

---

## Output expectations

When Perplexity is used:

- Provide a short summary first
- Include actionable recommendations
- Clearly separate facts from opinions
- Avoid inventing APIs, versions, or guarantees

---

## Safety & integrity

- Never fabricate citations, standards, or release notes
- Never assume security posture without verification
- When unsure, say so and propose a validation step

---

## User Notes

- Do not add AGENTS.md to README.md - this file is for development reference only.
- All commits must be by linroot with email nevalions@gmail.com
