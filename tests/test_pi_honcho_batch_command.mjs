import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { rmSync } from 'node:fs';
import { chmod, mkdir, mkdtemp, readFile, rm, symlink, writeFile } from 'node:fs/promises';
import { stripTypeScriptTypes } from 'node:module';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { pathToFileURL } from 'node:url';

const source = await readFile(new URL('../pi/.pi/agent/honcho-cli/batch-command.ts', import.meta.url), 'utf8');
const moduleSource = stripTypeScriptTypes(source);
const modDir = await mkdtemp(join(tmpdir(), 'pi-honcho-mod-'));
const modPath = join(modDir, 'batch-command.mjs');
await writeFile(modPath, moduleSource, 'utf8');
process.once('exit', () => {
  rmSync(modDir, { recursive: true, force: true });
});
const { default: extension } = await import(pathToFileURL(modPath).href);

const LAUNCH_PIN_SYMBOL = Symbol.for('pi.honcho.batch.launchPin');
function resetLaunchPin() {
  delete globalThis[LAUNCH_PIN_SYMBOL];
}

const DIGEST_A = 'a'.repeat(64);
const PREVIEW_TEXT = 'Honcho batch preview (pi_session_id=sess-1, items=1)\n[1] repo=dotfiles destination=https://honcho.example/mcp\n    note: SECRET_NOTE_BODY';
const OK_RESULTS = [
  { repo: 'dotfiles', status: 'verified', reason: 'conclusion verified via readback' },
  { repo: 'infra', status: 'already present', reason: 'exact conclusion already present' },
  { repo: 'app', status: 'blocked', reason: 'pending conclusion absent on readback; automatic retry disabled' },
];

async function withBatchEnv(t, manifestPath, extraEnv = {}) {
  const saved = {
    manifest: process.env.PI_HONCHO_BATCH_MANIFEST,
    grant: process.env.PI_HONCHO_PUBLISH_GRANT,
    offline: process.env.PI_OFFLINE,
    hasOffline: Object.prototype.hasOwnProperty.call(process.env, 'PI_OFFLINE'),
  };
  resetLaunchPin();
  if (manifestPath === undefined) delete process.env.PI_HONCHO_BATCH_MANIFEST;
  else process.env.PI_HONCHO_BATCH_MANIFEST = manifestPath;
  if ('PI_HONCHO_PUBLISH_GRANT' in extraEnv) {
    process.env.PI_HONCHO_PUBLISH_GRANT = extraEnv.PI_HONCHO_PUBLISH_GRANT;
  } else {
    delete process.env.PI_HONCHO_PUBLISH_GRANT;
  }
  if ('PI_OFFLINE' in extraEnv) {
    process.env.PI_OFFLINE = extraEnv.PI_OFFLINE;
  } else {
    delete process.env.PI_OFFLINE;
  }
  t.after(() => {
    resetLaunchPin();
    if (saved.manifest === undefined) delete process.env.PI_HONCHO_BATCH_MANIFEST;
    else process.env.PI_HONCHO_BATCH_MANIFEST = saved.manifest;
    if (saved.grant === undefined) delete process.env.PI_HONCHO_PUBLISH_GRANT;
    else process.env.PI_HONCHO_PUBLISH_GRANT = saved.grant;
    if (!saved.hasOffline || saved.offline === undefined) delete process.env.PI_OFFLINE;
    else process.env.PI_OFFLINE = saved.offline;
  });
}

function createHarness({
  previewResult = { code: 0, stdout: JSON.stringify({ digest: DIGEST_A, preview: PREVIEW_TEXT }), stderr: '' },
  applyResult = { code: 0, stdout: JSON.stringify({ digest: DIGEST_A, results: OK_RESULTS }), stderr: '' },
  execImpl,
} = {}) {
  const commands = new Map();
  const tools = [];
  const listeners = new Map();
  const execCalls = [];
  const sentMessages = [];

  const pi = {
    on(event, handler) {
      if (!listeners.has(event)) listeners.set(event, []);
      listeners.get(event).push(handler);
    },
    registerCommand(name, opts) {
      commands.set(name, opts);
    },
    registerTool(tool) {
      tools.push(tool);
    },
    async exec(cmd, args, options) {
      execCalls.push({ cmd, args, options });
      if (execImpl) return execImpl(cmd, args, options);
      if (args.includes('preview')) return typeof previewResult === 'function' ? previewResult() : previewResult;
      if (args.includes('apply')) return typeof applyResult === 'function' ? applyResult() : applyResult;
      throw new Error(`unexpected exec: ${cmd} ${args.join(' ')}`);
    },
    sendMessage(message, options) {
      sentMessages.push({ message, options });
    },
  };

  extension(pi);

  return {
    commands,
    tools,
    execCalls,
    sentMessages,
    async emitSessionStart(event, ctx) {
      for (const fn of listeners.get('session_start') ?? []) {
        await fn(event, ctx);
      }
    },
    async invoke(args, ctx) {
      const cmd = commands.get('honcho-batch');
      assert.ok(cmd, 'expected /honcho-batch command to be registered');
      return cmd.handler(args, ctx);
    },
  };
}

function makeCtx({
  mode = 'tui',
  hasUI = true,
  idle = true,
  sessionId = 'sess-1',
  cwd = process.cwd(),
  editor = async (_title, text) => text,
  confirm = async () => true,
} = {}) {
  const notifications = [];
  const statuses = [];
  const confirms = [];
  const editors = [];
  let currentSessionId = sessionId;
  let currentCwd = cwd;

  const ctx = {
    mode,
    hasUI,
    get cwd() { return currentCwd; },
    isIdle: () => idle,
    sessionManager: {
      getSessionId: () => currentSessionId,
      getCwd: () => currentCwd,
    },
    ui: {
      notify(message, level) { notifications.push({ message, level }); },
      setStatus(key, text) { statuses.push({ key, text }); },
      async editor(title, prefill) {
        editors.push({ title, prefill });
        return editor(title, prefill);
      },
      async confirm(title, message) {
        confirms.push({ title, message });
        return confirm(title, message);
      },
    },
  };

  return {
    ctx,
    notifications,
    statuses,
    confirms,
    editors,
    setSessionId(next) { currentSessionId = next; },
    setCwd(next) { currentCwd = next; },
  };
}

test('batch command registers only /honcho-batch in launcher mode and never registers tools', async t => {
  await withBatchEnv(t, undefined);
  const none = createHarness();
  assert.equal(none.commands.size, 0);
  assert.equal(none.tools.length, 0);

  await withBatchEnv(t, 'relative/manifest.json');
  const rel = createHarness();
  assert.equal(rel.commands.size, 0);

  await withBatchEnv(t, '/private/manifest.json', { PI_HONCHO_PUBLISH_GRANT: '/private/grant.json' });
  const both = createHarness();
  assert.equal(both.commands.size, 0);

  await withBatchEnv(t, '/private/manifest.json');
  const active = createHarness();
  assert.deepEqual([...active.commands.keys()], ['honcho-batch']);
  assert.equal(active.tools.length, 0);
});

test('non-tui, missing UI, busy session, and command arguments cause zero preview or apply', async t => {
  await withBatchEnv(t, '/private/manifest.json');
  const h = createHarness();
  await h.emitSessionStart({ reason: 'startup' }, makeCtx().ctx);

  await h.invoke('', makeCtx({ mode: 'print' }).ctx);
  await h.invoke('', makeCtx({ hasUI: false }).ctx);
  await h.invoke('', makeCtx({ idle: false }).ctx);
  await h.invoke('--force', makeCtx().ctx);

  assert.equal(h.execCalls.length, 0);
  assert.equal(h.sentMessages.length, 0);
});

test('overlapping invocations are refused without double preview or apply', async t => {
  await withBatchEnv(t, '/private/manifest.json');
  let releaseEditor;
  const editorGate = new Promise(resolve => { releaseEditor = resolve; });
  const h = createHarness();
  const { ctx, notifications } = makeCtx({
    editor: async (_t, text) => {
      await editorGate;
      return text;
    },
  });
  await h.emitSessionStart({ reason: 'startup' }, ctx);

  const first = h.invoke('', ctx);
  await new Promise(resolve => setTimeout(resolve, 10));
  await h.invoke('', ctx);
  assert.ok(notifications.some(n => /already in progress/i.test(n.message)));
  releaseEditor();
  await first;
  assert.equal(h.execCalls.filter(c => c.args.includes('apply')).length, 1);
});

test('aborted, modified, or declined review causes zero apply', async t => {
  await withBatchEnv(t, '/private/manifest.json');

  for (const [label, uiOpts] of [
    ['aborted editor', { editor: async () => undefined }],
    ['modified editor', { editor: async (_t, text) => `${text}\nextra` }],
    ['declined confirm', { confirm: async () => false }],
  ]) {
    resetLaunchPin();
    const h = createHarness();
    const { ctx } = makeCtx(uiOpts);
    await h.emitSessionStart({ reason: 'startup' }, ctx);
    await h.invoke('', ctx);
    assert.equal(h.execCalls.filter(c => c.args.includes('apply')).length, 0, `${label} must not apply`);
    assert.equal(h.sentMessages.length, 0, `${label} must not emit status report`);
  }
});

test('aborted, truncated, or malformed preview causes zero apply and leaks no raw stderr', async t => {
  await withBatchEnv(t, '/private/manifest.json');
  for (const previewResult of [
    { code: 1, stdout: '', stderr: 'token=SECRET_TOKEN /private/grant.json' },
    { code: 0, truncated: true, stdout: JSON.stringify({ digest: DIGEST_A, preview: PREVIEW_TEXT }), stderr: '' },
    { code: 0, stdout: '{"digest":"bad","preview":"ok"}', stderr: '' },
    { code: 0, stdout: 'not-json', stderr: '' },
  ]) {
    resetLaunchPin();
    const h = createHarness({ previewResult });
    const { ctx, notifications } = makeCtx();
    await h.emitSessionStart({ reason: 'startup' }, ctx);
    await h.invoke('', ctx);
    assert.equal(h.execCalls.filter(c => c.args.includes('apply')).length, 0);
    for (const n of notifications) {
      assert.ok(!n.message.includes('SECRET_TOKEN'));
      assert.ok(!n.message.includes('/private/grant.json'));
    }
  }
});

test('changed session or cwd rejects before apply; safe reload in same session succeeds', async t => {
  await withBatchEnv(t, '/private/manifest.json');

  const h1 = createHarness();
  const s1 = makeCtx({ sessionId: 'sess-1' });
  await h1.emitSessionStart({ reason: 'startup' }, s1.ctx);
  s1.setSessionId('sess-2');
  await h1.emitSessionStart({ reason: 'new' }, s1.ctx);
  await h1.invoke('', s1.ctx);
  assert.equal(h1.execCalls.length, 0);

  resetLaunchPin();
  const h2 = createHarness();
  const s2 = makeCtx({ sessionId: 'sess-1' });
  await h2.emitSessionStart({ reason: 'startup' }, s2.ctx);
  const origConfirm = s2.ctx.ui.confirm;
  s2.ctx.ui.confirm = async (title, msg) => {
    s2.setSessionId('sess-2');
    return origConfirm(title, msg);
  };
  await h2.invoke('', s2.ctx);
  assert.equal(h2.execCalls.filter(c => c.args.includes('apply')).length, 0);

  resetLaunchPin();
  const h3 = createHarness();
  const s3 = makeCtx({ sessionId: 'sess-1' });
  await h3.emitSessionStart({ reason: 'startup' }, s3.ctx);
  const otherDir = await mkdtemp(join(tmpdir(), 'pi-honcho-cwd-'));
  const origCwd = process.cwd();
  t.after(() => {
    process.chdir(origCwd);
    return rm(otherDir, { recursive: true, force: true });
  });
  s3.ctx.ui.confirm = async () => {
    process.chdir(otherDir);
    return true;
  };
  await h3.invoke('', s3.ctx);
  assert.equal(h3.execCalls.filter(c => c.args.includes('apply')).length, 0);
  process.chdir(origCwd);

  resetLaunchPin();
  const h4 = createHarness();
  const s4 = makeCtx({ sessionId: 'sess-1' });
  await h4.emitSessionStart({ reason: 'startup' }, s4.ctx);
  await h4.emitSessionStart({ reason: 'reload' }, s4.ctx);
  await h4.invoke('', s4.ctx);
  assert.equal(h4.execCalls.filter(c => c.args.includes('apply')).length, 1);
});

test('process pin fails closed without startup, ignores replacement startup, and allows reload only in original session', async t => {
  await withBatchEnv(t, '/private/manifest.json');

  const noPin = createHarness();
  await noPin.invoke('', makeCtx({ sessionId: 'sess-1' }).ctx);
  assert.equal(noPin.execCalls.length, 0);

  for (const reason of ['reload', 'new', 'resume', 'fork']) {
    resetLaunchPin();
    const h = createHarness();
    const s = makeCtx({ sessionId: 'sess-1' });
    await h.emitSessionStart({ reason }, s.ctx);
    await h.invoke('', s.ctx);
    assert.equal(h.execCalls.length, 0, `${reason} without startup must fail closed`);
  }

  resetLaunchPin();
  const inst1 = createHarness();
  const origCtx = makeCtx({ sessionId: 'sess-orig' });
  await inst1.emitSessionStart({ reason: 'startup' }, origCtx.ctx);

  const inst2 = createHarness();
  const otherSessCtx = makeCtx({ sessionId: 'sess-replacement' });
  await inst2.emitSessionStart({ reason: 'startup' }, otherSessCtx.ctx);
  await inst2.invoke('', otherSessCtx.ctx);
  assert.equal(inst2.execCalls.length, 0);

  const otherDir = await mkdtemp(join(tmpdir(), 'pi-honcho-pin-cwd-'));
  t.after(() => rm(otherDir, { recursive: true, force: true }));
  const otherCwdCtx = makeCtx({ sessionId: 'sess-orig', cwd: otherDir });
  await inst2.emitSessionStart({ reason: 'startup' }, otherCwdCtx.ctx);
  await inst2.invoke('', otherCwdCtx.ctx);
  assert.equal(inst2.execCalls.length, 0);

  for (const reason of ['new', 'resume', 'fork', 'reload']) {
    await inst2.emitSessionStart({ reason }, otherSessCtx.ctx);
    await inst2.invoke('', otherSessCtx.ctx);
    assert.equal(inst2.execCalls.length, 0, `${reason} in other session must not apply`);
  }

  await inst2.emitSessionStart({ reason: 'reload' }, origCtx.ctx);
  await inst2.invoke('', origCtx.ctx);
  assert.equal(inst2.execCalls.filter(c => c.args.includes('apply')).length, 1);
  assert.equal(inst2.sentMessages.length, 1);
});

test('successful approval passes exact fingerprint, -I -B, maxBuffer, sanitizes output, and emits status report', async t => {
  await withBatchEnv(t, '/private/manifest.json');
  const h = createHarness();
  const { ctx, confirms } = makeCtx({ sessionId: 'sess-42' });
  await h.emitSessionStart({ reason: 'startup' }, ctx);
  await h.invoke('', ctx);

  assert.equal(h.execCalls.length, 2);
  const [previewCall, applyCall] = h.execCalls;
  assert.equal(previewCall.cmd, '/usr/bin/python3');
  assert.deepEqual(previewCall.args.slice(0, 2), ['-I', '-B']);
  assert.ok(previewCall.args[2].endsWith('/batch.py'));
  assert.deepEqual(previewCall.args.slice(3), ['preview', '/private/manifest.json', 'sess-42']);
  assert.equal(previewCall.options.maxBuffer, 1024 * 1024);

  assert.equal(confirms.length, 1);
  assert.ok(confirms[0].title.includes(DIGEST_A.slice(0, 12)));
  assert.ok(confirms[0].message.includes(DIGEST_A));

  assert.equal(applyCall.cmd, '/usr/bin/python3');
  assert.deepEqual(applyCall.args.slice(0, 2), ['-I', '-B']);
  assert.ok(applyCall.args[2].endsWith('/batch.py'));
  assert.deepEqual(applyCall.args.slice(3), ['apply', '/private/manifest.json', 'sess-42', DIGEST_A]);
  assert.equal(applyCall.options.maxBuffer, 128 * 1024);

  assert.equal(h.sentMessages.length, 1);
  const [{ message, options }] = h.sentMessages;
  assert.equal(options.triggerTurn, false);
  assert.equal(message.display, true);
  assert.match(message.content, new RegExp(DIGEST_A));
  assert.match(message.content, /dotfiles: verified \(conclusion verified via readback\)/);
  assert.match(message.content, /infra: already present \(exact conclusion already present\)/);
  assert.match(message.content, /app: blocked \(pending conclusion absent on readback; automatic retry disabled\)/);
  assert.ok(!message.content.includes('SECRET_NOTE_BODY'));
  assert.ok(!message.content.includes('/private/manifest.json'));
});

test('aborted, truncated, or invalid apply emits sanitized warning without blind retry or leaked secrets', async t => {
  await withBatchEnv(t, '/private/manifest.json');
  for (const applyResult of [
    { code: 1, killed: true, stdout: 'RAW_STDOUT_LEAK', stderr: 'token=SECRET_TOKEN /private/grant.json' },
    { code: 0, truncated: true, stdout: JSON.stringify({ digest: DIGEST_A, results: OK_RESULTS }), stderr: '' },
    { code: 0, stdout: JSON.stringify({ digest: 'b'.repeat(64), results: OK_RESULTS }), stderr: '' },
    { code: 0, stdout: JSON.stringify({ digest: DIGEST_A, results: [{ repo: 'dotfiles', status: 'unknown', reason: 'bad' }] }), stderr: '' },
  ]) {
    resetLaunchPin();
    const h = createHarness({ applyResult });
    const { ctx } = makeCtx();
    await h.emitSessionStart({ reason: 'startup' }, ctx);
    await h.invoke('', ctx);
    assert.equal(h.sentMessages.length, 1);
    const content = h.sentMessages[0].message.content;
    assert.match(content, /Some repositories may already have been attempted/);
    assert.match(content, /Never blindly retry/);
    assert.match(content, /exact-readback recovery/);
    assert.ok(!content.includes('RAW_STDOUT_LEAK'));
    assert.ok(!content.includes('SECRET_TOKEN'));
    assert.ok(!content.includes('/private/grant.json'));
    assert.ok(!content.includes('SECRET_NOTE_BODY'));
  }
});

test('session change during apply suppresses posting status report and data URL fails closed without cwd fallback', async t => {
  await withBatchEnv(t, '/private/manifest.json');
  const s = makeCtx({ sessionId: 'sess-1' });
  const h = createHarness({
    execImpl(_cmd, args) {
      if (args.includes('preview')) {
        return { code: 0, stdout: JSON.stringify({ digest: DIGEST_A, preview: PREVIEW_TEXT }), stderr: '' };
      }
      s.setSessionId('sess-2');
      return { code: 0, stdout: JSON.stringify({ digest: DIGEST_A, results: OK_RESULTS }), stderr: '' };
    },
  });
  await h.emitSessionStart({ reason: 'startup' }, s.ctx);
  await h.invoke('', s.ctx);
  assert.equal(h.execCalls.filter(c => c.args.includes('apply')).length, 1);
  assert.equal(h.sentMessages.length, 0);

  resetLaunchPin();
  const savedHome = process.env.HOME;
  delete process.env.HOME;
  t.after(() => {
    if (savedHome === undefined) delete process.env.HOME;
    else process.env.HOME = savedHome;
  });
  const { default: dataExt } = await import(
    `data:text/javascript;base64,${Buffer.from(moduleSource).toString('base64')}`
  );
  const commands = new Map();
  const execCalls = [];
  dataExt({
    on() {},
    registerCommand(name, opts) { commands.set(name, opts); },
    async exec(cmd, args, options) {
      execCalls.push({ cmd, args, options });
      return { code: 0, stdout: '{}' };
    },
  });
  assert.equal(commands.size, 0);
  assert.equal(execCalls.length, 0);
});

test('handler rejects PI_OFFLINE by presence including empty string', async t => {
  for (const offlineVal of ['', '1']) {
    await withBatchEnv(t, '/private/manifest.json', { PI_OFFLINE: offlineVal });
    const h = createHarness();
    const { ctx } = makeCtx({ sessionId: 'sess-1' });
    await h.emitSessionStart({ reason: 'startup' }, ctx);
    await h.invoke('', ctx);
    assert.equal(h.execCalls.length, 0);
    assert.equal(h.sentMessages.length, 0);
  }
});

test('pi-honcho wrapper rejects noninteractive, nested, offline, extra args, and symlink manifests without launching Pi', async t => {
  const home = await mkdtemp(join(tmpdir(), 'pi-honcho-wrapper-'));
  t.after(() => rm(home, { recursive: true, force: true }));

  const binDir = join(home, '.pi', 'agent', 'bin');
  await mkdir(binDir, { recursive: true });
  const marker = join(home, 'launched.txt');
  for (const binName of ['pi', 'pi-team']) {
    const stub = join(binDir, binName);
    await writeFile(
      stub,
      `#!/bin/sh\nprintf '%s|%s|%s|%s\\n' "${binName}" "$*" "\${PI_HONCHO_BATCH_MANIFEST-}" "\${PI_HONCHO_NESTED-}" > "${marker}"\n`,
      { mode: 0o700 },
    );
    await chmod(stub, 0o700);
  }

  const manifest = join(home, 'manifest.json');
  await writeFile(manifest, '{"items":[]}\n', { mode: 0o600 });
  const linkManifest = join(home, 'link.json');
  await symlink(manifest, linkManifest);

  const wrapper = new URL('../pi/.pi/agent/bin/pi-honcho', import.meta.url).pathname;
  const baseEnv = { ...process.env, HOME: home };
  delete baseEnv.PI_HONCHO_NESTED;
  delete baseEnv.PI_HONCHO_PUBLISH_GRANT;
  delete baseEnv.PI_HONCHO_BATCH_MANIFEST;
  delete baseEnv.PI_OFFLINE;

  const nonTty = spawnSync(wrapper, ['pi', '--batch', manifest], {
    env: baseEnv,
    stdio: ['pipe', 'pipe', 'pipe'],
    encoding: 'utf8',
  });
  assert.notEqual(nonTty.status, 0);
  await assert.rejects(readFile(marker, 'utf8'));

  const extraArg = spawnSync(wrapper, ['pi', '--batch', manifest, '--continue'], {
    env: baseEnv,
    stdio: ['pipe', 'pipe', 'pipe'],
    encoding: 'utf8',
  });
  assert.equal(extraArg.status, 2);
  await assert.rejects(readFile(marker, 'utf8'));

  const relPath = spawnSync(wrapper, ['pi', '--batch', 'manifest.json'], {
    env: baseEnv,
    stdio: ['pipe', 'pipe', 'pipe'],
    encoding: 'utf8',
  });
  assert.equal(relPath.status, 2);
  await assert.rejects(readFile(marker, 'utf8'));

  const nested = spawnSync(wrapper, ['pi', '--batch', manifest], {
    env: { ...baseEnv, PI_HONCHO_NESTED: '1' },
    stdio: ['pipe', 'pipe', 'pipe'],
    encoding: 'utf8',
  });
  assert.notEqual(nested.status, 0);
  await assert.rejects(readFile(marker, 'utf8'));

  const singleGrant = join(home, 'grant.json');
  await writeFile(singleGrant, '{}\n', { mode: 0o600 });
  for (const launcher of ['pi', 'pi-team']) {
    for (const offlineVal of ['', '1']) {
      await rm(marker, { force: true });
      const offlineSingle = spawnSync(wrapper, [launcher, singleGrant, '--help'], {
        env: { ...baseEnv, PI_OFFLINE: offlineVal },
        stdio: ['pipe', 'pipe', 'pipe'],
        encoding: 'utf8',
      });
      assert.equal(offlineSingle.status, 2);
      await assert.rejects(readFile(marker, 'utf8'));
    }

    await rm(marker, { force: true });
    const single = spawnSync(wrapper, [launcher, singleGrant, '--help'], {
      env: baseEnv,
      stdio: ['pipe', 'pipe', 'pipe'],
      encoding: 'utf8',
    });
    assert.equal(single.status, 0, single.stderr);
    const launchedArgs = await readFile(marker, 'utf8');
    assert.match(launchedArgs, new RegExp(`^${launcher}\\|--extension .*/honcho-cli/publisher\\.ts --help`));
  }

  await rm(marker, { force: true });
  const ptyScript = `
import os, pty, select, subprocess, sys
master, slave = pty.openpty()
proc = subprocess.Popen(
    sys.argv[1:],
    stdin=slave, stdout=slave, stderr=slave,
    env=os.environ, close_fds=True,
)
os.close(slave)
while proc.poll() is None:
    r, _, _ = select.select([master], [], [], 0.2)
    if r:
        try:
            if not os.read(master, 4096):
                break
        except OSError:
            break
os.close(master)
sys.exit(proc.wait())
`;
  const ptySymlink = spawnSync('/usr/bin/python3', ['-c', ptyScript, wrapper, 'pi', '--batch', linkManifest], {
    env: baseEnv,
    encoding: 'utf8',
  });
  assert.notEqual(ptySymlink.status, 0);
  await assert.rejects(readFile(marker, 'utf8'));

  for (const nestedKey of ['PI_HONCHO_NESTED', 'PI_HONCHO_PUBLISH_GRANT', 'PI_HONCHO_BATCH_MANIFEST']) {
    const ptyEmptyNested = spawnSync('/usr/bin/python3', ['-c', ptyScript, wrapper, 'pi', '--batch', manifest], {
      env: { ...baseEnv, [nestedKey]: '' },
      encoding: 'utf8',
    });
    assert.equal(ptyEmptyNested.status, 2, `${nestedKey}="" must reject under PTY`);
    await assert.rejects(readFile(marker, 'utf8'));
  }

  for (const launcher of ['pi', 'pi-team']) {
    for (const offlineVal of ['', '1']) {
      await rm(marker, { force: true });
      const ptyOffline = spawnSync('/usr/bin/python3', ['-c', ptyScript, wrapper, launcher, '--batch', manifest], {
        env: { ...baseEnv, PI_OFFLINE: offlineVal },
        encoding: 'utf8',
      });
      assert.equal(ptyOffline.status, 2, `${launcher} PI_OFFLINE=${JSON.stringify(offlineVal)} must reject under PTY`);
      await assert.rejects(readFile(marker, 'utf8'));
    }

    await rm(marker, { force: true });
    const ptyValid = spawnSync('/usr/bin/python3', ['-c', ptyScript, wrapper, launcher, '--batch', manifest], {
      env: baseEnv,
      encoding: 'utf8',
    });
    assert.equal(ptyValid.status, 0, ptyValid.stderr);
    const batchLaunch = await readFile(marker, 'utf8');
    assert.equal(
      batchLaunch.trim(),
      `${launcher}|--extension ${join(home, '.pi', 'agent', 'honcho-cli', 'batch-command.ts')}|${manifest}|`,
    );
  }
});
