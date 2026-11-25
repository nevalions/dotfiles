import assert from "node:assert/strict";
import test from "node:test";
import { runAgyStream, stepProgress } from "../pi/.pi/agent/team/agy-stream.mjs";

const run = (source, options = {}) => runAgyStream(process.execPath, ["-e", source], { timeout: 5000, ...options });
const response = (index, state) => ({step_index: index, step_type: "agent_response", state, text_delta: "private model output"});
const tool = (index, state, name = "read_file") => ({step_index: index, step_type: "tool", state, tool_name: name, tool_info: {parameters: {Path: "private path"}, output: "private contents"}});
const update = step_update => JSON.stringify({event: "step_update", step_update});
const result = response => JSON.stringify({event: "result", result: {status: "SUCCESS", response}});

test("only real step transitions affect the display and completed steps count once for Jev", () => {
  const counted = [];
  const progress = stepProgress(k => counted.push(k), 0);
  assert.match(progress.summary(15000), /no new step events for 15s/);
  assert.equal(progress.observe({step_type:"user_input", step_index:0, state:"DONE"}, 15001), false);
  assert.equal(progress.observe(tool(1, "ACTIVE"), 16000), true);
  assert.equal(progress.observe(tool(1, "ACTIVE"), 17000), false);
  assert.match(progress.summary(18100), /0 tool steps finished · read_file started · 2s ago/);
  assert.equal(progress.observe(tool(1, "DONE"), 20000), true);
  assert.equal(progress.observe(tool(1, "ACTIVE"), 21000), false);
  assert.equal(progress.observe(tool(1, "DONE"), 22000), false);
  progress.observe(response(2, "DONE"), 23000);
  const quiet = progress.summary(83000);
  assert.match(quiet, /1m 23s elapsed · 1 tool step finished \(last: read_file\).*no new step events for 1m 0s/);
  progress.observe(tool(3, "DONE", "private tool name"), 84000);
  assert.doesNotMatch(progress.summary(84001), /private/);
  assert.deepEqual(counted, ["toolEvents", "outputEvents", "toolEvents"]);
});

test("model output during an active step counts without revealing deltas; empty repeats do not", () => {
  const counted = [];
  const progress = stepProgress(k => counted.push(k), 0);
  const step = response(1,"ACTIVE");
  progress.observe(step, 100);
  progress.observe(step, 15000);
  assert.equal(progress.observe({...step,text_delta:""}, 25000),false);
  assert.match(progress.summary(26000),/receiving model output · no new step events for 11s/);
  assert.doesNotMatch(progress.summary(26000),/private/);
  assert.deepEqual(counted,["outputEvents","outputEvents"]);
});

test("streams live summaries across chunks; final report can end at EOF in mid-UTF8 chunks", async () => {
  const first = update(tool(0,"DONE"));
  const last = result("réponse");
  const events = [], records = [];
  const r = await run(`
    const b=Buffer.from(${JSON.stringify(first + "\n" + last)});
    process.stdout.write(b.subarray(0, 10));
    setTimeout(() => process.stdout.write(b.subarray(10, b.indexOf('é')+1)), 50);
    setTimeout(() => process.stdout.end(b.subarray(b.indexOf('é')+1)), 150);
  `, {onProgress: s=>events.push(s), record:k=>records.push(k)});
  assert.equal(r.code, 0);
  assert.equal(r.protocolError,false);
  assert.deepEqual(JSON.parse(r.stdout), {status:"SUCCESS", response:"réponse"});
  assert.deepEqual(records,["toolEvents"]);
  assert.equal(events.length,1);
  assert.match(events[0],/read_file/);
  assert.doesNotMatch(events[0],/private|réponse/);
});

test("cancellation from a live update interrupts a still-running CLI", async () => {
  const c = new AbortController();
  const r = await run(`console.log(${JSON.stringify(update(tool(1,"ACTIVE")))}); setInterval(()=>{},1000)`, {
    signal:c.signal, onProgress:()=>c.abort(),
  });
  assert.equal(c.signal.aborted,true);
  assert.equal(r.killed,true);
  assert.equal(r.stdout,"");
});

test("denial payload reaches the existing report validator but not progress output", async () => {
  const denied = {event:"result", result:{status:"ERROR", denied_actions:[{tool_name:"command",input:"private"}]}};
  const r = await run(`console.log(${JSON.stringify(JSON.stringify(denied))}); process.exitCode=1`);
  assert.equal(r.code,1);
  assert.deepEqual(JSON.parse(r.stdout),denied.result);
});

test("failure diagnostics never become successful reports; malformed and repeated final frames fail closed", async () => {
  for (const extra of ["not json", result("duplicate")]) {
    const r = await run(`console.log(${JSON.stringify(result("first") + "\n" + extra)})`);
    assert.equal(r.protocolError,true);
  }
  const failed = await run(`console.log('quota exceeded: private diagnostic'); process.exitCode=1`);
  assert.equal(failed.diagnosticIssue,"provider rate or quota limit");
  assert.equal(failed.stdout,"");
  const empty = await run(`console.log(${JSON.stringify(update(tool(0,"ACTIVE")))})`);
  assert.equal(empty.stdout,"");
});

test("bounded unterminated frames and oversized final reports stop the child", async () => {
  for (const write of ["'x'.repeat(2*1024*1024+1)", "JSON.stringify({event:'result',result:{response:'x'.repeat(300000)}})+'\\n'"]) {
    const r = await run(`process.stdout.write(${write}); setInterval(()=>{},1000)`);
    assert.equal(r.truncated,true);
    assert.equal(r.killed,true);
  }
});

test("plain timeout stops a silent child; pre-aborted call does not start", async () => {
  const r = await run("setInterval(()=>{},1000)", {timeout:50});
  assert.equal(r.killed,true);
  await assert.rejects(run("process.exit(0)",{signal:AbortSignal.abort()}),/abort/i);
});
