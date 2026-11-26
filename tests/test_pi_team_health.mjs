import assert from "node:assert/strict";
import test from "node:test";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { worktreeSampler } from "../pi/.pi/agent/team/worktree-activity.mjs";
import { setImmediate } from "node:timers/promises";
import { activityLease, installCoordinatorRecovery, readOnlyAttempt, routeIssue, writeAlternate } from "../pi/.pi/agent/team/team-health.mjs";

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
  const thirdRole = {name:"planner",source:"user",tools:["read","ls"],model:"anthropic/claude-opus-4:medium"};
  const thirdCalls = [];
  await readOnlyAttempt(ctx,{agent:thirdRole},undefined,async ({agent}) => {
    thirdCalls.push(agent);
    return {routeIssue:"quota",model:"anthropic/claude-opus-4"};
  });
  assert.equal(thirdCalls.length,2);
  assert.deepEqual(thirdCalls[1],{...thirdRole,model:"openai-codex/gpt-6.1-sol:medium"});
});

test("an interrupted user reviewer gets one fresh attempt; verdicts, cancellations and other roles do not", async () => {
  const role = {name:"reviewer",source:"user",tools:["read","grep"],model:"openai-codex/gpt-6.1-sol:high"};
  const timeout = {status:"failed", reviewInterruption:"watchdog timeout"};
  const empty = {status:"failed", reviewInterruption:"missing final response"};
  const verdict = {status:"completed", content:"changes requested"};
  const aborted = AbortSignal.abort();
  for (const [agent, first, signal, second] of [
    [role, timeout, undefined, verdict],
    [{...role,name:"reviewer-quick"}, empty, undefined, timeout],
    [role, timeout, undefined, {status:"failed",routeIssue:"quota"}],
    [role, verdict], [role, timeout, aborted], [role, {status:"failed"}],
    [{...role,name:"planner"}, timeout], [{...role,source:"project"}, empty],
    [{...role,tools:["edit"]}, timeout],
  ]) {
    const resolved = {agent, cwd:"/checkout"};
    const attempts = [];
    const result = await readOnlyAttempt(ctx, resolved, signal, async request => {
      attempts.push(request);
      return attempts.length === 1 ? first : second;
    });
    assert.deepEqual(attempts, second ? [resolved,resolved] : [resolved]);
    assert.equal(result, second ?? first);
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
  const levels = [];
  installCoordinatorRecovery({
    on: (k,v)=>hooks[k]=v,
    setModel:async m=>{switched.push(m);return true},
    setThinkingLevel:level=>levels.push(level),
  });
  hooks.before_agent_start();
  hooks.message_end({message:{role:"assistant",stopReason:"error",errorMessage:"unsupported_country_region_territory"}});
  for (const [outcome,model,expected] of [["aborted",models[0],false],["error",models[0],true],["error",models[1],false]]) {
    const r = await hooks.agent_before_settle({outcome,entries:[]},{...ctx,model});
    assert.equal(Boolean(r?.continue),expected);
  }
  assert.deepEqual(switched,[models[1]]);
  assert.deepEqual(levels,[]);
  assert.equal(routeIssue("the assigned tests failed"),undefined);
});

test("coordinator falls back third-provider -> Flash (default effort) -> Sol (medium), respects exclusion and abort", async () => {
  const third = {provider:"anthropic",id:"claude-opus-4"};
  const hooks = {};
  const actions = [];
  const notices = [];
  const localCtx = {
    hasUI:true,
    ui:{notify(msg) { notices.push(msg); }},
    modelRegistry:{
      getAvailable:()=>models,
      find:(p,id)=>models.find(m=>m.provider === p && m.id === id),
    },
  };
  installCoordinatorRecovery({
    on:(k,v)=>hooks[k]=v,
    setModel:async m=>{ actions.push(["setModel",m]); return true; },
    setThinkingLevel:level=>actions.push(["setThinkingLevel",level]),
  });

  hooks.before_agent_start();
  hooks.message_end({message:{role:"assistant",stopReason:"error",errorMessage:"429 rate limit exceeded"}});

  const abortedSignal = new AbortController();
  abortedSignal.abort();
  assert.equal(await hooks.agent_before_settle({outcome:"aborted",entries:[]},{...localCtx,model:third}),undefined);
  assert.equal(await hooks.agent_before_settle({outcome:"error",entries:[]},{...localCtx,model:third,signal:abortedSignal.signal}),undefined);
  assert.deepEqual(actions,[]);

  const flashRes = await hooks.agent_before_settle({outcome:"error",entries:[]},{...localCtx,model:third});
  assert.equal(flashRes?.continue,true);
  assert.deepEqual(actions,[["setModel",models[1]]]);
  assert.match(notices.at(-1),/continuing with opencode-go\/deepseek-v4\.1-flash\.$/);

  hooks.message_end({message:{role:"assistant",stopReason:"error",errorMessage:"503 Service Unavailable"}});
  const solRes = await hooks.agent_before_settle({outcome:"error",entries:[]},{...localCtx,model:models[1]});
  assert.equal(solRes?.continue,true);
  assert.deepEqual(actions,[
    ["setModel",models[1]],
    ["setModel",models[0]],
    ["setThinkingLevel","medium"],
  ]);
  assert.match(notices.at(-1),/continuing with openai-codex\/gpt-6\.1-sol \(medium\)\.$/);

  hooks.message_end({message:{role:"assistant",stopReason:"error",errorMessage:"invalid API key"}});
  assert.equal(await hooks.agent_before_settle({outcome:"error",entries:[]},{...localCtx,model:models[0]}),undefined);
  assert.equal(actions.length,3);
  assert.match(notices.at(-1),/no approved fallback remains\.$/);

  hooks.before_agent_start();
  assert.deepEqual(writeAlternate({getAvailable:()=>[models[0]]},third.provider),{ref:"openai-codex/gpt-6.1-sol",thinking:"medium"});
  assert.equal(writeAlternate({getAvailable:()=>[third]},third.provider),undefined);
});

test("coordinator does not set thinking level when setModel fails", async () => {
  const hooks = {};
  const levels = [];
  const onlySolCtx = {
    hasUI:true,
    ui:{notify() {}},
    modelRegistry:{
      getAvailable:()=>[models[0]],
      find:(p,id)=>p === models[0].provider && id === models[0].id ? models[0] : undefined,
    },
  };
  installCoordinatorRecovery({
    on:(k,v)=>hooks[k]=v,
    setModel:async ()=>false,
    setThinkingLevel:level=>levels.push(level),
  });
  hooks.before_agent_start();
  hooks.message_end({message:{role:"assistant",stopReason:"error",errorMessage:"503 Service Unavailable"}});
  const res = await hooks.agent_before_settle({outcome:"error",entries:[]},{...onlySolCtx,model:models[1]});
  assert.equal(res,undefined);
  assert.deepEqual(levels,[]);
});

test("coordinator walks Flash then Sol on activation failure, respects abort and primary exclusion", async () => {
  const third = {provider:"anthropic",id:"claude-opus-4"};
  const hooks = {};
  const actions = [];
  const notices = [];
  let flashFind = true;
  let setModelImpl = async () => true;
  const localCtx = {
    hasUI:true,
    ui:{notify(msg) { notices.push(msg); }},
    modelRegistry:{
      getAvailable:()=>models,
      find:(p,id)=>(!flashFind && p === models[1].provider) ? undefined : models.find(m=>m.provider === p && m.id === id),
    },
  };
  installCoordinatorRecovery({
    on:(k,v)=>hooks[k]=v,
    setModel:async m=>{ actions.push(["setModel",m]); return setModelImpl(m); },
    setThinkingLevel:level=>actions.push(["setThinkingLevel",level]),
  });

  hooks.before_agent_start();
  hooks.message_end({message:{role:"assistant",stopReason:"error",errorMessage:"429 rate limit exceeded"}});
  setModelImpl = async m => m.provider !== models[1].provider;
  const res1 = await hooks.agent_before_settle({outcome:"error",entries:[]},{...localCtx,model:third});
  assert.equal(res1?.continue,true);
  assert.deepEqual(actions,[["setModel",models[1]],["setModel",models[0]],["setThinkingLevel","medium"]]);
  assert.match(notices.at(-1),/continuing with openai-codex\/gpt-6\.1-sol \(medium\)\.$/);
  hooks.message_end({message:{role:"assistant",stopReason:"error",errorMessage:"503 Service Unavailable"}});
  assert.equal(await hooks.agent_before_settle({outcome:"error",entries:[]},{...localCtx,model:models[0]}),undefined);
  assert.equal(actions.length,3);
  assert.match(notices.at(-1),/no approved fallback remains\.$/);

  actions.length = 0;
  flashFind = false;
  setModelImpl = async () => true;
  hooks.before_agent_start();
  hooks.message_end({message:{role:"assistant",stopReason:"error",errorMessage:"429 rate limit exceeded"}});
  const res2 = await hooks.agent_before_settle({outcome:"error",entries:[]},{...localCtx,model:third});
  assert.equal(res2?.continue,true);
  assert.deepEqual(actions,[["setModel",models[0]],["setThinkingLevel","medium"]]);

  actions.length = 0;
  flashFind = true;
  const controller = new AbortController();
  setModelImpl = async () => { controller.abort(); throw new Error("activation failed"); };
  hooks.before_agent_start();
  hooks.message_end({message:{role:"assistant",stopReason:"error",errorMessage:"429 rate limit exceeded"}});
  assert.equal(await hooks.agent_before_settle({outcome:"error",entries:[]},{...localCtx,model:third,signal:controller.signal}),undefined);
  assert.deepEqual(actions,[["setModel",models[1]]]);

  actions.length = 0;
  setModelImpl = async () => { throw new Error("activation failed"); };
  hooks.before_agent_start();
  hooks.message_end({message:{role:"assistant",stopReason:"error",errorMessage:"429 rate limit exceeded"}});
  assert.equal(await hooks.agent_before_settle({outcome:"error",entries:[]},{...localCtx,model:models[0]}),undefined);
  assert.deepEqual(actions,[["setModel",models[1]]]);
  assert.match(notices.at(-1),/no approved fallback remains\.$/);
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
