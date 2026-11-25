import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdir, mkdtemp, readFile, rm, readdir, symlink } from 'node:fs/promises';
import { stripTypeScriptTypes } from 'node:module';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { setImmediate } from 'node:timers/promises';
import test from 'node:test';

const source = await readFile(new URL('../pi/.pi/agent/extensions/agy-worker.ts', import.meta.url), 'utf8');
const moduleSource = stripTypeScriptTypes(source
  .replace(/from "(\.\.\/team\/[^"]+)"/g, (_, path) => `from "${new URL("../pi/.pi/agent/extensions/" + path, import.meta.url).href}"`)
  .replace('import { truncateHead } from "@earendil-works/pi-coding-agent";', 'const truncateHead = content => ({content});')
  .replace('import { Type } from "typebox";', 'const Type = new Proxy({}, {get: () => () => ({})});'));
const { default: extension, denialSummary, namespaceArgs } = await import(`data:text/javascript;base64,${Buffer.from(moduleSource).toString('base64')}`);
const ok = { code: 0, stdout: '', stderr: '' };
const success = { ...ok, stdout: JSON.stringify({ status: 'SUCCESS', response: 'edited' }) };

async function fixture(t, { team = true, heartbeat = async () => ok, launch = async () => success } = {}) {
  const cwd = await mkdtemp(join(tmpdir(), 'pi-agy-test-'));
  t.after(() => rm(cwd, { recursive: true, force: true }));
  const flags = new Map();
  const calls = [];
  let tool;
  extension({
    registerFlag(name, options) { flags.set(name, options.default); },
    getFlag(name) { return name === 'agy-team' ? team : flags.get(name); },
    registerTool(value) { tool = value; },
    async exec(command, args, options) {
      calls.push([command, args, options.cwd]);
      if (command === 'git' && args.includes('ls-files')) return ok;
      if (command === 'git') return { ...ok, stdout: `${cwd}\n/git/worktrees/test\n/git\n` };
      if (command === 'bd') return heartbeat();
      if (command === 'flock' && args.includes('--no-fork')) return launch(options.signal);
      return ok;
    },
  }, async (command, args, options) => {
    calls.push([command, args, options.cwd]);
    assert.ok(args.includes("stream-json"));
    return launch(options.signal, options);
  });
  const execute = (signal, resumeWithFallback, modelRegistry, onUpdate) => tool.execute('tool', {
    task: 'Edit the test file', resumeWithFallback, ...(team ? { cwd, issue: 'SBB-demo', actor: 'pi:test' } : {}),
  }, signal, onUpdate, { cwd, modelRegistry });
  return { calls, cwd, execute };
}

const heartbeatCalls = calls => calls.filter(([command]) => command === 'bd');

test('plain Pi does not touch Beads and removes its write probe', async t => {
  const { calls, cwd, execute } = await fixture(t, { team: false });
  await execute();
  assert.equal(heartbeatCalls(calls).length, 0);
  assert.deepEqual(await readdir(cwd), []);
  assert(calls.some(([command, args]) => command === 'flock' && args.includes('--unshare-pid') && args.includes('accept-edits')));
});

for (const team of [true, false]) test(`AGY progress reaches onUpdate before the worker finishes (team=${team})`, async t => {
  const updates = [];
  const {execute} = await fixture(t, {team, launch: async (_, {onProgress, record}) => {
    record("toolEvents");
    onProgress("5s elapsed · 1 tool step finished");
    assert.match(updates.at(-1).content[0].text, /1 tool step finished/);
    return success;
  }});
  const result = await execute(undefined, undefined, undefined, u => updates.push(u));
  assert.match(result.content[0].text, /edited/);
});

test('team refuses to start without a renewable claim', async t => {
  const { calls, cwd, execute } = await fixture(t, { heartbeat: async () => ({ ...ok, code: 1 }) });
  await assert.rejects(execute(), /Cannot renew the existing Beads claim/);
  assert.deepEqual(heartbeatCalls(calls), [['bd', ['--actor', 'pi:test', 'heartbeat', 'SBB-demo'], cwd]]);
  assert(!calls.some(([, args]) => args.includes('agy')));
});

test('team renews during delegation, aborts on failure and stops renewing', async t => {
  t.mock.timers.enable({ apis: ['setInterval'] });
  let count = 0;
  let start;
  const started = new Promise(resolve => { start = resolve; });
  const { calls, execute } = await fixture(t, {
    heartbeat: async () => ({ ...ok, code: ++count < 3 ? 0 : 1 }),
    launch: signal => new Promise(resolve => {
      signal.addEventListener('abort', () => resolve({ ...ok, code: 143, killed: true }), { once: true });
      start();
    }),
  });
  const rejected = assert.rejects(execute(), /claim renewal failed.*AGY stopped/);
  await started;
  t.mock.timers.tick(30_000);
  await setImmediate();
  assert.equal(heartbeatCalls(calls).length, 2);
  t.mock.timers.tick(30_000);
  await rejected;
  t.mock.timers.tick(300_000);
  assert.equal(heartbeatCalls(calls).length, 3);
});

test('team offers a scoped fallback without replaying a writer; resumed writer retains isolation', async t => {
  const agentDir = await mkdtemp(join(tmpdir(), 'pi-config-'));
  t.after(() => rm(agentDir, { recursive: true, force: true }));
  const previous = process.env.PI_CODING_AGENT_DIR;
  process.env.PI_CODING_AGENT_DIR = agentDir;
  t.after(() => { if (previous === undefined) delete process.env.PI_CODING_AGENT_DIR; else process.env.PI_CODING_AGENT_DIR = previous; });
  const modelRegistry = {getAvailable: () => [{provider: "openai-codex", id: "gpt-6.1-sol"}]};
  let count = 0;
  const {calls, execute} = await fixture(t, {launch: () => ++count === 1
    ? {...ok, code: 1, stderr: "User location is not supported"} : {...ok, stdout: "edited"}});
  await assert.rejects(execute(undefined, true, modelRegistry), /No pending/);
  await assert.rejects(execute(undefined, false, modelRegistry), /location restriction.*resumeWithFallback/);
  assert.equal(count, 1);
  const resumed = await execute(undefined, true, modelRegistry);
  assert.equal(resumed.details.model, "openai-codex/gpt-6.1-sol");
  const args = calls.filter(([,args]) => args.includes('--no-fork')).at(-1)[1];
  for (const flag of ['--nonblock','bwrap','--unshare-pid','--tmp-overlay',agentDir,'--no-approve','--no-mcp','--no-extensions','read,grep,find,ls,edit,write']) assert.ok(args.includes(flag));
  assert.equal(heartbeatCalls(calls).length, 2);
  await assert.rejects(execute(undefined, true, modelRegistry), /No pending/);
});

test('bubblewrap allows worktree writes but blocks sibling and symlink writes', async t => {
  const { cwd } = await fixture(t, { team: false });
  const work = join(cwd, 'work');
  await mkdir(work);
  await symlink(cwd, join(work, 'outside'));
  const sandbox = namespaceArgs(work);
  const preflight = spawnSync('bwrap', [...sandbox, 'true'], { cwd: work, timeout: 5000 });
  if (preflight.status !== 0) return t.skip('working bubblewrap is required');
  const run = spawnSync('bwrap', [...sandbox, 'sh', '-c',
    'touch inside && ! touch ../sibling && ! touch outside/escape'], { cwd: work, timeout: 5000 });
  assert.equal(run.status, 0, run.stderr.toString());
  assert.deepEqual((await readdir(work)).sort(), ['inside', 'outside']);
  assert.deepEqual(await readdir(cwd), ['work']);
});

test('denials are classified before exit status without leaking contents', async t => {
  const actions = [{ action: 'command', command: 'secret' }, { toolName: 'apply_patch' }, { name: 'secret' }];
  assert.equal(denialSummary(actions), '3 denied (shell, file edit, unrecognized tool)');
  const { execute } = await fixture(t, { launch: async () => ({ code: 1, stdout: JSON.stringify({ denied_actions: actions }) }) });
  await assert.rejects(execute(), error => /3 denied \(shell, file edit, unrecognized tool\)/.test(error.message) && !error.message.includes('secret'));
});
