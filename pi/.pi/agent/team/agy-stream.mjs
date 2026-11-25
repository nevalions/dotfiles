import { routeIssue } from "./team-health.mjs";
import { spawn } from "node:child_process";
import { performance } from "node:perf_hooks";

const lineLimit = 2 * 1024 * 1024;
const streamLimit = 64 * 1024 * 1024;
const reportLimit = 256 * 1024;
const knownTools = new Set([
  "read_file", "view_file", "list_dir", "grep_search", "find_by_name", "write_to_file",
  "replace_file_content", "multi_replace_file_content", "apply_patch", "run_command",
]);

const seconds = ms => Math.floor(ms / 1000);
const duration = ms => ms < 60_000 ? `${seconds(ms)}s` : `${Math.floor(ms / 60_000)}m ${seconds(ms) % 60}s`;

export function stepProgress(record, start = performance.now()) {
  const steps = new Map();
  let completed = 0, lastAt, lastLabel, lastTool;
  return {
    observe(step, now = performance.now()) {
      const { step_index: index, step_type: type, state } = step ?? {};
      const output = type === "agent_response" && state === "ACTIVE" && typeof step.text_delta === "string" && step.text_delta.length > 0;
      if (!Number.isSafeInteger(index) || index < 0 || !["tool", "agent_response"].includes(type) ||
          !["ACTIVE", "DONE"].includes(state) || (!output && steps.get(index) === state) || steps.get(index) === "DONE") return false;
      steps.set(index, state);
      const name = type === "tool" ? (knownTools.has(step.tool_name) ? step.tool_name : "tool") : "model response";
      lastLabel = output ? "receiving model output" : `${name} ${state === "DONE" ? "finished" : "started"}`;
      lastAt = now;
      if (output) record?.("outputEvents");
      if (state === "DONE") {
        if (type === "tool") { completed++; lastTool = name; }
        record?.(type === "tool" ? "toolEvents" : "outputEvents");
      }
      return true;
    },
    summary(now = performance.now()) {
      const age = now - (lastAt ?? start);
      const freshness = age >= 10_000 ? `no new step events for ${duration(age)}` : lastAt === undefined ? "waiting for first step event" : `${duration(age)} ago`;
      return [`${duration(now - start)} elapsed`, `${completed} tool step${completed === 1 ? "" : "s"} finished${lastTool ? ` (last: ${lastTool})` : ""}`, lastLabel, freshness].filter(Boolean).join(" · ");
    },
  };
}

export async function runAgyStream(command, args, { cwd, signal, timeout, onProgress, record }) {
  signal?.throwIfAborted();
  const child = spawn(command, args, { cwd, shell: false, stdio: ["ignore", "pipe", "pipe"] });
  const steps = stepProgress(record);
  let killed = false, truncated = false, protocolError = false, spawnFailed = false;
  let stdout = "", stderr = "", pending = [], pendingBytes = 0, total = 0, lastUpdate = -Infinity, dirty = false;
  let killTimer, diagnosticIssue;
  const stop = () => {
    if (killed) return;
    killed = true;
    child.kill("SIGTERM");
    killTimer = setTimeout(() => {
      if (child.exitCode === null && child.signalCode === null) child.kill("SIGKILL");
      child.stdout.destroy();
      child.stderr.destroy();
    }, 5000);
  };
  const overflow = () => { truncated = true; stop(); };
  const count = text => {
    total += Buffer.byteLength(text);
    if (total > streamLimit) overflow();
    return !killed;
  };
  const publish = () => {
    const now = performance.now();
    if (killed || !onProgress || now - lastUpdate < (dirty ? 1000 : 10_000)) return;
    try { onProgress(steps.summary(now)); } catch { /* Display failures must not interrupt the worker or its cleanup. */ }
    lastUpdate = now;
    dirty = false;
  };
  const line = value => {
    if (!value.trim()) return;
    let frame;
    try { frame = JSON.parse(value); } catch {
      diagnosticIssue ??= routeIssue(value);
      protocolError = true;
      return;
    }
    if (!frame || typeof frame.event !== "string" || stdout) { protocolError = true; return; }
    if (frame.event === "result") {
      if (!frame.result || typeof frame.result !== "object" || Array.isArray(frame.result)) { protocolError = true; return; }
      const terminal = JSON.stringify(frame.result);
      if (Buffer.byteLength(terminal) > reportLimit) { overflow(); return; }
      stdout = terminal;
    } else if (frame.event === "error") {
      diagnosticIssue ??= routeIssue(JSON.stringify(frame.error ?? frame.message ?? ""));
      protocolError = true;
    } else if (frame.event === "step_update" && steps.observe(frame.step_update)) {
      dirty = true;
      publish();
    }
  };
  child.stdout.setEncoding("utf8").on("data", chunk => {
    if (!count(chunk)) return;
    const parts = chunk.split("\n");
    for (let i = 0; i < parts.length; i++) {
      const part = parts[i];
      pendingBytes += Buffer.byteLength(part);
      if (pendingBytes > lineLimit) { overflow(); return; }
      if (part) pending.push(part);
      if (i === parts.length - 1) break;
      line(pending.join(""));
      pending = [];
      pendingBytes = 0;
      if (killed) return;
    }
  });
  child.stderr.setEncoding("utf8").on("data", chunk => {
    if (count(chunk)) stderr = (stderr + chunk).slice(-64 * 1024);
  });
  const streamError = () => { protocolError = true; stop(); };
  child.stdout.on("error", streamError);
  child.stderr.on("error", streamError);
  const refresh = onProgress && setInterval(publish, 1000);
  const deadline = timeout && setTimeout(stop, timeout);
  signal?.addEventListener("abort", stop, { once: true });
  try {
    const code = await new Promise(resolve => {
      child.once("error", () => { spawnFailed = true; });
      child.once("close", (code, terminationSignal) => resolve(code ?? (terminationSignal ? 128 : 1)));
    });
    if (pending.length && !killed) line(pending.join(""));
    return {code: spawnFailed ? 1 : code, stdout, stderr, killed, truncated, protocolError, diagnosticIssue};
  } finally {
    clearTimeout(deadline);
    clearTimeout(killTimer);
    clearInterval(refresh);
    signal?.removeEventListener("abort", stop);
  }
}
