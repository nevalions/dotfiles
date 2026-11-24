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
  hardMs = subagentTimeout(), exitMs = exitTimeoutDefault, graceMs = killGraceDefault,
} = {}) {
  let turnEnded = false;
  let stopping = false;
  let disposed = false;
  let error;
  let exitTimer;
  let killTimer;
  const hardTimer = setTimeout(() => stop(turnEnded
    ? `Subagent timed out after its turn ended; the process did not close within the ${hardMs} ms total limit.`
    : `Subagent timed out after ${hardMs} ms before its turn ended.`), hardMs);

  function stop(reason) {
    if (stopping || disposed) return;
    stopping = true;
    error = reason;
    clearTimeout(hardTimer);
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
    get error() { return error; },
    endTurn() {
      if (turnEnded || stopping || disposed) return;
      turnEnded = true;
      exitTimer = setTimeout(() => stop(`Subagent timed out after its turn ended; the process did not close within ${exitMs} ms.`), exitMs);
    },
    cancel() { stop(); },
    dispose() {
      disposed = true;
      clearTimeout(hardTimer);
      clearTimeout(exitTimer);
      clearTimeout(killTimer);
    },
  };
}
