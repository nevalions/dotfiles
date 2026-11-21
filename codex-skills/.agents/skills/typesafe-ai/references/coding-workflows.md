# Jev inside a coding workflow

Depth for repository-shaped work: PR triage, CI gating, diff classification, review routing, log and
build-failure triage. Read this when the state is a diff, a stack trace, or a build log rather than
a customer message.

## Jev is not a coding agent

There is no model setting that turns Claude Code, Codex, opencode or Cursor into a Jev-powered
agent. The vendor says this directly on its coding-agents page. The two roles stack:

| Layer | Owns |
| - | - |
| Jev | judgments about the code: what a change touches, how risky it reads, whether a comment applies to this hunk |
| coding agent / reasoning LLM | writing the code, explaining the defect, navigating the repo, drafting the review comment |
| deterministic tooling | scanners, secret detection, syntax, semver math, advisory matching, test execution, merge policy |

"Jev labels, code merges." Never let an answer be the merge gate; let it route, rank, and pick the
queue.

## State for a diff

```json
{
  "diff": "<unified diff, changed hunks only>",
  "changed_paths": ["app/auth.py", "migrations/0031_drop_sessions.sql"],
  "issue": {"title": "...", "body": "..."},
  "computed": {"files": 3, "added": 41, "removed": 9,
               "dependency_deltas": [{"name": "pyjwt", "from": "2.8.0", "to": "2.10.0", "semver": "minor"}],
               "advisories": []},
  "ownership": {"app/auth.py": "platform-team"}
}
```

Send changed hunks and paths, not the repository: unrelated code in the state costs accuracy and
makes a wrong answer impossible to attribute. Anything code can compute exactly goes under
`computed` — semver classification, counts, advisory ids, changed symbols — because Jev does not
count, compare versions, or do arithmetic.

## Question set that discriminates

One Noul per property, all in a single request over the same state:

```json
{
  "changes_auth_or_access": "Does `diff` change who is allowed to do something, or how a caller is authenticated or authorized?",
  "changes_public_behavior": "Does `diff` change behavior that an external user or an outside service can observe?",
  "touches_persisted_data": "Does `diff` change the shape of stored data, or modify rows already stored?",
  "changes_deployment_or_config": "Does `diff` change how the service is configured, deployed, or scheduled?",
  "matches_stated_issue": "Does `diff` implement what `issue` describes?",
  "needs_new_tests": "Would a new test be needed to demonstrate the change in `diff` works?"
}
```

Then one Noul per test family (unit / integration / migration / e2e) rather than a single
"which tests" Choice, and combine in code with the hard rules you already have (a schema change
mandates a migration test whatever the probability says).

Do **not** model change kind as one Choice over `feature / bugfix / refactor / dependency_update`.
A real diff is frequently several of those at once and the Choice is forced to split. On a mixed
auth-plus-migration diff the taxonomy came back 0.40 feature / 0.42 bugfix at 0.27 confidence — the
signal there is "wrong instrument", not "pick the larger one". If the pipeline needs a change
kind, make each kind its own Noul.

## What the answers look like on code

Measured on one benign 35 KB commit (config and profile files only) against one synthetic risky
diff (auth check removed, destructive migration, dependency bump), same six questions:

- Atomic Nouls discriminate hard: `touches_persisted_data` 0.11 vs 0.98, `changes_auth_or_access`
  0.36 vs 0.93. This is the routing signal worth building on.
- A negative for a benign commit still landed at 0.36, above a 0.3 "no" line. Keep the third,
  unsettled row in the truth table; do not collapse to yes/no.
- The risk Score sits high: the benign commit scored position 1.09 with `{routine 0.08, elevated
  0.75, urgent 0.17}`. Treat Score output on code states as a relative ranking, not a policy
  number, and read the level probabilities.
- Cost is negligible: both requests together were about 10.7k input tokens with output free, so
  probing a whole PR corpus before committing to thresholds is cheap.

## Cascade and gating

1. Deterministic screen: changed paths, scanners, policy engines. These decide the cases they can
   decide and never consult the model.
2. One Jev request per PR for the property Nouls above.
3. Code maps the truth table to advisory labels, reviewer routing, and test selection.
4. Escalate to a reasoning LLM or a human only on the rows that say so (high-risk Nouls, Nouls in
the unsettled band, `matches_stated_issue` low).

Start advisory. Let anything blocking — a required reviewer, a blocked merge, an expanded suite —
earn that right from measured override rates and escaped defects, not from the first demo. Risky
actions get higher thresholds than advisory labels.

## Versioning and replay

- Keep question wording, options, and thresholds in one module, with a question-set version.
- Cache answers keyed by commit SHA + question-set version + model version, so a re-run of CI does
  not re-charge the model and a model upgrade is visible in the diff of results.
- Persist the exact request payload and the answer set per commit. That log is the calibration
  corpus: reviewer overrides, escaped defects, and per-question accuracy all come from it.
- An API failure is an error. Never degrade it to "no risk found".

## Other code-shaped judgments that work

- Review-comment and bot-output triage: does this finding apply to a changed hunk, is it blocking,
  is it a duplicate of one already posted.
- CI failure classification: flake, real regression, infrastructure, environment, dependency
  resolution — pass normalized fields (exception type, job name, service, recent change) rather
  than the raw log.
- Agent tool choice and argument filling, per the function-calling cookbook.
- Spec or issue drift: does this commit implement the ticket it references, does this doc section
  still describe the code it documents.
