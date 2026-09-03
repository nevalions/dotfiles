---
name: search-plan
description: "Search a topic with Perplexity, extract rules and constraints, and propose a safe plan"
context: fork
agent: Plan
argument-hint: "<topic>"
---

First, search the following topic with `perplexity_search` (not `perplexity_research`, which runs for minutes and is reserved for deep multi-source investigation).

Then:
- Extract concrete rules or constraints
- Propose a safe implementation plan
- Identify what should NOT be automated
- List verification steps

Topic:
$ARGUMENTS
