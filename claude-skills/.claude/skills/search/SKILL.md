---
name: search
description: "Web-backed research via Perplexity. Modes: /search <query>, /search plan <topic>, /search ecosystem <topic>, /search security <topic>"
context: fork
agent: Plan
argument-hint: "[plan|ecosystem|security] <topic>"
---

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

Arguments:
$ARGUMENTS
