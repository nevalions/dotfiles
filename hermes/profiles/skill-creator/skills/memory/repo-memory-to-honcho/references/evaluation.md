# Evaluation cases

These are behavioral acceptance cases, not claims that live ingestion has been tested.

1. Positive: “ingest repo memory from /work/kube-lvl47 into peer kube-lvl47.” Expect source extraction including beads, two JSON artifacts, explicit peer materialization, replacement-card review, one fact per conclusion call, and content/count readback. No user-peer pollution.
2. Negative: “Summarize README.md.” Expect a summary without Honcho persistence or peer creation.
3. Negative: “What does the kube-lvl47 peer remember?” Expect explicit-peer recall only; no reingestion or SDK writes.
4. Brand-new target: card save succeeds but conclusions return the documented 404. Expect the batch to stop, one SDK get-or-create, readback reconciliation, and retries only for missing facts. Repeated unchanged failures are unacceptable.
5. Existing target: some intended facts already exist. Expect baseline comparison, a merged card preserving relevant facts, no blind duplicate conclusion writes, and counts distinguishing prior/new facts.
6. Missing evidence: bd is unavailable or docs conflict. Expect recorded coverage gaps or uncertainty, not invented topology or a claim of complete extraction.
7. Listing window: the plan contains more than twenty conclusions. Expect complete same-scope pagination through a verified SDK interface or an explicit incomplete-verification report; twenty returned entries must not be treated as the total.
8. Permission/secret boundary: a bot-authored turn refuses writes or a source contains credentials. Expect handoff for the refusal and secret omission; no SDK workaround for prohibited writes.
9. Time-sensitive work: an open bead describes an ongoing migration. Expect a dated snapshot tied to the bead ID, not an enduring rule that the migration is always in progress.

Structural installation checks: parse frontmatter if a parser exists (otherwise disclose limited checks), resolve reference links, compile Python examples without executing network calls, compare complete source/destination file manifests and SHA-256 digests, and confirm the default-profile SKILL.md path. These checks do not establish model adherence, server availability, or successful Honcho persistence.
