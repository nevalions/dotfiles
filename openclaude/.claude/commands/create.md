---
description: "Create a new Vikunja issue (e.g. /create Add feature X)"
agent: "plan"
---

Create a new Vikunja task for: $ARGUMENTS

Vikunja formatting rules:
- Task descriptions use HTML (e.g. <h2>, <ul>, <pre>, <code>)
- Task comments use plain text only

CRITICAL: vikunja_task_create does NOT support the description parameter — it is silently ignored. Always use a two-step pattern:
  Step A: vikunja_task_create — title, projectId, priority only
  Step B: vikunja_task_update — set description immediately after (REQUIRED, never skip)
An empty or missing description after creation is not acceptable.

Steps:
1. List available projects with vikunja_projects_list
2. Determine the appropriate project based on:
   - Current working directory/repo context
   - Project naming conventions (ansible -> ANS-, statsboard-back -> STAB-, etc.)
   - If uncertain, ask user to select from project list
3. List available labels with vikunja_labels_list
4. Draft the HTML description BEFORE making any API call:
   - Use HTML format: <h2>Context</h2>, <h2>Why</h2>, <h2>Acceptance Criteria</h2>, <ul>, <li>, <code>, <pre>
   - Include: what the task is, why it's needed, how to verify it's done
   - Minimum: a <p> paragraph explaining the task
5. Create task with vikunja_task_create:
   - title: Descriptive title (prefix added automatically by webhook)
   - priority: Infer from urgency (default: Medium = 2)
   - projectId: Selected project
   - DO NOT pass description here — it will be silently ignored
6. Immediately call vikunja_task_update with the description drafted in step 4
7. Apply relevant labels with vikunja_labels_bulk_set_on_task
8. Confirm creation with task ID and link

Best practices:
- Use descriptive, action-oriented titles
- Include 'Why' and 'How' in description
- Add acceptance criteria when applicable
- Tag with appropriate labels (bug, feature, enhancement, documentation, etc.)
