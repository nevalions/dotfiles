import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdir, mkdtemp, readFile, rm, readdir, symlink, writeFile } from 'node:fs/promises';
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
