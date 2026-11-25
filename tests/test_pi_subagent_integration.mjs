import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

const release = process.env.PI_TEST_RELEASE_PACKAGE;
if (process.argv.includes("--no-session")) {
  if (process.argv.includes("Task: progressing")) {
    const tick = setInterval(() => console.log(JSON.stringify({type:"tool_execution_end"})), 25);
    setTimeout(() => {
      clearInterval(tick);
      console.log(JSON.stringify({type:"message_end", message:{role:"assistant",stopReason:"stop",
        content:[{type:"text",text:"finished with extra time"}],usage:{cost:{total:0}}}}));
      console.log(JSON.stringify({type:"agent_end"}));
    }, 800);
  } else if (process.argv.includes("Task: isolation")) {
    assert.ok(process.argv.includes("--no-extensions"));
    assert.ok(process.argv.includes("--no-mcp"));
    assert.ok(process.argv.includes("--tools"));
    console.log(JSON.stringify({ type: "message_end", message: {
      role: "assistant", content: [{ type: "text", text: "isolated" }],
      stopReason: "stop", usage: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0, cost: { total: 0 } },
    } }));
    console.log(JSON.stringify({ type: "agent_end" }));
  } else if (process.argv.includes("Task: quota")) {
    console.error("provider returned HTTP 429: quota exceeded");
    process.exitCode = 1;
  } else if (!process.argv.includes("Task: empty")) {
    if (process.argv.includes("Task: finish")) {
      console.log(JSON.stringify({ type: "agent_end" }));
    }
    setInterval(() => {}, 1000);
  }
} else {
  test("the generated Pi tool isolates children and reports both timeout phases", {
    skip: !release && "Set PI_TEST_RELEASE_PACKAGE to the managed pi-coding-agent package directory",
    timeout: 25_000,
  }, async () => {
    const root = mkdtempSync(join(tmpdir(), "pi-team-test-"));
    const previousLimit = process.env.PI_TEAM_SUBAGENT_TIMEOUT_MS;
    try {
      const prepare = fileURLToPath(new URL("../pi/.pi/agent/team/prepare-subagent.py", import.meta.url));
      const subprocessArgs = ["-I", prepare, resolve(release, "examples/extensions/subagent/index.ts"), join(root, "cache")];
      const generated = execFileSync("python3", subprocessArgs, { encoding: "utf8" }).trim();
      assert.equal(execFileSync("python3", subprocessArgs, { encoding: "utf8" }).trim(), generated);
      const unsupported = join(root, "unsupported.ts");
      writeFileSync(unsupported, "export default () => {};\n");
      assert.throws(() => execFileSync("python3", ["-I", prepare, unsupported, join(root, "cache")], {
        stdio: "pipe",
      }), /unsupported bundled subagent layout/);
      const agents = join(root, ".pi", "agents");
      mkdirSync(agents, { recursive: true });
      writeFileSync(join(agents, "fixture.md"), "---\nname: fixture\ndescription: Synthetic test agent\ntools: [read, grep, find, ls]\n---\n");
      const { loadExtensions } = await import(pathToFileURL(resolve(release, "dist/core/extensions/loader.js")));
      const loaded = await loadExtensions([generated], root);
      assert.deepEqual(loaded.errors, []);
      const tool = loaded.extensions[0].tools.get("subagent");
      const decisions = [];
      const modelRegistry = {
        getModelOfType: () => ({}),
        classify: async (_, {state}) => {
          decisions.push(state);
          return {stopReason:"stop", answers:{progress:{type:"bool",probability:state.toolEvents > 0 ? 0.9 : 0.05}}};
        },
      };
      const execute = (task, cwd) => tool.definition.execute("fixture", {
        agent: "fixture", agentScope: "project", task, cwd,
      }, undefined, undefined, { cwd: root, hasUI: false, modelRegistry });

      process.env.PI_TEAM_SUBAGENT_TIMEOUT_MS = "500";
      const running = await execute("hang");
      assert.equal(running.details.results[0].status, "failed");
      assert.match(running.content[0].text, /timed out after 500 ms before its turn ended/);

      const progressing = await execute("progressing");
      assert.equal(progressing.details.results[0].status, "completed");
      assert.match(progressing.content[0].text, /finished with extra time/);
      assert.ok(decisions.some(state => state.toolEvents > 0));
      process.env.PI_TEAM_SUBAGENT_TIMEOUT_MS = "18000";
      const closing = await execute("finish");
      assert.equal(closing.details.results[0].status, "failed");
      assert.match(closing.content[0].text, /after its turn ended.*within 10000 ms/);

      const isolated = await execute("isolation");
      assert.equal(isolated.details.results[0].status, "completed");
      assert.equal(isolated.content[0].text, "isolated");

      const invalid = await execute("hang", join(root, "missing"));
      assert.equal(invalid.details.results[0].exitCode, null);
      assert.match(invalid.details.results[0].blocker, /not an accessible directory/);
      assert.match((await execute("hang", ".")).details.results[0].blocker, /absolute path/);
      assert.match((await execute("empty")).details.results[0].blocker, /without a final assistant response/);
      assert.match((await execute("quota")).details.results[0].blocker, /provider rate or quota limit/);
    } finally {
      if (previousLimit === undefined) delete process.env.PI_TEAM_SUBAGENT_TIMEOUT_MS;
      else process.env.PI_TEAM_SUBAGENT_TIMEOUT_MS = previousLimit;
      rmSync(root, { recursive: true, force: true });
    }
  });
}
