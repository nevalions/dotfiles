---
name: search
description: "General web-backed search using Perplexity"
context: fork
agent: Plan
argument-hint: "<query>"
---

Search the following with `perplexity_search` (not `perplexity_research`, which runs for minutes and is reserved for deep multi-source investigation).

Requirements:
- Prefer official docs, specs, or authoritative blogs
- Include practical recommendations
- Note any disagreements or trade-offs

Question:
$ARGUMENTS
