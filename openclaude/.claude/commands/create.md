---
description: "Create a new bd (beads) issue (e.g. /create Add feature X)"
agent: "plan"
---

Create a new bd (beads) issue for: $ARGUMENTS

bd notes:
- Descriptions, acceptance, and notes are plain text / markdown (no HTML).
- Priority is inverted vs Vikunja: `-p 0..4`, 0 = highest. 0=Urgent 1=High 2=Medium (default) 3=Low 4=Trivial.

Steps:
1. Confirm bd is initialized here: `bd ready` (or check for a `.beads/` dir). If none, tell the user to run `bd init` first and stop.
2. Draft the issue BEFORE the create call:
   - title: descriptive, action-oriented, imperative
   - description: what the task is, why it's needed, how to verify it's done
   - acceptance criteria when applicable
   - priority: infer from urgency using the scale above
   - labels: bug, feature, enhancement, documentation, etc.
3. Create it:
   ```
   bd create "<title>" \
     -p <0-4> \
     -l <comma,separated,labels> \
     -d "<description>" \
     --acceptance "<acceptance criteria>"
   ```
4. Confirm creation with the returned issue id.

Best practices:
- Descriptive, action-oriented titles
- Include why and how-to-verify in the description
- Add acceptance criteria when applicable
- Tag with appropriate labels
