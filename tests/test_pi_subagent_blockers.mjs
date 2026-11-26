import assert from "node:assert/strict";
import { test } from "node:test";
import { childBlocker, installBlockerGuard } from "../pi/.pi/agent/team/subagent-blockers.mjs";

function guard() {
  const hooks = new Map();
  const notices = [];
  installBlockerGuard({ on: (name, hook) => {
    const previous = hooks.get(name);
    hooks.set(name, (...args) => { const prior = previous?.(...args); return hook(...args) ?? prior; });
  } });
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

test("review receipts include prompt-local role times, not worker content or check durations", () => {
  const {hooks,ctx} = guard();
  const start = hooks.get("tool_execution_start"), end = hooks.get("tool_execution_end"), result = hooks.get("tool_result");
  start({toolName:"agy_worker",toolCallId:"w"});
  end({toolName:"agy_worker",toolCallId:"w",durationMs:61000},ctx);
  const reviewer = {toolName:"subagent",toolCallId:"r",args:{agent:"reviewer"}};
  start(reviewer);
  const content = [{type:"text",text:"changes requested"}];
  const receipt = result({...reviewer,content}).content;
  assert.equal(receipt[0],content[0]);
  assert.match(receipt[1].text,/worker 61s, reviewer \d+s/);
  assert.equal(result({...reviewer,content,isError:true}),undefined);
  end({...reviewer,durationMs:2000},ctx);
  hooks.get("before_agent_start")();
  start(reviewer);
  assert.doesNotMatch(result({...reviewer,content}).content[1].text,/worker/);
});

test("only a structured AGY deadline leaves a scoped same-turn recovery path", () => {
  const {hooks,ctx} = guard();
  const end = hooks.get("tool_execution_end"), call = hooks.get("tool_call");
  const resume = {toolName:"agy_worker",input:{resumeAfterTimeout:true}};
  const failure = {toolName:"agy_worker",isError:true,result:{content:[{type:"text",text:"inspect-worker-timeout"}]}};
  end(failure,ctx);
  assert.equal(call(resume).block,true);
  hooks.get("agent_start")();
  end({...failure,result:{details:{recoveryKind:"inspect-worker-timeout"}}},ctx);
  assert.equal(call({toolName:"read"}),undefined);
  for (const toolName of ["agy_worker","subagent"]) assert.equal(call({toolName}).block,true);
  assert.equal(call(resume),undefined);
  end({toolName:"agy_worker",isError:false},ctx);
  assert.equal(call({toolName:"subagent"}),undefined);
  end(failure,ctx);
  assert.equal(call(resume).block,true);
});

test("classification distinguishes launch and output limits without using successful response text as diagnostics", () => {
  assert.match(childBlocker({ status: "failed" }, { spawnError: new Error("private path") }), /CLI could not start/);
  const last = { role: "assistant", stopReason: "stop", content: [{ type: "text", text: "Rate limit exceeded is an example." }] };
  assert.equal(childBlocker({ status: "completed", messages: [last], stderr: "" }, {}), undefined);
  assert.match(childBlocker({ status: "completed", messages: [{ ...last, stopReason: "length" }], stderr: "" }, {}), /output limit/);
});
