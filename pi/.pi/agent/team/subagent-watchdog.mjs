import { activityLease } from "./team-health.mjs";

const hardTimeoutDefault = 300_000;
const exitTimeoutDefault = 10_000;
const killGraceDefault = 5_000;

export function subagentTimeout(value = process.env.PI_TEAM_SUBAGENT_TIMEOUT_MS) {
  if (value === undefined) return hardTimeoutDefault;
  if (!/^[1-9][0-9]*$/.test(value) || Number(value) > 2_147_483_647) {
    throw new Error("PI_TEAM_SUBAGENT_TIMEOUT_MS must be a positive integer in milliseconds (max 2147483647)");
  }
  return Number(value);
}

export function watchSubagent(child, onForcedClose, {
  hardMs = subagentTimeout(), exitMs = exitTimeoutDefault, graceMs = killGraceDefault, registry, notify = () => {}, label = "Subagent",
} = {}) {
  let turnEnded = false;
  let stopping = false;
  let disposed = false;
  let error;
  let exitTimer;
  let killTimer;
  const lease = activityLease({windowMs: hardMs, registry, notify, label,
    expire: reason => stop(`Subagent timed out after ${hardMs} ms before its turn ended (${reason}).`),
  });

  function stop(reason) {
    if (stopping || disposed) return;
    stopping = true;
    error = reason;
    lease.dispose();
    clearTimeout(exitTimer);
    if (child.exitCode === null && child.signalCode === null) child.kill("SIGTERM");
    killTimer = setTimeout(() => {
      if (child.exitCode === null && child.signalCode === null) child.kill("SIGKILL");
      child.stdout?.destroy();
      child.stderr?.destroy();
      onForcedClose();
    }, graceMs);
  }

  return {
    observe(event) {
      if (event.type === "message_update" && /^(text|thinking|toolcall)_delta$/.test(event.assistantMessageEvent?.type)) lease.record("outputEvents");
      if (event.type === "tool_execution_end") lease.record("toolEvents");
    },
    get error() { return error; },
    endTurn() {
      if (turnEnded || stopping || disposed) return;
      turnEnded = true;
      lease.dispose();
      exitTimer = setTimeout(() => stop(`Subagent timed out after its turn ended; the process did not close within ${exitMs} ms.`), exitMs);
    },
    cancel() { stop(); },
    dispose() {
      disposed = true;
      lease.dispose();
      clearTimeout(exitTimer);
      clearTimeout(killTimer);
    },
  };
}
