import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { createInterface } from "node:readline";
import { test } from "node:test";
import { subagentTimeout, watchSubagent } from "../pi/.pi/agent/team/subagent-watchdog.mjs";

const hang = 'process.on("SIGTERM", () => {}); setInterval(() => {}, 1000);';

function runChild(source, { cancel = false, hardMs = 1250 } = {}) {
  const child = spawn(process.execPath, ["-e", source], { stdio: ["ignore", "pipe", "pipe"] });
  const lines = createInterface({ input: child.stdout });
  let result;
  const watchdog = watchSubagent(child, () => { result = watchdog.error; }, { hardMs, exitMs: 80, graceMs: 80 });
  lines.on("line", (line) => {
    if (line === "agent_end") watchdog.endTurn();
    if (line === "ready" && cancel) watchdog.cancel();
  });
  return once(child, "close").then(([code, signal]) => {
    result ??= watchdog.error;
    watchdog.dispose();
    return { code, signal, error: result };
  });
}

test("finite hard timeout configuration", () => {
  assert.equal(subagentTimeout("12000"), 12000);
  for (const value of ["", "0", "-1", "01", "Infinity", "1.5", "2147483648"]) {
    assert.throws(() => subagentTimeout(value), /PI_TEAM_SUBAGENT_TIMEOUT_MS/);
  }
});

test("normal completion closes without timing out", async () => {
  assert.deepEqual(await runChild('console.log("agent_end");'), { code: 0, signal: null, error: undefined });
});

test("hard timeout force-kills a child that has not ended its turn", async () => {
  const result = await runChild(hang);
  assert.equal(result.signal, "SIGKILL");
  assert.match(result.error, /before its turn ended/);
});

test("agent_end arms a shorter deadline and reports a cleanup timeout", async () => {
  const result = await runChild(`${hang} console.log("agent_end");`);
  assert.equal(result.signal, "SIGKILL");
  assert.match(result.error, /after its turn ended.*within 80 ms/);
});

test("manual cancellation force-kills without reporting a timeout", async () => {
  const result = await runChild(`${hang} console.log("ready");`, { cancel: true });
  assert.equal(result.signal, "SIGKILL");
  assert.equal(result.error, undefined);
});

test("an exited child with unclosed output streams cannot hold the call open", async () => {
  const destroyed = [];
  const child = {
    exitCode: 0, signalCode: null,
    kill() { assert.fail("must not signal an exited child"); },
    stdout: { destroy() { destroyed.push("stdout"); } },
    stderr: { destroy() { destroyed.push("stderr"); } },
  };
  let watchdog;
  await new Promise((resolve) => {
    watchdog = watchSubagent(child, resolve, { hardMs: 1000, exitMs: 20, graceMs: 20 });
    watchdog.endTurn();
  });
  assert.match(watchdog.error, /after its turn ended/);
  assert.deepEqual(destroyed, ["stdout", "stderr"]);
  watchdog.dispose();
});
