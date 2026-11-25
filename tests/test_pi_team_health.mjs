import assert from "node:assert/strict";
import test from "node:test";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { worktreeSampler } from "../pi/.pi/agent/team/worktree-activity.mjs";
import { setImmediate } from "node:timers/promises";
import { activityLease, installCoordinatorRecovery, readOnlyAttempt, routeIssue } from "../pi/.pi/agent/team/team-health.mjs";

const models = [{provider:"openai-codex",id:"gpt-6.1-sol"}, {provider:"opencode-go",id:"deepseek-v4.1-flash"}];
const ctx = {hasUI:true, ui:{notify() {}}, modelRegistry:{getAvailable: () => models, find: (p,id) => models.find(m => m.provider === p && m.id === id)}};

test("sampling notices a second edit to an already dirty file, not heartbeats or unchanged status", async t => {
  const cwd = await mkdtemp(join(tmpdir(), "worker-sample-"));
  t.after(() => rm(cwd, {recursive:true,force:true}));
  let listing = "dirty\0", changes = 0;
  const pi = {exec: async () => ({code:0,stdout:listing})};
  const sample = worktreeSampler(pi,cwd,new AbortController().signal,() => changes++);
  await writeFile(join(cwd,"dirty"),"before");
  await sample();
  await sample();
  assert.equal(changes,0);
  await writeFile(join(cwd,"dirty"),"after");
  await sample();
  assert.equal(changes,1);
  listing = "";
  await sample();
  assert.equal(changes,2);
});

test("only read-only team roles retry a routing failure, exactly once with the same tools and effort", async () => {
  const err = {routeIssue:"quota",model:"openai-codex/gpt-6.1-sol:high"};
  const role = {name:"reviewer",source:"user",tools:["read","grep"],model:err.model};
  for (const [agent, expected] of [[role,2],[{...role,source:"project"},1],[{...role,tools:["bash"]},1]]) {
    const calls = [];
    await readOnlyAttempt(ctx,{agent},undefined,async ({agent}) => {calls.push(agent);return err});
    assert.equal(calls.length,expected);
    if (expected === 2) assert.deepEqual(calls[1],{...role,model:"opencode-go/deepseek-v4.1-flash:high"});
  }
});

test("routing decisions distinguish unavailable providers from task and permission failures", () => {
  for (const [text, reason] of [
    ["You have exhausted your capacity on this model", "provider rate or quota limit"],
    ["unsupported_country_region_territory", "provider location restriction"],
    ["invalid API key", "provider authentication unavailable"],
    ["model_not_found", "model unavailable"],
    ["503 Service Unavailable", "provider unavailable"],
    ["Permission denied writing test.txt", undefined],
    ["test suite failed", undefined],
  ]) assert.equal(routeIssue(text), reason);
});

test("coordinator recovers at settlement, no bounce or replay on abort", async () => {
  const hooks = {};
  const switched = [];
  installCoordinatorRecovery({on: (k,v)=>hooks[k]=v,setModel:async m=>{switched.push(m);return true}});
  hooks.before_agent_start();
  hooks.message_end({message:{role:"assistant",stopReason:"error",errorMessage:"unsupported_country_region_territory"}});
  for (const [outcome,model,expected] of [["aborted",models[0],false],["error",models[0],true],["error",models[1],false]]) {
    const r = await hooks.agent_before_settle({outcome,entries:[]},{...ctx,model});
    assert.equal(Boolean(r?.continue),expected);
  }
  assert.deepEqual(switched,[models[1]]);
  assert.equal(routeIssue("the assigned tests failed"),undefined);
});

for (const [name,p,active,extend] of [
  ["positive",0.86,true,2],["negative",0.08,true,0],["uncertain",0.53,true,1],
  ["silent",0.94,false,0],["missing classifier",undefined,true,1],
]) test("deadline: "+name,async t=>{
  t.mock.timers.enable({apis:["setTimeout","Date"]});
  let expired = 0;
  const notices = [], states = [];
  const registry = {getModelOfType:()=>p === undefined ? undefined : {},classify:async (_,q)=>{
    states.push(q.state);return {stopReason:"stop",answers:{progress:{type:"bool",probability:p}}};
  }};
  const lease=activityLease({windowMs:100,registry,label:"worker",notify:v=>notices.push(v),expire:()=>expired++});
  for (let i=0;i<=extend;i++){
    if(active) lease.record("toolEvents");
    t.mock.timers.tick(100);
    await setImmediate();
  }
  assert.equal(notices.length,extend);
  assert.equal(expired,1);
  if(states.length) assert.deepEqual(Object.keys(states[0]).sort(),["fileChanges","lastProgressMsAgo","outputEvents","toolEvents","windowMs"]);
  lease.dispose();
});

test("cancelling during a stuck judgement never extends or expires the stopped worker",async t=>{
  t.mock.timers.enable({apis:["setTimeout"]});
  const registry={getModelOfType:()=>({}),classify:()=>new Promise(()=>{})};
  const lease=activityLease({windowMs:100,registry,notify:assert.fail,expire:assert.fail});
  t.mock.timers.tick(100);
  lease.dispose();
  t.mock.timers.tick(5000);
  await setImmediate();
});
