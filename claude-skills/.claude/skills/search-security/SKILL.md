---
name: search-security
description: "Search latest security guidance and standards"
context: fork
agent: Plan
argument-hint: "<topic>"
---

Search the latest security guidance with `perplexity_search` (not `perplexity_research`, which runs for minutes and is reserved for deep multi-source investigation).

Focus on:
- Official standards (RFCs, W3C, OWASP, browser vendors)
- Recent changes or deprecations
- Real-world pitfalls

Output:
- Short summary
- Do / Don't list
- What has changed recently
- Actionable recommendations for a production system

Topic:
$ARGUMENTS
