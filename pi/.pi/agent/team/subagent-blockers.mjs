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

function installReviewTiming(pi) {
  const active = new Map();
  const totals = new Map();
  pi.on("before_agent_start", () => { active.clear(); totals.clear(); });
  pi.on("tool_execution_start", event => {
    const role = event.toolName === "agy_worker" ? "worker" : event.toolName === "subagent" &&
      ({scout:"scout", planner:"planner", "planner-quick":"planner", reviewer:"reviewer", "reviewer-quick":"reviewer"})[event.args?.agent];
    if (typeof role === "string") active.set(event.toolCallId, {role, start:performance.now()});
  });
  pi.on("tool_result", event => {
    const current = active.get(event.toolCallId);
    if (current?.role !== "reviewer" || event.isError) return;
    const snapshot = new Map(totals);
    snapshot.set("reviewer", (snapshot.get("reviewer") ?? 0) + performance.now() - current.start);
    const times = [...snapshot].map(([role, ms]) => `${role} ${Math.round(ms / 1000)}s`).join(", ");
    return { content: [...event.content, {type:"text", text:`Coordinator timing (this prompt, single-role calls; excludes checks): ${times}.`}] };
  });
  pi.on("tool_execution_end", event => {
    const current = active.get(event.toolCallId);
    active.delete(event.toolCallId);
    if (current && Number.isFinite(event.durationMs)) {
      totals.set(current.role, (totals.get(current.role) ?? 0) + event.durationMs);
    }
  });
}

export function installBlockerGuard(pi) {
  installCoordinatorRecovery(pi);
  installReviewTiming(pi);
  let blocker;
  let awaitingInspection = false;
  let offeredRoute, resuming;
  pi.on("agent_start", () => { blocker = undefined; awaitingInspection = false; offeredRoute = resuming = undefined; });
  pi.on("tool_call", (event) => {
    if (!["subagent", "agy_worker"].includes(event.toolName)) return;
    if (resuming) return { block: true, reason: "The inspected writer fallback is already running." };
    if (!blocker && offeredRoute) {
      const input = event.input;
      if (event.toolName === "agy_worker" && input?.resumeWithFallback === true &&
          !input.flashFirst && !input.resumeAfterTimeout && !input.switchFrom &&
          ["issue", "actor", "cwd"].every(k => input[k] === offeredRoute[k])) {
        offeredRoute = undefined;
        resuming = event.toolCallId;
        return;
      }
      return { block: true, reason: "Inspect the partial candidate and resume only the offered route for the same claim." };
    }
    if (!blocker && awaitingInspection && !(event.toolName === "agy_worker" && event.input?.resumeAfterTimeout === true)) {
      return { block: true, reason: "Inspect the timed-out worker's partial changes. Only the offered scoped continuation may resume delegation." };
    }
    if (!blocker) return;
    return {
      block: true,
      reason: `Pi team delegation is paused for this turn: ${blocker} Report the blocker and wait for user action.`,
    };
  });
  pi.on("tool_execution_end", (event, ctx) => {
    if (resuming && resuming === event.toolCallId) resuming = undefined;
    if (blocker || !["subagent", "agy_worker"].includes(event.toolName) || ctx.signal?.aborted) return;
    const details = event.result?.details;
    if (event.toolName === "agy_worker" && event.isError && details?.recoveryKind === "inspect-worker-route" &&
        ["issue", "actor", "cwd"].every(k => typeof details.scope?.[k] === "string" && details.scope[k])) {
      offeredRoute = details.scope;
      return;
    }
    if (event.toolName === "agy_worker" && event.isError && event.result?.details?.recoveryKind === "inspect-worker-timeout") {
      awaitingInspection = true;
      warn(ctx, "AGY timed out. Inspect the partial candidate before using the one scoped continuation.");
      return;
    }
    if (!event.isError) {
      if (event.toolName === "agy_worker") awaitingInspection = false;
      return;
    }
    const results = event.result?.details?.results;
    if (results?.length && results.every((item) => item.status === "aborted")) return;
    blocker = event.toolName === "agy_worker" ? "Worker failed. Inspect partial edits and the failed tool result before resuming." : failureSummary(event.result ?? {});
    if (ctx.hasUI) ctx.ui.notify(`Pi team blocked: ${blocker}`, "error");
    else warn(ctx, `Pi team blocked: ${blocker}`);
  });
}
