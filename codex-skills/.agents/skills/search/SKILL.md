---
name: search
description: 'Web-backed research via Perplexity. Modes: $search query, $search plan
  topic, $search ecosystem topic, $search security topic'
---

## Model selection

Default: `gpt-6.1-sol / medium` (standard). Exact factual lookup: easy; security or conflicting evidence: review. Apply the task routes and runtime limits in `~/.codex/model-policy.md` when available; skill text does not switch the session model.



Research with `perplexity_search` (not `perplexity_research`, which runs for minutes and is reserved for deep multi-source investigation). Prefer official standards and docs over community posts and blogs; note disagreements and trade-offs.

If the first word of the arguments is `plan`, `ecosystem` or `security`, that is the mode and the rest is the topic. Otherwise it is a general query.

## general

Answer the question with practical recommendations and sources.

## plan

Extract concrete rules and constraints, propose a safe implementation plan, say what should NOT be automated, and list verification steps.

## ecosystem

Check release notes and recent announcements: breaking changes, recommended defaults, migration considerations. Output: TL;DR, adopt now, avoid, migration notes.

## security

Focus on official standards (RFCs, W3C, OWASP, browser vendors), recent changes or deprecations, and real-world pitfalls. Output: short summary, do / don't list, what changed recently, actionable recommendations for a production system.

Use the arguments supplied with `$search` as the mode and topic.

## When the runtime has no perplexity tool

Some runtimes expose no `perplexity_search` (Hermes, for one, ships `web_search` on a different
backend). Do not substitute a generic search scrape — the prose answer plus `citations[]` is what
makes the modes above work. Call the same backend over HTTP:

```bash
set -a; . ~/dotfiles/opencode/.config/opencode/.env; set +a   # PERPLEXITY_API_KEY
curl -sS -m 120 https://api.perplexity.ai/chat/completions \
  -H "Authorization: Bearer $PERPLEXITY_API_KEY" -H "Content-Type: application/json" \
  -d '{"model":"sonar-pro","messages":[{"role":"system","content":"Be concrete and cite sources."},{"role":"user","content":"<query>"}],"search_recency_filter":"year"}' \
  -o /tmp/pplx.json -w "%{http_code}\n"
```

Read the answer from `choices[0].message.content` and the sources from `citations[]`; relay the
citations, since they are the part the reader can check. Write the key into a subshell
(`set -a; . file; set +a`) rather than echoing it. `sonar-pro` is the workhorse; pass a
`search_recency_filter` whenever the question turns on current releases or defaults, because
without it the model answers from whatever it already believes.
