import assert from "node:assert/strict";
import test from "node:test";
import { teamTaskPicker } from "../pi/.pi/agent/team/task-picker.mjs";

const run = {run_id:"run-1", issue:"repo-1", stage:"implement", worktree:"/worktree"};
const mine = {id:"repo-1", assignee:"pi:session-1", status:"in_progress"};

async function pick(t, opts = {}) {
  const env = process.env.PI_TEAM_TASK_PICKER;
  process.env.PI_TEAM_TASK_PICKER = "1";
  t.after(() => { if (env === undefined) delete process.env.PI_TEAM_TASK_PICKER; else process.env.PI_TEAM_TASK_PICKER = env; });
  const result = {calls:[], notices:[], options:[], editor:opts.editor || ""};
  const pi = {
    getFlag: () => opts.team !== false,
    exec: async (cmd, args) => {
      result.calls.push([cmd, args]);
      const rows = cmd !== "bd" ? (opts.runs ?? [run]) : args.includes("list") ? (opts.mine ?? [mine]) : (opts.ready ?? []);
      return {code: opts.fail ? 1 : 0, stdout:JSON.stringify(rows)};
    },
  };
  const ctx = {mode:opts.mode ?? "tui", hasUI:true, sessionManager:{getSessionId:()=>"session-1"},
    ui:{getEditorText:()=>result.editor, setEditorText:v=>result.editor=v,
      notify:v=>result.notices.push(v), select:async (_, choices) => {
        result.options = choices;
        return choices.find(c=>c.startsWith(opts.pick ?? "no selection"));
      }}};
  await teamTaskPicker(pi, {reason:"startup"}, ctx);
  return result;
}

test("team startup finds the owned run and prepares, but never executes, continuation", async t => {
  const r = await pick(t, {pick:"Continue"});
  assert.match(r.editor, /pi:session-1.*repo-1.*run-1/);
  assert.ok(!r.options.some(c=>c.startsWith("Use repo-1")));
  for (const [,args] of r.calls.slice(1)) assert.deepEqual(args.slice(0,2), ["--readonly","--sandbox"]);
});

for (const [action, label, message] of [
  ["await_external_patch", "External patch required", /No writer is scheduled/],
  ["verify_external_patch", "Verify supplied patch", /do not launch a writer/],
]) {
  test("parked startup reflects durable " + action, async t => {
    const r = await pick(t, {runs:[{...run, action}], pick:label});
    assert.match(r.editor, message);
    assert.ok(!r.options.some(c => c.startsWith("Continue ")));
  });
}

test("other claim and missing worktree are busy, ready issue remains selectable", async t => {
  const r = await pick(t, {runs:[run,{...run,issue:"repo-2",worktree:null}], mine:[],
    ready:[{id:"repo-3",status:"open",title:"fix it"}],pick:"Use"});
  assert.ok(!r.options.some(c=>c.startsWith("Continue")));
  assert.match(r.notices[0], /repo-1, repo-2/);
  assert.match(r.editor, /Implement existing Beads issue repo-3/);
});

for (const opts of [{team:false},{mode:"print"},{editor:"my draft"}]) {
  test("preserves plain Pi, print, or existing input: " + JSON.stringify(opts), async t => {
    const r = await pick(t, opts);
    assert.deepEqual(r.calls, []);
    assert.equal(r.editor, opts.editor || "");
  });
}

for (const opts of [{runs:[{issue:null}]},{fail:true},{pick:"Inspect only"},{}]) {
  test("no startup mutation: " + JSON.stringify(opts), async t => {
    const r = await pick(t, opts);
    assert.equal(r.editor, "");
    if (opts.fail || opts.runs) assert.deepEqual(r.options, []);
  });
}

test("new task needs a submitted description, no ID or path", async t => {
  const r = await pick(t, {runs:[], mine:[], pick:"New task"});
  assert.match(r.editor, /Create a new Beads task.*for: $/);
  assert.deepEqual(r.options, ["New task","Inspect only"]);
});
