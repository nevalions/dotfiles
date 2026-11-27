import assert from 'node:assert/strict';
import { spawn, spawnSync } from 'node:child_process';
import { constants as fsConstants } from 'node:fs';
import { access, chmod, mkdir, mkdtemp, readFile, realpath, rm, readdir, stat, symlink, writeFile } from 'node:fs/promises';
import { stripTypeScriptTypes } from 'node:module';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { setImmediate, setTimeout as delay } from 'node:timers/promises';
import test from 'node:test';
import { runAgyStream } from '../pi/.pi/agent/team/agy-stream.mjs';

const cliPath = new URL('../pi/.pi/agent/bin/pi-team-run', import.meta.url).pathname;
const source = await readFile(new URL('../pi/.pi/agent/extensions/agy-worker.ts', import.meta.url), 'utf8');
const moduleSource = stripTypeScriptTypes(source
  .replace(/from "(\.\.\/team\/[^"]+)"/g, (_, path) => `from "${new URL("../pi/.pi/agent/extensions/" + path, import.meta.url).href}"`)
  .replace('join(homedir(), ".pi/agent/bin/pi-team-run")', JSON.stringify(cliPath))
  .replace('import { truncateHead } from "@earendil-works/pi-coding-agent";', 'const truncateHead = content => ({content});')
  .replace('import { Type } from "typebox";', 'const Type = new Proxy({}, {get: () => () => ({})});'));
assert.ok(moduleSource.includes(cliPath));
const { default: extension, denialSummary, namespaceArgs } = await import(`data:text/javascript;base64,${Buffer.from(moduleSource).toString('base64')}`);
const ok = { code: 0, stdout: '', stderr: '' };
const success = { ...ok, stdout: JSON.stringify({ status: 'SUCCESS', response: 'edited' }) };

async function fixture(t, { team = true, heartbeat = async () => ok, idle = ok, launch = async () => success } = {}) {
  const cwd = await mkdtemp(join(tmpdir(), 'pi-agy-test-'));
  t.after(() => rm(cwd, { recursive: true, force: true }));
  const flags = new Map();
  const calls = [];
  let tool;
  const hooks = {};
  extension({
    on(name, callback) { hooks[name] = callback; },
    registerFlag(name, options) { flags.set(name, options.default); },
    getFlag(name) { return name === 'agy-team' ? team : flags.get(name); },
    registerTool(value) { tool = value; },
    async exec(command, args, options) {
      calls.push([command, args, options.cwd]);
      const expectedGit = team ? '/usr/bin/git' : 'git';
      if (command === expectedGit && args.includes('ls-files')) return ok;
      if (command === expectedGit) return { ...ok, stdout: `${options.cwd}\n/git/worktrees/test\n/git\n` };
      if (command === 'bd') throw new Error('unexpected bare bd call');
      if (team && command === '/usr/bin/bd') return heartbeat();
      if (team && command === '/usr/bin/python3' && args[0] === '-I' && args[1] === '-S' && args[2] === cliPath && args[3] === 'writer-fence') {
        throw new Error('unexpected writer-fence probe');
      }
      if (command === (team ? '/usr/bin/flock' : 'flock') && args.at(-1) === (team ? '/usr/bin/true' : 'true')) return idle;
      if (command === (team ? '/usr/bin/flock' : 'flock') && args.includes('--no-fork')) return launch(options.signal);
      return ok;
    },
  }, async (command, args, options) => {
    calls.push([command, args, options.cwd]);
    assert.ok(args.includes("stream-json"));
    return launch(options.signal, options);
  });
  const execute = (signal, resumeWithFallback, modelRegistry, onUpdate, overrides) => tool.execute('tool', {
    task: 'Edit the test file', resumeWithFallback, ...(team ? { cwd, issue: 'SBB-demo', actor: 'pi:test' } : {}), ...overrides,
  }, signal, onUpdate, { cwd, modelRegistry });
  return { calls, cwd, execute, hooks };
}

const heartbeatCalls = calls => calls.filter(([command]) => command === '/usr/bin/bd');

test('plain Pi does not touch Beads and removes its write probe', async t => {
  const { calls, cwd, execute } = await fixture(t, { team: false });
  await execute();
  assert.equal(heartbeatCalls(calls).length, 0);
  assert.equal(calls.filter(([command]) => command === 'bd').length, 0);
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
  assert.deepEqual(heartbeatCalls(calls), [['/usr/bin/bd', ['--actor', 'pi:test', 'heartbeat', 'SBB-demo'], cwd]]);
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

async function deadlineFixture(t, { result, idle, heartbeat } = {}) {
  t.mock.timers.enable({apis:['setTimeout']});
  let started, finish;
  const f = await fixture(t, {idle, heartbeat, launch: signal => new Promise(resolve => {
    finish = () => resolve(success);
    signal.addEventListener('abort', () => resolve({ ...ok, code:143, killed:true, protocolError:false, ...result }), { once:true });
    started();
  })});
  return { ...f, async run(params, timeout = true) {
    const ready = new Promise(resolve => { started = resolve; });
    const work = f.execute(undefined, undefined, undefined, undefined, params);
    await ready;
    if (timeout) t.mock.timers.tick(600_000);
    else finish();
    return work;
  }};
}

test('a team deadline never offers continuation or rechecks lock/fence, and rejects resumeAfterTimeout before launch', async t => {
  const f = await deadlineFixture(t);
  await assert.rejects(f.run(), /no continuation offered/);
  assert.equal(f.calls.filter(([, args]) => args.includes('--no-fork')).length, 1);
  assert.ok(!f.calls.some(([cmd, args]) => cmd === '/usr/bin/flock' && args[0] === '--nonblock'));
  assert.ok(!f.calls.some(([cmd, args]) => cmd === '/usr/bin/python3' && args.includes('writer-fence')));
  for (const resumeArgs of [
    { resumeAfterTimeout: true, task: 'Finish only the missing test' },
    { resumeAfterTimeout: true, flashFirst: true, task: 'Finish only the missing test' },
    { resumeAfterTimeout: true, resumeWithFallback: true, task: 'Finish only the missing test' },
  ]) {
    await assert.rejects(f.execute(undefined, undefined, undefined, undefined, resumeArgs), /resumeAfterTimeout/i);
  }
  assert.equal(heartbeatCalls(f.calls).length, 1);
  assert.equal(f.calls.filter(([, args]) => args.includes('--no-fork')).length, 1);
  const fresh = await f.run({ task: 'Fresh attempt after inspection' }, false);
  assert.match(fresh.content[0].text, /edited/);
  assert.equal(heartbeatCalls(f.calls).length, 2);
});

test('explicit resumeAfterTimeout fails closed before launch even from a fresh or legacy session', async t => {
  const f = await fixture(t);
  await assert.rejects(
    f.execute(undefined, undefined, undefined, undefined, { resumeAfterTimeout: true, task: 'Only complete remaining edits' }),
    /resumeAfterTimeout/i,
  );
  assert.equal(f.calls.filter(([cmd]) => cmd === '/usr/bin/bwrap' || cmd === '/usr/bin/flock' || cmd === '/usr/bin/bd').length, 0);
});

for (const [label, options, expected] of [
  ['free worktree lock', { idle: ok }, /no continuation offered/],
  ['busy worktree', { idle: { ...ok, code: 1 } }, /no continuation offered/],
  ['denial', { result: { stdout: JSON.stringify({ denied_actions: ['read_file'] }) } }, /permission/],
  ['output limit', { result: { truncated: true } }, /output limit/],
  ['protocol error', { result: { protocolError: true } }, /no continuation offered/],
  ['provider error', { result: { stderr: '429 rate limit exceeded' } }, /no continuation offered/],
]) test('deadline does not offer recovery for ' + label, async t => {
  const f = await deadlineFixture(t, options);
  await assert.rejects(f.run(), expected);
  assert.ok(!f.calls.some(([cmd, args]) => cmd === '/usr/bin/flock' && args[0] === '--nonblock'));
  assert.ok(!f.calls.some(([cmd, args]) => cmd === '/usr/bin/python3' && args.includes('writer-fence')));
});

test('operator cancellation is not a recoverable work deadline', async t => {
  const stop = new AbortController();
  const f = await fixture(t, { launch: async () => {
    stop.abort();
    return { ...ok, code: 143, killed: true, protocolError: false };
  } });
  await assert.rejects(f.execute(stop.signal), /cancelled/);
  await assert.rejects(
    f.execute(undefined, undefined, undefined, undefined, { resumeAfterTimeout: true, task: 'Finish the missing edit' }),
    /resumeAfterTimeout/i,
  );
  assert.equal(f.calls.filter(([, args]) => args.includes('--no-fork')).length, 1);
});

async function withTempAgentDir(t) {
  const agentDir = await mkdtemp(join(tmpdir(), 'pi-config-'));
  t.after(() => rm(agentDir, { recursive: true, force: true }));
  const previous = process.env.PI_CODING_AGENT_DIR;
  process.env.PI_CODING_AGENT_DIR = agentDir;
  t.after(() => { if (previous === undefined) delete process.env.PI_CODING_AGENT_DIR; else process.env.PI_CODING_AGENT_DIR = previous; });
  return agentDir;
}

function assertRestrictedWriterArgs(args, agentDir, model, thinking) {
  for (const flag of ['--nonblock','/usr/bin/python3','-I','-S','/usr/bin/bwrap','--unshare-pid','--tmp-overlay',agentDir,'--no-approve','--no-mcp','--no-extensions','read,grep,find,ls,edit,write']) {
    assert.ok(args.includes(flag), `missing expected arg: ${flag}`);
  }
  assert.equal(args[args.indexOf('--model') + 1], model);
  assert.equal(args[args.indexOf('--thinking') + 1], thinking);
}

const flashModel = {provider: "opencode-go", id: "deepseek-v4.1-flash"};
const flashRegistry = {getAvailable: () => [flashModel, {provider: "openai-codex", id: "gpt-6.1-sol"}]};
const freshFlash = execute => execute(undefined, undefined, flashRegistry, undefined, {flashFirst: true});

test('Flash-first launches only the pinned restricted writer under the claim and lock', async t => {
  const dir = await withTempAgentDir(t);
  const {calls, execute} = await fixture(t, {launch: () => ({...ok, stdout: 'edited'})});
  const result = await freshFlash(execute);
  const launches = calls.filter(([,args]) => args.includes('--no-fork'));
  assert.equal(launches.length, 1);
  assert.equal(heartbeatCalls(calls).length, 1);
  assertRestrictedWriterArgs(launches[0][1], dir, 'opencode-go/deepseek-v4.1-flash', 'high');
  assert.match(result.content[0].text, /restricted Pi writer.*edited/s);
});

test('Flash-first fails before launch without team mode or claim', async t => {
  await withTempAgentDir(t);
  const plain = await fixture(t, {team:false});
  await assert.rejects(freshFlash(plain.execute), /plain Pi/);
  const f = await fixture(t, {heartbeat: async () => ({...ok, code:1})});
  await assert.rejects(freshFlash(f.execute), /Cannot renew/);
  assert.equal([...plain.calls, ...f.calls].filter(([,args]) => args.includes('--no-fork')).length, 0);
});

test('Flash-first uses the ordinary AGY path when Flash is not configured, before any edits', async t => {
  const {calls, execute} = await fixture(t);
  const result = await execute(undefined, undefined, {getAvailable: () => []}, undefined, {flashFirst:true});
  assert.equal(result.details.model, 'gemini-4-hydrogen-high');
  assert.equal(calls.filter(([,args]) => args.includes('--no-fork')).length, 1);
  assert.equal(heartbeatCalls(calls).length, 1);
});

test('Flash-first offers Sol on provider failure only after inspection, and never loops back to Flash', async t => {
  const dir = await withTempAgentDir(t);
  const {calls, execute} = await fixture(t, {launch: () => ({...ok, code:1, stderr:'429 rate limit exceeded'})});
  await assert.rejects(freshFlash(execute), /resumeWithFallback for openai-codex.*sol .*medium/);
  await assert.rejects(freshFlash(execute), /fresh assignments/);
  assert.equal(heartbeatCalls(calls).length, 1);
  await assert.rejects(execute(undefined, true, flashRegistry), /No approved fallback remains/);
  assertRestrictedWriterArgs(calls.filter(([,args]) => args.includes('--no-fork')).at(-1)[1], dir, 'openai-codex/gpt-6.1-sol', 'medium');
  await assert.rejects(execute(undefined, true, flashRegistry), /No pending/);
});

test('team offers a scoped fallback without replaying a writer; resumed writer retains isolation', async t => {
  const agentDir = await withTempAgentDir(t);
  const modelRegistry = {getAvailable: () => [{provider: "openai-codex", id: "gpt-6.1-sol"}]};
  let count = 0;
  const {calls, execute} = await fixture(t, {launch: () => ++count === 1
    ? {...ok, code: 1, stderr: "User location is not supported"} : {...ok, stdout: "edited"}});
  await assert.rejects(execute(undefined, true, modelRegistry), /No pending/);
  await assert.rejects(execute(undefined, false, modelRegistry), /location restriction.*resumeWithFallback for openai-codex\/gpt-6\.1-sol \(medium\)/);
  assert.equal(count, 1);
  const resumed = await execute(undefined, true, modelRegistry);
  assert.equal(resumed.details.model, "openai-codex/gpt-6.1-sol");
  assert.equal(resumed.details.effort, "medium");
  const args = calls.filter(([,args]) => args.includes('--no-fork')).at(-1)[1];
  assertRestrictedWriterArgs(args, agentDir, 'openai-codex/gpt-6.1-sol', 'medium');
  assert.equal(heartbeatCalls(calls).length, 2);
  await assert.rejects(execute(undefined, true, modelRegistry), /No pending/);
});

test('team falls back AGY -> Flash writer (high) -> Sol writer (medium) without replay and retains isolation', async t => {
  const agentDir = await withTempAgentDir(t);
  const modelRegistry = {
    getAvailable: () => [
      {provider: "openai-codex", id: "gpt-6.1-sol"},
      {provider: "opencode-go", id: "deepseek-v4.1-flash"},
    ],
  };
  let count = 0;
  const {calls, execute} = await fixture(t, {launch: () => {
    count++;
    if (count === 1) return {...ok, code: 1, stderr: "User location is not supported"};
    if (count === 2) return {...ok, code: 1, stderr: "429 rate limit exceeded"};
    return {...ok, stdout: "edited"};
  }});

  await assert.rejects(execute(undefined, false, modelRegistry), /location restriction.*resumeWithFallback for opencode-go\/deepseek-v4\.1-flash \(high\)/);
  assert.equal(count, 1);
  const agyArgs = calls.find(([, args]) => args.includes('--print'))[1];
  assert.equal(agyArgs[agyArgs.indexOf('--model') + 1], 'gemini-4-hydrogen-high');
  assert.equal(agyArgs[agyArgs.indexOf('--effort') + 1], 'high');

  await assert.rejects(execute(undefined, true, modelRegistry), /rate or quota limit.*resumeWithFallback for openai-codex\/gpt-6\.1-sol \(medium\)/);
  assert.equal(count, 2);
  const flashArgs = calls.filter(([, args]) => args.includes('--no-fork')).at(-1)[1];
  assertRestrictedWriterArgs(flashArgs, agentDir, 'opencode-go/deepseek-v4.1-flash', 'high');

  const resumed = await execute(undefined, true, modelRegistry);
  assert.equal(count, 3);
  assert.equal(resumed.details.model, "openai-codex/gpt-6.1-sol");
  assert.equal(resumed.details.effort, "medium");
  const solArgs = calls.filter(([, args]) => args.includes('--no-fork')).at(-1)[1];
  assertRestrictedWriterArgs(solArgs, agentDir, 'openai-codex/gpt-6.1-sol', 'medium');

  assert.equal(heartbeatCalls(calls).length, 3);
  await assert.rejects(execute(undefined, true, modelRegistry), /No pending/);
});

test('team stops without bouncing back to Flash when Sol writer also hits a routing issue', async t => {
  await withTempAgentDir(t);
  const modelRegistry = {
    getAvailable: () => [
      {provider: "openai-codex", id: "gpt-6.1-sol"},
      {provider: "opencode-go", id: "deepseek-v4.1-flash"},
    ],
  };
  let count = 0;
  const {execute} = await fixture(t, {launch: () => {
    count++;
    return {...ok, code: 1, stderr: "503 Service Unavailable"};
  }});

  await assert.rejects(execute(undefined, false, modelRegistry), /opencode-go\/deepseek-v4\.1-flash \(high\)/);
  await assert.rejects(execute(undefined, true, modelRegistry), /openai-codex\/gpt-6\.1-sol \(medium\)/);
  await assert.rejects(execute(undefined, true, modelRegistry), /No approved fallback remains/);
  assert.equal(count, 3);
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
  const actions = [
    { action: 'command', command: 'secret', path: '/etc/passwd' },
    { toolName: 'apply_patch' },
    { action: 'LIST_DIR' },
    { action: 'grep_search' },
    { action: 'find_files' },
    { action: 'read_file' },
    { action: 'read_file' },
    { name: 'secret_tool', path: 'inside.txt' },
  ];
  assert.equal(
    await denialSummary(actions),
    '8 denied (shell: command; file edit: apply_patch [target scope unavailable]; file read/search: list_dir [target scope unavailable]; file read/search: grep_search [target scope unavailable]; file read/search: find_files [target scope unavailable]; file read/search: read_file [target scope unavailable] x2; unrecognized tool: unknown)',
  );
  const { execute } = await fixture(t, { launch: async () => ({ code: 1, stderr: 'secret stderr', stdout: JSON.stringify({ denied_actions: actions }) }) });
  await assert.rejects(execute(), error => (
    /8 denied \(shell: command; file edit: apply_patch \[target scope unavailable\];/.test(error.message)
    && /print mode cannot request interactive approval/.test(error.message)
    && /omit target scope and denial reason/.test(error.message)
    && !error.message.includes('secret')
    && !error.message.includes('/etc/passwd')
  ));
});

test('observed AGY action+display_name shape stops even on exit 0 SUCCESS without echoing display_name', async t => {
  const actions = [{ action: 'read_file', display_name: 'Read /home/user/.ssh/secret_key' }];
  const { execute } = await fixture(t, {
    launch: async () => ({
      code: 0,
      stderr: 'secret stderr',
      stdout: JSON.stringify({ status: 'SUCCESS', response: 'completed', denied_actions: actions }),
    }),
  });
  await assert.rejects(execute(), error => (
    /1 denied \(file read\/search: read_file \[target scope unavailable\]\)/.test(error.message)
    && !error.message.includes('secret_key')
    && !error.message.includes('.ssh')
    && !error.message.includes('stderr')
  ));
});

test('denial target scope classifies worktree boundary, symlinks, .., globs, URLs, and malformed payloads conservatively', async t => {
  const { cwd } = await fixture(t);
  const outsideRoot = await mkdtemp(join(tmpdir(), 'pi-agy-outside-'));
  const siblingPrefixDir = `${cwd}-sibling`;
  await mkdir(siblingPrefixDir, { recursive: true });
  t.after(() => rm(outsideRoot, { recursive: true, force: true }));
  t.after(() => rm(siblingPrefixDir, { recursive: true, force: true }));

  const subDir = join(cwd, 'src');
  const insideFile = join(subDir, 'target.ts');
  const outsideFile = join(outsideRoot, 'secret-outside.txt');
  const siblingFile = join(siblingPrefixDir, 'secret-sibling.txt');
  const outsideLink = join(cwd, 'escape-link');
  const insideLink = join(cwd, 'inside-link');
  const dirLink = join(cwd, 'dir-link');
  const danglingLink = join(cwd, 'dangling-link');
  await mkdir(subDir);
  await writeFile(insideFile, 'ok\n');
  await writeFile(outsideFile, 'secret\n');
  await writeFile(siblingFile, 'secret\n');
  await symlink(outsideFile, outsideLink);
  await symlink(insideFile, insideLink);
  await symlink(subDir, dirLink);
  await symlink(join(outsideRoot, 'missing-target.txt'), danglingLink);

  assert.equal(await denialSummary([{ action: 'read_file', path: 'src/target.ts' }], cwd), '1 denied (file read/search: read_file [existing in-worktree regular file])');
  assert.equal(await denialSummary([{ action: 'read_file', path: insideFile }], cwd), '1 denied (file read/search: read_file [existing in-worktree regular file])');
  assert.equal(await denialSummary([{ action: 'list_dir', target: 'src' }], cwd), '1 denied (file read/search: list_dir [other existing in-worktree path])');
  assert.equal(await denialSummary([{ action: 'write_file', path: 'src/new-file.ts' }], cwd), '1 denied (file edit: write_file [target scope unknown])');
  assert.equal(await denialSummary([{ action: 'write_file', target_file: 'src/target.ts' }], cwd), '1 denied (file edit: write_file [target scope unavailable])');
  assert.equal(await denialSummary([{ action: 'read_file', path: outsideFile }], cwd), '1 denied (file read/search: read_file [outside worktree path])');
  assert.equal(await denialSummary([{ action: 'read_file', path: siblingFile }], cwd), '1 denied (file read/search: read_file [outside worktree path])');
  assert.equal(await denialSummary([{ action: 'read_file', path: join(outsideRoot, 'nonexistent-outside.txt') }], cwd), '1 denied (file read/search: read_file [outside worktree path])');
  assert.equal(await denialSummary([{ action: 'read_file', path: 'escape-link' }], cwd), '1 denied (file read/search: read_file [target scope unknown])');
  assert.equal(await denialSummary([{ action: 'read_file', path: 'inside-link' }], cwd), '1 denied (file read/search: read_file [target scope unknown])');
  assert.equal(await denialSummary([{ action: 'read_file', path: 'dangling-link' }], cwd), '1 denied (file read/search: read_file [target scope unknown])');
  assert.equal(await denialSummary([{ action: 'read_file', path: 'dir-link/target.ts' }], cwd), '1 denied (file read/search: read_file [target scope unknown])');
  assert.equal(await denialSummary([{ action: 'read_file', path: 'dir-link/../src/target.ts' }], cwd), '1 denied (file read/search: read_file [target scope unknown])');
  assert.equal(await denialSummary([{ action: 'read_file', path: 'src/../src/target.ts' }], cwd), '1 denied (file read/search: read_file [target scope unknown])');
  assert.equal(await denialSummary([{ action: 'read_file', path: '../outside.txt' }], cwd), '1 denied (file read/search: read_file [target scope unknown])');
  assert.equal(await denialSummary([{ action: 'read_file', path: '~/secret' }], cwd), '1 denied (file read/search: read_file [target scope unknown])');
  assert.equal(await denialSummary([{ action: 'glob', path: 'src/**/*.ts' }], cwd), '1 denied (file read/search: glob [target scope unknown])');
  assert.equal(await denialSummary([{ action: 'read_file', path: 'https://secret.example/token' }], cwd), '1 denied (file read/search: read_file [target scope unknown])');
  assert.equal(await denialSummary([{ action: 'read_file', path: 'file:///etc/passwd' }], cwd), '1 denied (file read/search: read_file [target scope unknown])');
  assert.equal(await denialSummary([{ action: 'read_file', path: 'a.ts', target: 'b.ts' }], cwd), '1 denied (file read/search: read_file [target scope unknown])');
  assert.equal(await denialSummary([{ action: 'read_file', path: 'bad\0secret' }], cwd), '1 denied (file read/search: read_file [target scope unknown])');
  assert.equal(await denialSummary([{ action: 'read_file', path: 42 }], cwd), '1 denied (file read/search: read_file [target scope unknown])');

  assert.equal(await denialSummary([{ action: 'read_file', decision: 'ask', reason_code: 'deny' }], cwd), '1 denied (file read/search: read_file [target scope unavailable])');
  assert.equal(await denialSummary([{ action: 'read_file', decision: 'ask', reason_code: 'custom_rule' }], cwd), '1 denied (file read/search: read_file [target scope unavailable])');
  assert.equal(await denialSummary([{ action: 'read_file', reason: 'ask' }], cwd), '1 denied (file read/search: read_file [target scope unavailable])');
  assert.equal(await denialSummary([{ action: 'read_file', reason: 'denied by policy' }], cwd), '1 denied (file read/search: read_file [target scope unavailable])');
  assert.equal(await denialSummary([{ action: 'read_file', reason_code: 'policy_denied' }], cwd), '1 denied (file read/search: read_file [target scope unavailable, denied by policy])');

  const leaky = [
    { action: 'read_file', path: outsideFile, display_name: 'secret-display', reason: 'secret rule detail', decision: 'ask' },
  ];
  const summary = await denialSummary(leaky, cwd);
  assert.equal(summary, '1 denied (file read/search: read_file [outside worktree path, requires approval])');
  assert.ok(!summary.includes('secret'));
  assert.ok(!summary.includes(outsideFile));
});

test('denial diagnostics bound distinct path probes, path depth, and unique descriptors', async t => {
  const { cwd } = await fixture(t);
  const files = [];
  for (let i = 1; i <= 9; i++) {
    const name = `f${i}.txt`;
    await writeFile(join(cwd, name), `${i}\n`);
    files.push(name);
  }
  const boundedActions = [
    ...Array.from({ length: 10 }, (_, i) => ({ action: 'read_file', path: `/outside-nominal-${i}/secret.txt` })),
    ...files.map(path => ({ action: 'read_file', path })),
    { action: 'read_file', path: 'f1.txt' },
    { action: 'read_file', path: 'a/b/c/d/e/f/g/h/i/j/k/l/m.txt' },
  ];
  assert.equal(
    await denialSummary(boundedActions, cwd),
    '21 denied (file read/search: read_file [outside worktree path] x10; file read/search: read_file [existing in-worktree regular file] x9; file read/search: read_file [target scope unknown] x2)',
  );

  const manyActions = [
    'command', 'bash', 'sh', 'zsh', 'shell', 'terminal', 'run_command',
    'edit', 'edit_file', 'write', 'write_file', 'apply_patch', 'read', 'read_file',
  ].map(action => ({ action }));
  const capped = await denialSummary(manyActions, cwd);
  assert.match(capped, /^14 denied \(.+\+2 more\)$/);
});

test('worker brief prefers exact worktree paths, scopes search, and keeps native-tool/no-terminal instructions', async t => {
  const { calls, execute } = await fixture(t);
  await execute();
  const agyCall = calls.find(([, args]) => args.includes('--print'));
  assert.ok(agyCall);
  const prompt = agyCall[1].at(-1);
  assert.match(prompt, /native file tools/i);
  assert.match(prompt, /exact named paths in the current worktree/i);
  assert.match(prompt, /only search when explicitly scoped/i);
  assert.match(prompt, /Do not probe outside the worktree or normally protected data/i);
  assert.match(prompt, /stop and ask the coordinator/i);
  assert.match(prompt, /coordinator handles discovery and checks/i);
  assert.match(prompt, /Do not invoke terminal tools/i);
});

function runReal(command, args, { cwd, env, signal, timeout, maxBuffer = 64 * 1024 } = {}) {
  return new Promise(resolve => {
    const child = spawn(command, args, { cwd, env, shell: false, stdio: ['ignore', 'pipe', 'pipe'] });
    const stdout = [], stderr = [];
    let outBytes = 0, errBytes = 0, killed = false, done = false, deadline, escalate;
    const stop = () => {
      if (killed) return;
      killed = true;
      child.kill('SIGTERM');
      escalate = setTimeout(() => child.kill('SIGKILL'), 2000);
    };
    const finish = code => {
      if (done) return;
      done = true;
      clearTimeout(deadline);
      clearTimeout(escalate);
      signal?.removeEventListener('abort', stop);
      resolve({
        code,
        stdout: Buffer.concat(stdout).toString('utf8'),
        stderr: Buffer.concat(stderr).toString('utf8'),
        killed,
        truncated: outBytes > maxBuffer || errBytes > maxBuffer,
      });
    };
    if (signal?.aborted) stop();
    else signal?.addEventListener('abort', stop, { once: true });
    if (timeout) deadline = setTimeout(stop, timeout);
    child.stdout.on('data', chunk => {
      outBytes += chunk.length;
      if (outBytes <= maxBuffer) stdout.push(chunk);
    });
    child.stderr.on('data', chunk => {
      errBytes += chunk.length;
      if (errBytes <= maxBuffer) stderr.push(chunk);
    });
    child.once('error', () => finish(1));
    child.once('close', code => finish(code ?? 1));
  });
}

async function setupFenceFixture(t, { extraWorktrees = [], withFlash = false } = {}) {
  const root = await realpath(await mkdtemp(join(tmpdir(), 'pi-agy-fence-')));
  t.after(() => rm(root, { recursive: true, force: true }));
  const repo = join(root, 'repo');
  const wt1 = join(root, 'wt1');
  const wt2 = join(root, 'wt2');
  const worktrees = { wt1, wt2 };
  for (const name of extraWorktrees) worktrees[name] = join(root, name);
  const bin = join(root, 'bin');
  const stateHome = join(root, 'state');
  const homeDir = join(root, 'home');
  const gitEnv = { ...process.env, GIT_CONFIG_GLOBAL: '/dev/null', GIT_CONFIG_NOSYSTEM: '1' };
  const git = (cwd, ...args) => {
    const run = spawnSync('git', ['-c', 'user.name=Writer Fence', '-c', 'user.email=fence@example.invalid', ...args], {
      cwd, env: gitEnv, encoding: 'utf8', timeout: 15_000,
    });
    assert.equal(run.status, 0, `git ${args.join(' ')} failed: ${run.stderr}`);
    return run.stdout;
  };
  await mkdir(repo);
  git(repo, 'init', '-q', '-b', 'main');
  await writeFile(join(repo, 'README.md'), '# writer fence fixture\n');
  git(repo, 'add', 'README.md');
  git(repo, 'commit', '-q', '-m', 'fixture base');
  for (const [name, dir] of Object.entries(worktrees)) {
    git(repo, 'worktree', 'add', '-q', '-b', name, dir);
  }
  if (spawnSync('/usr/bin/bwrap', [...namespaceArgs(wt1), 'true'], { cwd: wt1, timeout: 5000 }).status !== 0) {
    t.skip('working /usr/bin/bwrap PID namespace is required');
    return null;
  }
  if (spawnSync('/usr/bin/flock', ['--version'], { timeout: 5000 }).status !== 0) {
    t.skip('util-linux /usr/bin/flock is required');
    return null;
  }
  if (spawnSync('/usr/bin/python3', ['-I', '-S', '--version'], { timeout: 5000 }).status !== 0) {
    t.skip('/usr/bin/python3 is required for pi-team-run');
    return null;
  }

  const previous = {
    PATH: process.env.PATH,
    XDG_STATE_HOME: process.env.XDG_STATE_HOME,
    HOME: process.env.HOME,
    PI_CODING_AGENT_DIR: process.env.PI_CODING_AGENT_DIR,
    GIT_CONFIG_GLOBAL: process.env.GIT_CONFIG_GLOBAL,
    GIT_CONFIG_NOSYSTEM: process.env.GIT_CONFIG_NOSYSTEM,
  };
  await mkdir(bin);
  await mkdir(stateHome);
  process.env.PATH = `${bin}:${previous.PATH ?? ''}`;
  process.env.XDG_STATE_HOME = stateHome;
  process.env.GIT_CONFIG_GLOBAL = '/dev/null';
  process.env.GIT_CONFIG_NOSYSTEM = '1';
  let agentDir;
  if (withFlash) {
    agentDir = join(homeDir, '.pi', 'agent');
    const agentBin = join(agentDir, 'bin');
    await mkdir(agentBin, { recursive: true });
    process.env.HOME = homeDir;
    process.env.PI_CODING_AGENT_DIR = agentDir;
    await writeFile(join(agentBin, 'pi.managed'), `#!/bin/sh
set -eu
gate=".pi-agy-gate"
mkdir -p "$gate"
printf '%s %s\\n' "$$" "$(cat /proc/1/comm)" > "$gate/flash-ready"
printf '%s\\n' 'edited'
`, { mode: 0o755 });
  }
  t.after(() => {
    for (const [name, value] of Object.entries(previous)) {
      if (value === undefined) delete process.env[name];
      else process.env[name] = value;
    }
  });

  await writeFile(join(bin, 'agy'), `#!/bin/sh
set -eu
gate=".pi-agy-gate"
mkdir -p "$gate"
printf '%s %s\\n' "$$" "$(cat /proc/1/comm)" > "$gate/ready"
count=0
while [ ! -f "$gate/release" ]; do
  count=$((count + 1))
  if [ "$count" -gt 400 ]; then exit 9; fi
  sleep 0.1
done
printf '%s\\n' '{"event":"step_update","step_update":{"step_index":1,"step_type":"agent_response","state":"ACTIVE","text_delta":"working"}}'
printf '%s\\n' '{"event":"result","result":{"status":"SUCCESS","response":"edited"}}'
`, { mode: 0o755 });

  const env = () => ({ ...process.env, XDG_STATE_HOME: stateHome });
  const cli = (cwd, ...args) => {
    const run = spawnSync('/usr/bin/python3', ['-I', '-S', cliPath, ...args], {
      cwd, env: env(), encoding: 'utf8', timeout: 20_000,
    });
    return {
      code: run.status ?? -1,
      stdout: run.stdout ?? '',
      stderr: run.stderr ?? '',
      output: `${run.stdout ?? ''}${run.stderr ?? ''}`,
    };
  };
  const cliAsync = async (cwd, ...args) => {
    const run = await runReal('/usr/bin/python3', ['-I', '-S', cliPath, ...args], { cwd, env: env(), timeout: 20_000 });
    return { ...run, output: `${run.stdout}${run.stderr}` };
  };
  const createTool = ({ onStreamResult, heartbeat } = {}) => {
    const flags = new Map();
    let tool;
    extension({
      on() {},
      registerFlag(name, options) { flags.set(name, options.default); },
      getFlag(name) { return name === 'agy-team' ? true : flags.get(name); },
      registerTool(value) { tool = value; },
      exec(command, args, options) {
        return command === '/usr/bin/bd'
          ? Promise.resolve(heartbeat ? heartbeat(args, options) : { code: 0, stdout: '', stderr: '' })
          : runReal(command, args, options);
      },
    }, onStreamResult
      ? async (cmd, args, opts) => {
        const res = await runAgyStream(cmd, args, opts);
        onStreamResult(res);
        return res;
      }
      : runAgyStream);
    return tool;
  };
  const dbPath = join(stateHome, 'pi-team-run', 'state.db');
  const readLedger = () => {
    const py = [
      'import json, pathlib, sqlite3, sys',
      'p = pathlib.Path(sys.argv[1])',
      'if not p.exists(): print(json.dumps({"runs": [], "writer_attempts": []})); raise SystemExit(0)',
      'conn = sqlite3.connect(f"{p.resolve().as_uri()}?mode=ro", uri=True)',
      'conn.row_factory = sqlite3.Row',
      'runs = [dict(r) for r in conn.execute("SELECT run_id, repo_key, issue, worktree, status, current_stage FROM runs ORDER BY created_at")]',
      'attempts = [dict(r) for r in conn.execute("SELECT attempt_id, repo_key, worktree, issue, bound, run_id, status, exit_code FROM writer_attempts ORDER BY created_at")]',
      'print(json.dumps({"runs": runs, "writer_attempts": attempts}))',
    ].join('\n');
    const run = spawnSync('/usr/bin/python3', ['-I', '-S', '-c', py, dbPath], { encoding: 'utf8', timeout: 10_000 });
    assert.equal(run.status, 0, `readLedger failed: ${run.stderr}`);
    return JSON.parse(run.stdout);
  };
  const assertBaselineControl = (runId = 'baseline-control') => {
    const baseline = cli(wt2, 'start', wt2, '--json', '--run-id', runId);
    assert.equal(baseline.code, 0, `pi-team-run start failed before any writer existed: ${baseline.output}`);
    const cancelled = cli(wt2, 'cancel', runId, 'admit', '--json');
    assert.equal(cancelled.code, 0, `pi-team-run cancel failed: ${cancelled.output}`);
  };
  return {
    root, repo, wt1, wt2, worktrees, bin, stateHome, homeDir, agentDir, dbPath,
    git, cli, cliAsync, createTool, readLedger, assertBaselineControl,
  };
}

async function assertSandboxedBoundary(cwd, payload, settled) {
  assert.ok(payload.trim(), `fixture setup failed: no sandboxed writer payload in ${cwd}`);
  const [writerPid, namespaceInit] = payload.trim().split(/\s+/);
  assert.match(writerPid, /^[1-9]\d*$/, 'the payload must report the writer PID from its namespace');
  assert.ok(namespaceInit, 'the payload must report the PID 1 comm of its namespace');
  assert.notEqual(namespaceInit, (await readFile('/proc/1/comm', 'utf8')).trim(),
    'the payload must run inside a bubblewrap PID namespace, not the host namespace');
  if (settled !== undefined) {
    assert.equal(settled, false, 'the writer settled before gate release');
  }
}

function launchGatedWriter(t, tool, { cwd, issue, actor = 'pi:fence', task = 'Hold this worktree until the coordinator releases the gate.' }) {
  const stop = new AbortController();
  const gate = join(cwd, '.pi-agy-gate');
  let settled = false;
  let outcome;
  const promise = tool.execute('writer-fence', { task, cwd, issue, actor }, stop.signal, undefined, { cwd })
    .then(value => { settled = true; outcome = { value }; return value; }, error => { settled = true; outcome = { error }; throw error; });
  promise.catch(() => {});

  const waitFinish = async (ms = 20_000) => {
    const ac = new AbortController();
    try {
      await Promise.race([
        promise.catch(() => {}),
        delay(ms, undefined, { signal: ac.signal, ref: false }).catch(() => {}),
      ]);
    } finally {
      ac.abort();
    }
  };
  const releaseGateFile = async () => {
    await mkdir(gate, { recursive: true }).catch(() => {});
    await writeFile(join(gate, 'release'), '').catch(() => {});
  };
  t.after(async () => {
    await releaseGateFile();
    await waitFinish(20_000);
    if (!settled) {
      stop.abort();
      await waitFinish(10_000);
    }
  });

  return {
    promise,
    isSettled: () => settled,
    abort: () => stop.abort(),
    async assertReady(timeoutMs = 20_000) {
      let payload = '';
      const readyBy = Date.now() + timeoutMs;
      while (!payload && !settled && Date.now() < readyBy) {
        payload = await readFile(join(gate, 'ready'), 'utf8').catch(() => '');
        if (!payload && !settled) await delay(50);
      }
      if (!payload && settled) {
        if (outcome?.error) throw outcome.error;
        throw new Error(`writer settled before writing ready marker in ${gate}`);
      }
      await assertSandboxedBoundary(cwd, payload, settled);
      assert.notEqual(spawnSync('/usr/bin/flock', ['--nonblock', cwd, '/usr/bin/true'], { timeout: 5000 }).status, 0,
        'the writer no longer holds the per-worktree flock');
      return payload.trim().split(/\s+/);
    },
    async release(timeoutMs = 20_000) {
      await releaseGateFile();
      await waitFinish(timeoutMs);
      assert.equal(settled, true, 'writer supervisor did not exit within bounded release timeout');
      return promise;
    },
  };
}

test('writer-first unbound writer fences exclusive admission', async t => {
  const f = await setupFenceFixture(t);
  if (!f) return;
  f.assertBaselineControl();
  const tool = f.createTool();
  const writer = launchGatedWriter(t, tool, { cwd: f.wt1, issue: 'SBB-fence-1', actor: 'pi:fence' });
  await writer.assertReady();
  const admission = f.cli(f.wt2, 'start', f.wt2, '--json', '--run-id', 'writer-fence-probe');
  assert.notEqual(admission.code, 0,
    `pi-team-run start accepted exclusive local-only admission while an unbound writer held ${f.wt1}: ${admission.output}`);
  assert.match(admission.output, /writer fence/i, `rejection must name the writer fence: ${admission.output}`);
  await writer.release();
});

test('writer-first denies sibling exclusive start, succeeds on release, then admits exclusive start with no Git delivery', async t => {
  const f = await setupFenceFixture(t);
  if (!f) return;
  const baseSha = f.git(f.repo, 'rev-parse', 'HEAD').trim();
  const baseRefs = f.git(f.repo, 'show-ref');
  f.assertBaselineControl();

  const tool = f.createTool();
  const writer = launchGatedWriter(t, tool, { cwd: f.wt1, issue: 'SBB-case1-1', actor: 'pi:case1' });
  await writer.assertReady();

  const denied = f.cli(f.wt2, 'start', f.wt2, '--json', '--run-id', 'case1-denied');
  assert.notEqual(denied.code, 0);
  assert.match(denied.output, /writer fence/i);

  const result = await writer.release();
  assert.notEqual(result.isError, true);
  assert.match(result.content[0].text, /edited/);

  const ledger = f.readLedger();
  assert.equal(ledger.writer_attempts.length, 1);
  assert.equal(ledger.writer_attempts[0].status, 'closed');
  assert.equal(ledger.writer_attempts[0].exit_code, 0);

  const admitted = f.cli(f.wt2, 'start', f.wt2, '--json', '--run-id', 'case1-admitted');
  assert.equal(admitted.code, 0, admitted.output);
  assert.equal(f.cli(f.wt2, 'cancel', 'case1-admitted', 'admit', '--json').code, 0);

  assert.equal(f.git(f.repo, 'rev-parse', 'main').trim(), baseSha);
  assert.equal(f.git(f.wt1, 'rev-parse', 'HEAD').trim(), baseSha);
  assert.equal(f.git(f.wt2, 'rev-parse', 'HEAD').trim(), baseSha);
  assert.equal(f.git(f.repo, 'show-ref'), baseRefs);
  assert.equal(f.git(f.wt2, 'status', '--porcelain').trim(), '');
});

test('exclusive-first rejects sibling AGY and Flash wrapper with writer fence and no payload marker', async t => {
  const f = await setupFenceFixture(t, { withFlash: true });
  if (!f) return;
  f.assertBaselineControl();

  const started = f.cli(f.wt2, 'start', f.wt2, '--json', '--run-id', 'case2-exclusive');
  assert.equal(started.code, 0, started.output);

  const tool = f.createTool();
  await assert.rejects(
    tool.execute('case2-agy', { task: 'Should be fenced.', cwd: f.wt1, issue: 'SBB-case2-agy', actor: 'pi:case2' }, undefined, undefined, { cwd: f.wt1 }),
    /writer fence/i,
  );
  await assert.rejects(access(join(f.wt1, '.pi-agy-gate', 'ready')), { code: 'ENOENT' });
  assert.equal(f.readLedger().writer_attempts.length, 0);

  const overlayOk = spawnSync('/usr/bin/bwrap', [...namespaceArgs(f.wt1, f.agentDir), 'true'], { cwd: f.wt1, timeout: 5000 }).status === 0;
  await t.test('Flash exact wrapper path', async st => {
    if (!overlayOk) return st.skip('bwrap --tmp-overlay is required for restricted Flash writer');
    await assert.rejects(
      tool.execute('case2-flash-fenced',
        { task: 'Should be fenced.', cwd: f.wt1, issue: 'SBB-case2-flash', actor: 'pi:case2', flashFirst: true },
        undefined, undefined, { cwd: f.wt1, modelRegistry: flashRegistry }),
      /writer fence/i,
    );
    await assert.rejects(access(join(f.wt1, '.pi-agy-gate', 'flash-ready')), { code: 'ENOENT' });

    assert.equal(f.cli(f.wt2, 'cancel', 'case2-exclusive', 'admit', '--json').code, 0);
    const flashResult = await tool.execute('case2-flash-ok',
      { task: 'Run Flash wrapper.', cwd: f.wt1, issue: 'SBB-case2-flash', actor: 'pi:case2', flashFirst: true },
      undefined, undefined, { cwd: f.wt1, modelRegistry: flashRegistry });
    assert.match(flashResult.content[0].text, /restricted Pi writer.*edited/s);
    const flashReady = await readFile(join(f.wt1, '.pi-agy-gate', 'flash-ready'), 'utf8');
    await assertSandboxedBoundary(f.wt1, flashReady);
  });
});

test('concurrent CLI exclusive start and writer launch allow either order with exactly one winner before release', async t => {
  const f = await setupFenceFixture(t);
  if (!f) return;
  f.assertBaselineControl();

  for (const order of ['cli-first', 'writer-first']) {
    const gateDir = join(f.wt1, '.pi-agy-gate');
    await rm(gateDir, { recursive: true, force: true });
    const tool = f.createTool();
    const runId = `case3-${order}`;
    const issue = `SBB-case3-${order}`;

    let cliPromise, writer;
    if (order === 'cli-first') {
      cliPromise = f.cliAsync(f.wt2, 'start', f.wt2, '--json', '--run-id', runId);
      writer = launchGatedWriter(t, tool, { cwd: f.wt1, issue, actor: 'pi:case3' });
    } else {
      writer = launchGatedWriter(t, tool, { cwd: f.wt1, issue, actor: 'pi:case3' });
      cliPromise = f.cliAsync(f.wt2, 'start', f.wt2, '--json', '--run-id', runId);
    }

    const cliRes = await cliPromise;
    const readyBy = Date.now() + 20_000;
    let readyPayload = '';
    while (!writer.isSettled() && !readyPayload && Date.now() < readyBy) {
      readyPayload = await readFile(join(gateDir, 'ready'), 'utf8').catch(() => '');
      if (!writer.isSettled() && !readyPayload) await delay(50);
    }
    await assert.rejects(access(join(gateDir, 'release')), { code: 'ENOENT' });

    const cliWon = cliRes.code === 0;
    const writerWon = !writer.isSettled();
    assert.notEqual(cliWon, writerWon, `expected exactly one winner in ${order}: cli=${cliRes.code} writerSettled=${writer.isSettled()}`);

    const ledgerBeforeRelease = f.readLedger();
    if (cliWon) {
      await assert.rejects(writer.promise, /writer fence/i);
      await assert.rejects(access(join(gateDir, 'ready')), { code: 'ENOENT' });
      const activeRuns = ledgerBeforeRelease.runs.filter(r => r.status === 'active');
      assert.equal(activeRuns.length, 1);
      assert.equal(activeRuns[0].run_id, runId);
      assert.equal(ledgerBeforeRelease.writer_attempts.filter(w => w.status === 'open').length, 0);
      assert.equal(f.cli(f.wt2, 'cancel', runId, 'admit', '--json').code, 0);
    } else {
      assert.match(cliRes.output, /writer fence/i);
      await writer.assertReady();
      assert.equal(ledgerBeforeRelease.runs.filter(r => r.status === 'active' || r.status === 'waiting').length, 0);
      assert.equal(ledgerBeforeRelease.writer_attempts.filter(w => w.status === 'open').length, 1);
      const finished = await writer.release();
      assert.match(finished.content[0].text, /edited/);
    }
  }
});

test('interrupting writer after ready keeps attempt open and fences exclusive sibling even after lock frees', async t => {
  const f = await setupFenceFixture(t);
  if (!f) return;
  f.assertBaselineControl();

  const tool = f.createTool();
  const writer = launchGatedWriter(t, tool, { cwd: f.wt1, issue: 'SBB-case4-1', actor: 'pi:case4' });
  await writer.assertReady();

  writer.abort();
  await assert.rejects(writer.promise, /cancelled/i);
  assert.equal(spawnSync('flock', ['--nonblock', f.wt1, 'true'], { timeout: 5000 }).status, 0,
    'per-worktree lock must be free after supervisor cancellation');

  const ledger = f.readLedger();
  assert.equal(ledger.writer_attempts.length, 1);
  assert.equal(ledger.writer_attempts[0].status, 'open');
  assert.equal(ledger.writer_attempts[0].issue, 'SBB-case4-1');

  const preflight = f.cli(f.wt1, 'preflight', f.wt1, '--json');
  assert.equal(preflight.code, 0, preflight.output);
  assert.equal('writer_fence_open' in JSON.parse(preflight.stdout), false);

  const denied = f.cli(f.wt2, 'start', f.wt2, '--json', '--run-id', 'case4-denied');
  assert.notEqual(denied.code, 0);
  assert.match(denied.output, /writer fence/i);
});

test('interrupted scoped supervisor refuses a same-scope replacement', async t => {
  const f = await setupFenceFixture(t);
  if (!f) return;
  f.assertBaselineControl();

  const issue = 'SBB-review-fence-1';
  const runId = 'review-fence-run';
  const started = f.cli(f.wt1, 'start', f.wt1, '--issue', issue, '--json', '--run-id', runId);
  assert.equal(started.code, 0, started.output);
  let review = { current_stage: 'admit' };
  for (const stage of ['admit', 'implement', 'check']) {
    const checkpointed = f.cli(f.wt1, 'checkpoint', runId, stage, '--evidence', `ev:${stage}`, '--json');
    assert.equal(checkpointed.code, 0, `checkpoint ${stage} failed: ${checkpointed.output}`);
    review = JSON.parse(checkpointed.stdout);
  }
  assert.equal(review.current_stage, 'review');

  const tool = f.createTool();
  const writer = launchGatedWriter(t, tool, { cwd: f.wt1, issue, actor: 'pi:review-fence' });
  await writer.assertReady();

  const [live] = f.readLedger().writer_attempts;
  assert.deepEqual(
    { bound: live.bound, run_id: live.run_id, issue: live.issue, status: live.status },
    { bound: 1, run_id: runId, issue, status: 'open' },
  );

  writer.abort();
  await assert.rejects(writer.promise, /cancelled/i);
  assert.equal(spawnSync('/usr/bin/flock', ['--nonblock', f.wt1, '/usr/bin/true'], { timeout: 5000 }).status, 0,
    'per-worktree lock must be free after supervisor cancellation');

  const gate = join(f.wt1, '.pi-agy-gate');
  await rm(gate, { recursive: true, force: true });

  const interrupted = f.readLedger();
  assert.equal(interrupted.writer_attempts.length, 1);
  assert.deepEqual(
    {
      attempt_id: interrupted.writer_attempts[0].attempt_id,
      bound: interrupted.writer_attempts[0].bound,
      run_id: interrupted.writer_attempts[0].run_id,
      issue: interrupted.writer_attempts[0].issue,
      status: interrupted.writer_attempts[0].status,
      exit_code: interrupted.writer_attempts[0].exit_code,
    },
    { attempt_id: live.attempt_id, bound: 1, run_id: runId, issue, status: 'open', exit_code: null },
  );
  const run = interrupted.runs.find(row => row.run_id === runId);
  assert.equal(run.status, 'active');
  assert.equal(run.current_stage, 'review');

  await assert.rejects(
    tool.execute('review-fence-replacement', { task: 'Replace the interrupted writer.', cwd: f.wt1, issue, actor: 'pi:review-fence' },
      undefined, undefined, { cwd: f.wt1 }),
    /writer fence/i,
  );
  await assert.rejects(access(join(gate, 'ready')), { code: 'ENOENT' });
  await assert.rejects(access(gate), { code: 'ENOENT' });

  const replaced = f.readLedger();
  assert.equal(replaced.writer_attempts.length, 1);
  assert.equal(replaced.writer_attempts[0].attempt_id, live.attempt_id);
  assert.equal(replaced.writer_attempts[0].status, 'open');
  assert.equal(replaced.runs.find(row => row.run_id === runId).current_stage, 'review');
  assert.equal(f.cli(f.wt1, 'cancel', runId, 'review', '--json').code, 0);
});

test('stale writer completion rejects close mismatch and leaves replacement attempt fenced', async t => {
  const f = await setupFenceFixture(t);
  if (!f) return;
  f.assertBaselineControl();

  const seenStderr = [];
  const tool = f.createTool({ onStreamResult: res => { if (res.stderr) seenStderr.push(res.stderr); } });
  const writer = launchGatedWriter(t, tool, { cwd: f.wt1, issue: 'SBB-case5-orig', actor: 'pi:case5' });
  await writer.assertReady();

  const [live] = f.readLedger().writer_attempts;
  assert.equal(live.status, 'open');

  const injectPy = [
    'import sqlite3, sys',
    'db, old_id, rep_id, repo_key, wt = sys.argv[1:6]',
    'conn = sqlite3.connect(db, timeout=5.0, isolation_level=None)',
    'conn.execute("BEGIN IMMEDIATE")',
    'cur = conn.execute("UPDATE writer_attempts SET status=\'closed\', exit_code=137, closed_at=\'2026-01-01T00:00:00Z\' WHERE attempt_id=? AND status=\'open\'", (old_id,))',
    'assert cur.rowcount == 1',
    'conn.execute("INSERT INTO writer_attempts(attempt_id, repo_key, worktree, issue, bound, run_id, status, created_at) VALUES (?, ?, ?, \'SBB-case5-next\', 0, NULL, \'open\', \'2026-01-01T00:00:01Z\')", (rep_id, repo_key, wt))',
    'conn.execute("COMMIT")',
    'conn.close()',
  ].join('\n');
  const inject = spawnSync('python3', ['-c', injectPy, f.dbPath, live.attempt_id, 'wa-replacement-case5', live.repo_key, live.worktree], {
    encoding: 'utf8', timeout: 10_000,
  });
  assert.equal(inject.status, 0, `disposable stale injection failed: ${inject.stderr}`);

  await writeFile(join(f.wt1, '.pi-agy-gate', 'release'), '');
  await assert.rejects(writer.promise, /exited with code 1/i);
  assert.match(seenStderr.join('\n'), /writer fence close mismatch/i);

  const attempts = new Map(f.readLedger().writer_attempts.map(row => [row.attempt_id, row]));
  assert.equal(attempts.get(live.attempt_id)?.status, 'closed');
  assert.equal(attempts.get(live.attempt_id)?.exit_code, 137);
  assert.equal(attempts.get('wa-replacement-case5')?.status, 'open');

  const denied = f.cli(f.wt2, 'start', f.wt2, '--json', '--run-id', 'case5-denied');
  assert.notEqual(denied.code, 0);
  assert.match(denied.output, /writer fence/i);
});

test('concurrent scoped writers in separate worktrees run simultaneously while duplicates fail', async t => {
  const f = await setupFenceFixture(t, { extraWorktrees: ['wt3'] });
  if (!f) return;
  const wt3 = f.worktrees.wt3;
  f.assertBaselineControl();

  assert.equal(f.cli(f.wt1, 'start', f.wt1, '--issue', 'SBB-case6-1', '--json', '--run-id', 'case6-run-1').code, 0);

  const tool = f.createTool();
  const w1 = launchGatedWriter(t, tool, { cwd: f.wt1, issue: 'SBB-case6-1', actor: 'pi:case6-1' });
  await w1.assertReady();

  assert.equal(f.cli(f.wt2, 'start', f.wt2, '--issue', 'SBB-case6-2', '--json', '--run-id', 'case6-run-2').code, 0);
  const w2 = launchGatedWriter(t, tool, { cwd: f.wt2, issue: 'SBB-case6-2', actor: 'pi:case6-2' });
  await w2.assertReady();
  assert.equal(w1.isSettled(), false);
  assert.equal(w2.isSettled(), false);
  await w1.assertReady();

  const openAttempts = f.readLedger().writer_attempts.filter(w => w.status === 'open');
  assert.equal(openAttempts.length, 2);
  assert.ok(openAttempts.every(w => w.bound === 1));

  assert.equal(spawnSync('flock', ['--nonblock', wt3, 'true'], { timeout: 5000 }).status, 0);
  assert.notEqual(f.cli(wt3, 'start', wt3, '--issue', 'SBB-case6-1', '--json', '--run-id', 'case6-dup-issue').code, 0);
  await assert.rejects(
    tool.execute('dup-issue', { task: 'Duplicate issue.', cwd: wt3, issue: 'SBB-case6-1', actor: 'pi:case6-dup' }, undefined, undefined, { cwd: wt3 }),
    /writer fence/i,
  );
  await assert.rejects(access(join(wt3, '.pi-agy-gate', 'ready')), { code: 'ENOENT' });

  assert.notEqual(f.cli(f.wt1, 'start', f.wt1, '--issue', 'SBB-case6-3', '--json', '--run-id', 'case6-dup-wt').code, 0);
  await assert.rejects(
    tool.execute('dup-wt', { task: 'Duplicate worktree.', cwd: f.wt1, issue: 'SBB-case6-3', actor: 'pi:case6-dup' }, undefined, undefined, { cwd: f.wt1 }),
    /worktree lock is busy/i,
  );

  const unscoped = f.cli(wt3, 'start', wt3, '--json', '--run-id', 'case6-unscoped');
  assert.notEqual(unscoped.code, 0);
  assert.match(unscoped.output, /writer fence/i);

  const [r1, r2] = await Promise.all([w1.release(), w2.release()]);
  assert.match(r1.content[0].text, /edited/);
  assert.match(r2.content[0].text, /edited/);

  const closedAttempts = f.readLedger().writer_attempts;
  assert.equal(closedAttempts.length, 2);
  assert.ok(closedAttempts.every(w => w.status === 'closed' && w.exit_code === 0));
});

test('missing or non-executable fake writer emits bwrap diagnostic without trace or args, closes fence, and never falls back to real agy', async t => {
  const f = await setupFenceFixture(t, { withFlash: true });
  if (!f) return;
  f.assertBaselineControl();

  const findInPath = async (name, pathValue) => {
    for (const dir of (pathValue ?? '').split(':').filter(Boolean)) {
      const candidate = join(dir, name);
      try {
        if ((await stat(candidate)).isFile()) {
          await access(candidate, fsConstants.X_OK);
          return candidate;
        }
      } catch {}
    }
    return null;
  };

  const sysBin = join(f.root, 'sys-bin');
  await mkdir(sysBin);
  for (const name of ['bwrap', 'flock', 'python3', 'git', 'sh', 'true']) {
    const resolved = await findInPath(name, process.env.PATH);
    assert.ok(resolved, `missing required tool in PATH: ${name}`);
    await symlink(resolved, join(sysBin, name));
  }
  process.env.PATH = `${f.bin}:${sysBin}`;

  await rm(join(f.bin, 'agy'));
  assert.equal(await findInPath('agy', process.env.PATH), null, 'isolated PATH must not resolve any real agy');

  const seenMissing = [];
  const toolMissing = f.createTool({ onStreamResult: res => seenMissing.push(res) });
  await assert.rejects(
    toolMissing.execute('missing-agy',
      { task: 'Secret missing writer payload.', cwd: f.wt1, issue: 'SBB-missing-agy', actor: 'pi:missing' },
      undefined, undefined, { cwd: f.wt1, modelRegistry: flashRegistry }),
    /CLI unavailable.*resumeWithFallback for opencode-go\/deepseek-v4\.1-flash \(high\)/,
  );
  assert.equal(seenMissing.length, 1);
  assert.equal(seenMissing[0].code, 127);
  assert.match(seenMissing[0].stderr, /^bwrap: execvp agy: No such file or directory$/m);
  assert.doesNotMatch(seenMissing[0].stderr, /Traceback|FileNotFoundError|Secret missing writer payload|--model/);

  await writeFile(join(f.bin, 'agy'), '#!/bin/sh\nexit 0\n', { mode: 0o644 });
  await chmod(join(f.bin, 'agy'), 0o644);
  const seenPerm = [];
  const toolPerm = f.createTool({ onStreamResult: res => seenPerm.push(res) });
  await assert.rejects(
    toolPerm.execute('denied-agy',
      { task: 'Secret perm writer payload.', cwd: f.wt1, issue: 'SBB-denied-agy', actor: 'pi:denied' },
      undefined, undefined, { cwd: f.wt1, modelRegistry: flashRegistry }),
    /CLI unavailable.*resumeWithFallback for opencode-go\/deepseek-v4\.1-flash \(high\)/,
  );
  assert.equal(seenPerm.length, 1);
  assert.equal(seenPerm[0].code, 126);
  assert.match(seenPerm[0].stderr, /^bwrap: execvp agy: Permission denied$/m);
  assert.doesNotMatch(seenPerm[0].stderr, /Traceback|PermissionError|Secret perm writer payload|--model/);

  const overlayOk = spawnSync('/usr/bin/bwrap', [...namespaceArgs(f.wt1, f.agentDir), 'true'], { cwd: f.wt1, timeout: 5000 }).status === 0;
  await t.test('missing direct pi.managed wrapper', async st => {
    if (!overlayOk) return st.skip('bwrap --tmp-overlay is required for restricted Flash writer');
    await rm(join(f.agentDir, 'bin', 'pi.managed'));
    const toolFlash = f.createTool();
    await assert.rejects(
      toolFlash.execute('missing-flash',
        { task: 'Secret flash payload.', cwd: f.wt1, issue: 'SBB-missing-flash', actor: 'pi:flash', flashFirst: true },
        undefined, undefined, { cwd: f.wt1, modelRegistry: flashRegistry }),
      err => (
        /restricted Pi writer.*CLI unavailable.*resumeWithFallback for openai-codex\/gpt-6\.1-sol \(medium\)/.test(err.message)
        && !/Traceback|FileNotFoundError|Secret flash payload/.test(err.message)
      ),
    );
  });

  const attempts = new Map(f.readLedger().writer_attempts.map(row => [row.issue, row]));
  assert.deepEqual(
    { status: attempts.get('SBB-missing-agy')?.status, exit_code: attempts.get('SBB-missing-agy')?.exit_code },
    { status: 'closed', exit_code: 127 },
  );
  assert.deepEqual(
    { status: attempts.get('SBB-denied-agy')?.status, exit_code: attempts.get('SBB-denied-agy')?.exit_code },
    { status: 'closed', exit_code: 126 },
  );
  if (overlayOk) {
    assert.deepEqual(
      { status: attempts.get('SBB-missing-flash')?.status, exit_code: attempts.get('SBB-missing-flash')?.exit_code },
      { status: 'closed', exit_code: 127 },
    );
  }
});

test('team supervisor pins trusted system runtimes and ignores worktree-local shadowed binaries and site hooks', async t => {
  const f = await setupFenceFixture(t);
  if (!f) return;
  f.assertBaselineControl();

  const shadowBin = join(f.wt1, '.shadow-bin');
  const shadowMarker = join(f.wt1, 'shadow-executed');
  const siteMarker = join(f.wt1, 'site-hook-ran');
  await mkdir(shadowBin);
  for (const name of ['python3', 'bwrap', 'flock', 'git', 'true', 'bd']) {
    const exe = join(shadowBin, name);
    await writeFile(exe, `#!/bin/sh\ntouch ${JSON.stringify(shadowMarker)}\nexit 99\n`, { mode: 0o755 });
  }
  await writeFile(join(f.wt1, 'sitecustomize.py'), `from pathlib import Path\nPath(${JSON.stringify(siteMarker)}).write_text('pwned')\n`);

  const prevPythonPath = process.env.PYTHONPATH;
  const prevUserBase = process.env.PYTHONUSERBASE;
  process.env.PATH = `${shadowBin}:${process.env.PATH}`;
  process.env.PYTHONPATH = f.wt1;
  process.env.PYTHONUSERBASE = f.wt1;
  t.after(() => {
    if (prevPythonPath === undefined) delete process.env.PYTHONPATH;
    else process.env.PYTHONPATH = prevPythonPath;
    if (prevUserBase === undefined) delete process.env.PYTHONUSERBASE;
    else process.env.PYTHONUSERBASE = prevUserBase;
  });

  const failingHeartbeatTool = f.createTool({ heartbeat: () => ({ code: 1, stdout: '', stderr: '' }) });
  await assert.rejects(
    failingHeartbeatTool.execute('bad-hb', { task: 'Heartbeat fails.', cwd: f.wt1, issue: 'SBB-bad-hb', actor: 'pi:trusted' }, undefined, undefined, { cwd: f.wt1 }),
    /Cannot renew the existing Beads claim/,
  );

  const tool = f.createTool();
  const writer = launchGatedWriter(t, tool, { cwd: f.wt1, issue: 'SBB-trusted-launch', actor: 'pi:trusted' });
  await writer.assertReady();
  const result = await writer.release();
  assert.match(result.content[0].text, /edited/);

  await assert.rejects(access(shadowMarker), { code: 'ENOENT' });
  await assert.rejects(access(siteMarker), { code: 'ENOENT' });
  const ledger = f.readLedger();
  assert.equal(ledger.writer_attempts.length, 1);
  assert.equal(ledger.writer_attempts[0].status, 'closed');
  assert.equal(ledger.writer_attempts[0].exit_code, 0);
});

test('team mode pins trusted system paths in preflight and launch without post-timeout probes while plain Pi stays unmodified', async t => {
  const team = await deadlineFixture(t);
  await assert.rejects(team.run(), /no continuation offered/);
  assert.ok(team.calls.some(([cmd, args]) => cmd === '/usr/bin/git' && args.includes('rev-parse')));
  assert.ok(team.calls.some(([cmd, args]) => cmd === '/usr/bin/git' && args.includes('ls-files')));
  assert.ok(team.calls.some(([cmd, args]) => cmd === '/usr/bin/bd' && args.includes('heartbeat')));
  assert.ok(!team.calls.some(([cmd]) => cmd === 'bd'));
  assert.ok(team.calls.some(([cmd, args]) => cmd === '/usr/bin/bwrap' && args.at(-1) === '/usr/bin/true'));
  assert.ok(team.calls.some(([cmd, args]) => cmd === '/usr/bin/flock' && args[0] === '--version'));
  assert.ok(team.calls.some(([cmd, args]) =>
    cmd === '/usr/bin/flock' && args.includes('/usr/bin/python3') && args.includes('-I') && args.includes('-S') && args.includes('/usr/bin/bwrap')
  ));
  assert.ok(!team.calls.some(([cmd, args]) => cmd === '/usr/bin/flock' && args[0] === '--nonblock'));
  assert.ok(!team.calls.some(([cmd, args]) => cmd === '/usr/bin/python3' && (args[3] === 'writer-fence' || args[3] === 'preflight')));

  const plain = await fixture(t, { team: false });
  await plain.execute();
  assert.ok(plain.calls.some(([cmd, args]) => cmd === 'bwrap' && args.at(-1) === 'true'));
  assert.ok(plain.calls.some(([cmd, args]) => cmd === 'flock' && args[0] === '--version'));
  assert.ok(plain.calls.some(([cmd, args]) => cmd === 'flock' && args.includes('bwrap') && !args.includes('/usr/bin/bwrap')));
});

test('shadowed git and GIT_DIR/GIT_COMMON_DIR overrides cannot bypass fence on start or writer-exec', async t => {
  const f = await setupFenceFixture(t);
  if (!f) return;
  f.assertBaselineControl();

  const unrelated = join(f.root, 'unrelated-repo');
  await mkdir(unrelated);
  f.git(unrelated, 'init', '-q', '-b', 'main');
  await writeFile(join(unrelated, 'README.md'), '# unrelated\n');
  f.git(unrelated, 'add', 'README.md');
  f.git(unrelated, 'commit', '-q', '-m', 'unrelated');

  const shadowGitDir = join(f.root, 'shadow-git');
  const shadowMarker = join(f.root, 'shadow-git-ran');
  await mkdir(shadowGitDir);
  await writeFile(join(shadowGitDir, 'git'), `#!/bin/sh\ntouch ${JSON.stringify(shadowMarker)}\nprintf '%s\\n' ${JSON.stringify(join(unrelated, '.git'))}\n`, { mode: 0o755 });

  const tool = f.createTool();
  const writer = launchGatedWriter(t, tool, { cwd: f.wt1, issue: 'SBB-git-env', actor: 'pi:git-env' });
  await writer.assertReady();

  writer.abort();
  await assert.rejects(writer.promise, /cancelled/i);

  const prevEnv = {
    PATH: process.env.PATH,
    GIT_DIR: process.env.GIT_DIR,
    GIT_COMMON_DIR: process.env.GIT_COMMON_DIR,
    GIT_WORK_TREE: process.env.GIT_WORK_TREE,
  };
  process.env.PATH = `${shadowGitDir}:${process.env.PATH}`;
  process.env.GIT_DIR = join(unrelated, '.git');
  process.env.GIT_COMMON_DIR = join(unrelated, '.git');
  process.env.GIT_WORK_TREE = unrelated;
  t.after(() => {
    for (const [k, v] of Object.entries(prevEnv)) {
      if (v === undefined) delete process.env[k];
      else process.env[k] = v;
    }
  });

  const deniedStart = f.cli(f.wt2, 'start', f.wt2, '--json', '--run-id', 'shadow-git-denied');
  assert.notEqual(deniedStart.code, 0);
  assert.match(deniedStart.output, /writer fence/i);

  const deniedScopedStart = f.cli(f.wt2, 'start', f.wt2, '--issue', 'SBB-git-env-2', '--json', '--run-id', 'shadow-git-scoped-denied');
  assert.notEqual(deniedScopedStart.code, 0);
  assert.match(deniedScopedStart.output, /writer fence/i);

  const blockedMarker = join(f.wt2, 'shadow-wexec-ran');
  const deniedWriterExec = f.cli(
    f.wt2, 'writer-exec', '--cwd', f.wt2, '--issue', 'SBB-git-env-2', '--',
    '/usr/bin/bwrap', ...namespaceArgs(f.wt2), '/bin/sh', '-c', `touch ${JSON.stringify(blockedMarker)}`,
  );
  assert.notEqual(deniedWriterExec.code, 0);
  assert.match(deniedWriterExec.output, /writer fence/i);
  await assert.rejects(access(blockedMarker), { code: 'ENOENT' });

  assert.notEqual(f.cli(f.wt1, 'writer-fence', f.wt1, '--json').code, 0);
  await assert.rejects(access(shadowMarker), { code: 'ENOENT' });
});
