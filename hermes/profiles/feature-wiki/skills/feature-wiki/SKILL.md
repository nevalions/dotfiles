---
name: feature-wiki
description: Document implemented features from code and wiki context.
---

# Feature Wiki

## When to Use

Use when asked to explain or document an implemented repository feature:
what it does, how it works, and what evidence explains its design.

Use repo-scout for initial repository orientation.
Use this skill for deeper investigation of bounded capabilities.

Default wiki:
 /home/linroot/vault/linroot-wiki-code

Create or improve pages in this existing vault.
Do not create a separate vault unless requested.

## Inputs

Required:
- A repository identity or existing repo-scout page.

Optional:
- A specific feature or question.
- A target revision.
- Owner-provided usage or design context.
- Authorization to ingest the resulting evidence.

## 1. Read Existing Knowledge

Read the vault's AGENTS.md, SCHEMA.md, and RW/index.md.

Find and read:
- The repository entity.
- Its repo-scout source briefing.
- Related feature topics.
- Relevant source references.

Search for existing coverage before proposing new pages.

Distinguish a wiki lookup from an implementation investigation. For a request
to check a project from the wiki, answer from existing pages with wikilinks
and state their revision and verification limits; do not imply that current
code was checked. For a feature investigation or explicit invocation of this
skill with a repository identity, continue through snapshot verification and
one bounded code trace. Neither mode authorizes ingestion by itself.

Obtain the repository location and scout revision from evidence.
Verify the repository identity rather than assuming a matching folder name
is sufficient.

## 2. Select the Feature

Use the feature named by the user.

If none is named, prepare a short candidate list from the scout and code:
- Feature name and user-visible behavior.
- Likely entry points.
- Existing wiki coverage.
- Important evidence gaps.

Choose one bounded feature for the first investigation unless the user
requested a batch.

Prefer capabilities over arbitrary files or directories.
Do not create a page for every class or function.

## 3. Establish the Snapshot

Inspect Git state using read-only operations. Batch the initial checks:
`git -C <repo> remote -v`, `git -C <repo> rev-parse HEAD`, and
`git -C <repo> status --short`. Compare the remote and full SHA with the wiki's
evidence before reading implementation files. Recheck status at completion
when reporting that the inspection left the repository unchanged.

Record:
- Repository identity.
- Full inspected commit SHA.
- Relevant uncommitted changes.
- Scout revision and any difference from the inspected revision.

When revisions differ, inspect the scout revision or explicitly document
the newer implementation. Never silently mix evidence from different
revisions.

Use commit, repository-relative path, and symbol or line references
for implementation evidence.

A HEAD SHA does not identify uncommitted file contents.
Mark such evidence separately.

## 4. Trace the Implementation

Follow the relevant execution path:

1. Trigger: UI interaction, API route, CLI command, job, or library call.
2. Input parsing, validation, permissions, and feature flags.
3. Business logic and significant transformations.
4. State changes, persistence, and external calls.
5. Output and observable behavior.
6. Failures, retries, cleanup, and limits.
7. Tests and the behavior they assert.

Mark irrelevant layers as not applicable.
Do not invent architectural components to fill the outline.

Distinguish active paths from unused code and documentation-only claims.

For asynchronous jobs, downloads, or other background-work features, use
[the background lifecycle checklist](references/background-lifecycles.md)
to distinguish persisted state from process-local progress, recovery from
cancellation, and authentication from resource ownership.

Read selectively with file listings and targeted searches.
Exclude generated output, dependencies, binaries, and secret material
unless a specific authorized investigation requires otherwise.

Do not execute tests or application code by default.
When execution is authorized, record commands, environment limitations,
and observed results.

## 5. Investigate Why

Look for rationale in:
- Design documents and architecture records.
- Relevant comments.
- Narrowly scoped commit history.
- Available issue or PR discussions.
- Owner-provided explanations.

Separate:
- Documented rationale, with attribution.
- Implementation constraints supported by code.
- Your interpretation, labeled Synthesis.
- Unknown intent.

Do not present a commit message or comment as unquestionably current.
Check whether the implementation still matches it.

Preserve contradictions instead of silently choosing one account.

## 6. Draft the Feature Report

Use this structure:

# <Feature>

## What It Does
Behavior, inputs, outputs, and intended use.

## Implementation Snapshot
Repository, revision, scout revision, and local-change limitations.

## How It Works
Execution flow, components, state changes, and dependencies.
Include source locators.

## Why This Design
Attributed rationale, constraints, and separately labeled interpretation.
State when rationale is unknown.

## Configuration and Limits
Relevant settings, defaults, restrictions, and assumptions.
Never include secret values.

## Failure Behavior
Errors, retries, recovery, cleanup, and observable failure outcomes.

## Tests and Verification
Separate inspected tests, executed checks, and reported results.

## Evidence
Important claims mapped to revision-pinned source references.

## Open Questions
Missing context, contradictions, and useful follow-up work.

## Related
Existing project, source, and topic pages.

Keep code excerpts short and purposeful.
Use a small diagram when it explains a nontrivial flow more clearly.

## 7. Respect Source Intake

Follow the vault's current ingestion rules before writing pages.

Read AGENTS.md for raw-source location permissions before applying schema
intake defaults. In this vault, RO/ is one possible raw-input location, not
an exclusive requirement. When ingestion is requested, agents may archive
raw investigation evidence under RW/ and ingest from the durable artifact;
no separate exception is required solely for its location. Separate raw
artifacts from derived pages and record exact paths, revision, provenance,
and verification limitations. Never write RO/ or invent a source path.

Do not treat this permission as authorization to skip the review checkpoint,
modify source repositories, or ingest unrelated material. Follow any stricter
user-specified limits for other vaults or external-source locations.

If ingestion is not authorized or source intake is incomplete, return
the report and proposed page changes in the conversation.

When ingestion is authorized:
- Read selected raw sources completely.
- Follow the required review checkpoint.
- Record exact durable source paths, provenance, and portability limitations; record any actual permission exception, but do not treat location outside RO/ alone as requiring one under this vault's policy.
- Do not skip review unless the user authorized that workflow.

## 8. Update the Wiki

Follow SCHEMA.md exactly.

Use:
- RW/sources/ for newly ingested evidence.
- RW/topics/ for feature mechanisms.
- RW/entities/ for project relationships.
- RW/synthesis/ for cross-feature conclusions.

Do not introduce a new page type.

Create a new source page for new evidence when required.
Do not attribute new code findings to an old scout report that does not
contain them.

Update an existing topic when it already owns the feature.
Use lowercase kebab-case names consistent with the vault.

Include schema-required frontmatter, Sources, and Related sections.
Use actual operation dates and real supporting source paths.

Maintain:
- Forward and reverse links.
- RW/index.md entries and counts.
- An appended operation in RW/log.md.

Preserve log history and unrelated content.

## Verification

Before claiming completion, check:
- Important factual claims have supporting evidence.
- Rationale is attributed or explicitly uncertain.
- Revision differences and local changes are disclosed.
- Existing pages were reused where appropriate.
- Frontmatter matches the current schema.
- Source paths and wikilinks resolve.
- Reverse links and index counts are consistent.
- Log changes are append-only.
- No secrets or unrelated edits were introduced.

Review the complete changed-file diff.

## Completion

Report:
- Feature inspected and repository revision.
- Reports prepared or wiki pages changed.
- Checks actually performed.
- Remaining contradictions and unknowns.

Do not commit, push, deploy, or modify source code unless requested.
