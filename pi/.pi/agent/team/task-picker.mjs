import { homedir } from "node:os";
import { join } from "node:path";

const id = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/;
const clean = text => String(text ?? "").replace(/[\p{C}\p{Z}]+/gu, " ").slice(0, 90);
const inspect = "Inspect only";
const fresh = "New task";

export async function teamTaskPicker(pi, event, ctx) {
  if (!pi.getFlag("agy-team") || process.env.PI_TEAM_TASK_PICKER !== "1" || !ctx.hasUI || ctx.mode !== "tui"
      || !["startup", "new", "resume"].includes(event.reason) || ctx.ui.getEditorText()) return;
  const session = ctx.sessionManager.getSessionId();
  if (!id.test(session)) return;
  const actor = "pi:" + session;
  const read = async (cmd, args) => {
    const result = await pi.exec(cmd, args, { cwd: ctx.cwd, timeout: 5000, maxBuffer: 512 * 1024 });
    if (result.code !== 0 || result.truncated || result.killed) throw new Error();
    const rows = JSON.parse(result.stdout);
    if (!Array.isArray(rows)) throw new Error();
    return rows;
  };
  try {
    const ledger = join(homedir(), ".pi/agent/bin/pi-team-run");
    const runs = await read(ledger, ["discover", ".", "--json"]);
    if (runs.some(r => !r.issue)) {
      ctx.ui.notify("Pi Team: an exclusive run already owns this repository. Inspect only; no task was started.", "warning");
      return;
    }
    const bd = args => read("bd", ["--readonly", "--sandbox", ...args, "--brief", "--json"]);
    const [mine, ready] = await Promise.all([
      bd(["list", "--assignee", actor, "--status", "in_progress", "--limit", "50"]),
      bd(["ready", "--limit", "20"]),
    ]);
    const choices = new Map();
    const busy = [];
    for (const r of runs) {
      if (typeof r.issue !== "string" || !id.test(r.issue) || typeof r.run_id !== "string" || !id.test(r.run_id) || !r.worktree || !mine.some(i => i.id === r.issue && i.assignee === actor)) {
        busy.push(clean(r.issue));
        continue;
      }
      if (r.action === "await_external_patch" || r.action === "verify_external_patch") {
        const pending = r.action === "await_external_patch";
        choices.set(`${pending ? "External patch required" : "Verify supplied patch"} · ${r.issue}`,
          `Inspect the durable handoff on ${r.issue} (run ${r.run_id}). ${pending ? "No writer is scheduled. Do not request approval or repeat a repair." : "Recheck the exact supplied candidate and outstanding review findings; do not launch a writer."}`);
        continue;
      }
      choices.set(`Continue ${r.issue} · ${clean(r.stage)}`,
        `Continue my existing Pi Team task ${r.issue} (run ${r.run_id}). Recheck the claim, worktree and wait state before doing any work.`);
    }
    for (const i of [...mine, ...ready]) {
      if (typeof i.id !== "string" || !id.test(i.id) || runs.some(r => r.issue === i.id)
          || (i.assignee && i.assignee !== actor) || !["open", "in_progress"].includes(i.status)) continue;
      choices.set(`Use ${i.id} · ${clean(i.title)}`,
        `Implement existing Beads issue ${i.id}. Reuse its verified task worktree and run, or create only the missing pieces.`);
    }
    if (busy.length) ctx.ui.notify("Busy or unverified (resume the owning session; no takeover): " + busy.join(", "), "info");
    const selected = await ctx.ui.select("Pi Team · choose a task", [...choices.keys(), fresh, inspect]);
    if (!selected || selected === inspect || ctx.ui.getEditorText()) return;
    const draft = selected === fresh ? "Create a new Beads task and set up its worktree and run for: " : choices.get(selected);
    if (draft) {
      ctx.ui.setEditorText(`Pi Team (claim actor ${actor}): ${draft}`);
      ctx.ui.notify(selected === fresh ? "Describe the task and submit to start." : "Review and submit to continue.", "info");
    }
  } catch {
    ctx.ui.notify("Pi Team startup discovery unavailable. Nothing was started; verify Git, Beads and ledger state before setup.", "warning");
  }
}
