import { routeIssue, installCoordinatorRecovery, warn } from "./team-health.mjs";
import { statSync } from "node:fs";
import { isAbsolute } from "node:path";

export function cwdBlocker(requested, effective) {
  if (requested !== undefined && !isAbsolute(requested)) {
    return "Subagent cwd must be an absolute path to the intended checkout.";
  }
  try {
    if (statSync(effective, { throwIfNoEntry: false })?.isDirectory()) return;
  } catch {
    return "Subagent cwd could not be accessed. Check the intended checkout path and permissions.";
  }
  return "Subagent cwd is not an accessible directory. Verify the intended checkout and its path.";
}

export function childBlocker(result, outcome) {
  if (result.status === "aborted") return;
  if (outcome.timeoutError) {
    result.reviewInterruption = "watchdog timeout";
    return;
  }
  if (outcome.spawnError) {
    return "Subagent CLI could not start. Check the managed Pi installation and the requested cwd.";
  }
  const last = result.messages.findLast((message) => message.role === "assistant");
  const diagnostics = `${last?.stopReason === "error" ? last.errorMessage ?? "" : ""}\n${result.stderr}`;
  if (result.status === "failed") {
    result.routeIssue = routeIssue(diagnostics);
    if (result.routeIssue) return `Subagent ${result.routeIssue}. Check the assigned model and provider.`;
    return;
  }
  if (last?.stopReason === "length") return "Subagent exceeded its output limit before completing the assignment.";
  if (!last?.content.some((part) => part.type === "text" && part.text.trim())) {
    result.reviewInterruption = "missing final response";
    return "Subagent CLI exited without a final assistant response. Check the child CLI and its provider configuration.";
  }
}

function failureSummary(result) {
  const failed = result.details?.results?.find((item) => item.status === "failed");
  if (failed?.blocker) return failed.blocker;
  if (failed?.status === "failed") {
    return "Subagent failed before completing its assignment. See the failed tool result for details.";
  }
  return "Subagent call did not complete. See the failed tool result for details.";
}

export function installBlockerGuard(pi) {
  installCoordinatorRecovery(pi);
  let blocker;
  pi.on("agent_start", () => { blocker = undefined; });
  pi.on("tool_call", (event) => {
    if (!blocker || !["subagent", "agy_worker"].includes(event.toolName)) return;
    return {
      block: true,
      reason: `Pi team delegation is paused for this turn: ${blocker} Report the blocker and wait for user action.`,
    };
  });
  pi.on("tool_execution_end", (event, ctx) => {
    if (blocker || !["subagent", "agy_worker"].includes(event.toolName) || !event.isError || ctx.signal?.aborted) return;
    const results = event.result?.details?.results;
    if (results?.length && results.every((item) => item.status === "aborted")) return;
    blocker = event.toolName === "agy_worker" ? "Worker failed. Inspect partial edits and the failed tool result before resuming." : failureSummary(event.result ?? {});
    if (ctx.hasUI) ctx.ui.notify(`Pi team blocked: ${blocker}`, "error");
    else warn(ctx, `Pi team blocked: ${blocker}`);
  });
}
