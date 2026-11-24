import assert from "node:assert/strict";
import { test } from "node:test";
import { childBlocker, installBlockerGuard } from "../pi/.pi/agent/team/subagent-blockers.mjs";

function guard() {
  const hooks = new Map();
  const notices = [];
  installBlockerGuard({ on: (name, hook) => hooks.set(name, hook) });
  const ctx = { hasUI: true, ui: { notify: (...args) => notices.push(args) } };
  return { hooks, notices, ctx };
}

test("the first failure notifies immediately and blocks both delegate tools until the next run", () => {
  const { hooks, notices, ctx } = guard();
  const end = hooks.get("tool_execution_end");
  const call = hooks.get("tool_call");
  const result = { details: { results: [{ status: "failed", blocker: "Check the pinned model." }] } };
  end({ toolName: "subagent", isError: true, result }, ctx);
  assert.deepEqual(notices, [["Pi team blocked: Check the pinned model.", "error"]]);
  for (const toolName of ["subagent", "agy_worker"]) {
    assert.equal(call({ toolName }).block, true);
  }
  assert.equal(call({ toolName: "read" }), undefined);
  end({ toolName: "subagent", isError: true, result }, ctx);
  assert.equal(notices.length, 1);
  hooks.get("agent_start")();
  assert.equal(call({ toolName: "subagent" }), undefined);
});

test("validation failures without details notify, but deliberate cancellation does not", () => {
  const { hooks, notices, ctx } = guard();
  const end = hooks.get("tool_execution_end");
  end({ toolName: "subagent", isError: true, result: { details: { results: [{ status: "aborted" }] } } }, ctx);
  assert.deepEqual(notices, []);
  end({ toolName: "subagent", isError: true, result: { details: { results: [] } } }, ctx);
  assert.equal(notices.length, 1);
});

test("classification distinguishes launch and output limits without using successful response text as diagnostics", () => {
  assert.match(childBlocker({ status: "failed" }, { spawnError: new Error("private path") }), /CLI could not start/);
  const last = { role: "assistant", stopReason: "stop", content: [{ type: "text", text: "Rate limit exceeded is an example." }] };
  assert.equal(childBlocker({ status: "completed", messages: [last], stderr: "" }, {}), undefined);
  assert.match(childBlocker({ status: "completed", messages: [{ ...last, stopReason: "length" }], stderr: "" }, {}), /output limit/);
});
