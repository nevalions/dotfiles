---
name: search-ecosystem
description: "Search the current ecosystem state for a tool or framework"
context: fork
agent: Plan
argument-hint: "<topic>"
---

Search the current state of the ecosystem with `perplexity_search` (not `perplexity_research`, which runs for minutes and is reserved for deep multi-source investigation).

Requirements:
- Check release notes and recent announcements
- Identify breaking changes
- Identify recommended defaults
- Note migration considerations

Output:
- TL;DR
- What to adopt now
- What to avoid
- Migration notes

Topic:
$ARGUMENTS
