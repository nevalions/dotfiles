# Review Loop Policy

- Reviewer checks the actual code diff and runs relevant tests.
- Approve (`kanban_complete`) when the deliverable works and tests pass. Never reject or block over evidence-packet formatting, hypothetical future commands, or minor nits.
- Use `kanban_request_changes` for concrete, fixable bugs in the deliverable.
- Use `kanban_block` only when a genuine external dependency or human policy decision is required. Do not run `review_loop_guard.py` or park tasks over artificial 2-strike counters.
