import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { truncateHead } from "@earendil-works/pi-coding-agent";
import { mkdtemp, realpath, rm, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { isAbsolute, join, relative } from "node:path";
import { Type } from "typebox";

const efforts = ["low", "medium", "high", "xhigh", "max"];
const timeoutMs = 10 * 60_000;
const heartbeatMs = 30_000;
export const namespaceArgs = (cwd: string) => [
  "--unshare-pid", "--die-with-parent", "--ro-bind", "/", "/", "--bind", cwd, cwd,
  "--dev", "/dev", "--proc", "/proc", "--",
];

export function denialSummary(actions: unknown[]): string {
  const kinds = new Set<string>();
  for (const action of actions) {
    const entry = action && typeof action === "object" ? action as Record<string, unknown> : {};
    const name = typeof action === "string" ? action : entry.action ?? entry.tool_name ?? entry.toolName ?? entry.name;
    const kind = typeof name === "string" ? name.toLowerCase() : "";
    if (["command", "bash", "shell", "terminal", "run_command", "execute_command"].includes(kind)) kinds.add("shell");
    else if (["edit", "write", "write_to_file", "replace_file_content", "multi_replace_file_content", "apply_patch"].includes(kind)) kinds.add("file edit");
    else if (["read", "read_file", "view_file", "list_dir", "grep_search"].includes(kind)) kinds.add("file read/search");
    else kinds.add("unrecognized tool");
  }
  return `${actions.length} denied (${[...kinds].join(", ")})`;
}
const defaultModel = "gemini-4-hydrogen-high";
const defaultEffort = "high";

export default function (pi: ExtensionAPI) {
  pi.registerFlag("agy-model", { type: "string", default: defaultModel, description: "Plain Pi worker model ID from agy models" });
  pi.registerFlag("agy-effort", { type: "string", default: defaultEffort, description: "Plain Pi worker effort: low, medium, high, xhigh, or max" });
  pi.registerFlag("agy-team", { type: "boolean", default: false, description: "Require a linked task worktree and pin the team worker to Hydrogen High" });

  pi.registerTool({
    name: "agy_worker",
    label: "AGY Worker",
    description: "Delegate a coding task to agy. Plain Pi uses its current directory; pi-team requires the linked task worktree root, issue and existing claim actor. Returns up to 16 KiB of the worker's final response.",
    promptGuidelines: [
      "In plain Pi, use agy_worker only when the user explicitly requests AGY delegation. In pi-team, follow the team workflow. Send a self-contained assignment, not chat history or secrets.",
      "Do not write to the workspace while agy_worker is running. Inspect the actual diff and independently verify the result before reporting success.",
    ],
    executionMode: "sequential",
    parameters: Type.Object({
      task: Type.String({ minLength: 1, maxLength: 16000 }),
      cwd: Type.Optional(Type.String({ description: "Absolute linked task worktree root (required in pi-team; omit in plain Pi)" })),
      issue: Type.Optional(Type.String({ pattern: "^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$", description: "Existing Beads issue claimed by the coordinator (pi-team only)" })),
      actor: Type.Optional(Type.String({ pattern: "^[A-Za-z0-9][A-Za-z0-9:._-]{0,159}$", description: "Exact unique Beads claim actor (pi-team only)" })),
    }, { additionalProperties: false }),
    async execute(_id, { task, cwd: worktree, issue, actor }, signal, onUpdate, ctx) {
      const team = pi.getFlag("agy-team") === true;
      const model = team ? defaultModel : pi.getFlag("agy-model");
      const effort = team ? defaultEffort : pi.getFlag("agy-effort");
      if (typeof model !== "string" || !/^[A-Za-z0-9][A-Za-z0-9._/-]*$/.test(model) ||
          typeof effort !== "string" || !efforts.includes(effort)) {
        throw new Error("Set --agy-model to an ID from agy models and --agy-effort to low, medium, high, xhigh, or max.");
      }
      if (!task.trim() || task.includes("\0")) throw new Error("Provide a non-empty AGY assignment without NUL characters.");
      signal?.throwIfAborted();

      let cwd = await realpath(ctx.cwd);
      if (team && (!issue || !actor)) throw new Error("Provide the Beads issue and exact existing claim actor; AGY does not claim issues.");
      if (team) {
        if (!worktree || !isAbsolute(worktree)) throw new Error("Provide the absolute linked task worktree root.");
        cwd = await realpath(worktree);
        const git = await pi.exec("git", ["rev-parse", "--path-format=absolute", "--show-toplevel", "--git-dir", "--git-common-dir"], {
          cwd, signal, timeout: 5000, maxBuffer: 64 * 1024,
        });
        const [root, gitDir, commonDir] = git.stdout.trimEnd().split("\n");
        if (git.code !== 0 || root !== cwd || !gitDir || !commonDir || gitDir === commonDir) {
          throw new Error("AGY team worker requires the root of a linked Git worktree, not the primary checkout.");
        }
      } else if (worktree !== undefined || issue !== undefined || actor !== undefined) {
        throw new Error("Start plain Pi in the desired workspace and omit cwd, issue and actor.");
      }
      const homeFromWorkspace = relative(cwd, await realpath(homedir()));
      if (cwd === "/" || (homeFromWorkspace !== ".." && !homeFromWorkspace.startsWith("../"))) {
        throw new Error("AGY requires a workspace that does not contain your home directory. Start Pi in the project directory.");
      }
      const sandbox = namespaceArgs(cwd);
      const isolation = await pi.exec("bwrap", [...sandbox, "true"], { cwd, signal, timeout: 5000, maxBuffer: 4096 });
      signal?.throwIfAborted();
      if (isolation.code !== 0) throw new Error("AGY requires working bubblewrap PID isolation; no worker was started.");
      const lock = await pi.exec("flock", ["--version"], { cwd, signal, timeout: 5000, maxBuffer: 4096 });
      signal?.throwIfAborted();
      if (lock.code !== 0) throw new Error("AGY requires util-linux flock; no worker was started.");
      try {
        const probe = await mkdtemp(join(cwd, ".pi-agy-probe-"));
        try {
          await writeFile(join(probe, "write-test"), "", { flag: "wx", mode: 0o600 });
        } finally {
          await rm(probe, { recursive: true, force: true });
        }
      } catch (error) {
        const code = (error as NodeJS.ErrnoException).code ?? "unknown";
        throw new Error(`AGY worktree write preflight failed (${code}); no worker was started.`);
      }
      signal?.throwIfAborted();
      const details = { model, effort, cwd };
      const launch = `agy (${model}, ${effort}) in ${cwd}`;
      onUpdate?.({ content: [{ type: "text", text: `Running ${launch}…` }], details });
      const prompt = [
        "Work only on the assignment below in the current directory. Do not commit, push, deploy, change tracker state, or delegate.",
        "Use native file tools to inspect and edit. Do not invoke terminal tools; the coordinator runs checks.",
        "Report files changed and any blockers. Do not include credentials or raw logs.",
        "",
        task.trim(),
      ].join("\n");

      const worker = new AbortController();
      const runningSignal = signal ? AbortSignal.any([signal, worker.signal]) : worker.signal;
      const heartbeat = async () => {
        const result = await pi.exec("bd", ["--actor", actor!, "heartbeat", issue!], {
          cwd, signal: runningSignal, timeout: 5000, maxBuffer: 4096,
        });
        if (result.code !== 0) throw new Error("Beads heartbeat failed");
      };
      if (team) {
        try {
          await heartbeat();
        } catch {
          signal?.throwIfAborted();
          throw new Error(`Cannot renew the existing Beads claim for ${issue}; no worker was started. Check ownership and tracker availability.`);
        }
      }
      runningSignal.throwIfAborted();
      let pending: Promise<void> | undefined;
      let leaseFailed = false;
      const timer = team ? setInterval(() => {
        if (pending || runningSignal.aborted) return;
        pending = heartbeat().catch(() => {
          if (!runningSignal.aborted) {
            leaseFailed = true;
            worker.abort();
          }
        }).finally(() => { pending = undefined; });
      }, heartbeatMs) : undefined;
      const result = await (async () => {
        try {
          return await pi.exec("flock", ["--no-fork", "--nonblock", "--conflict-exit-code", "73", cwd,
            "bwrap", ...sandbox, "agy", "--model", model, "--effort", effort, "--mode", "accept-edits",
            "--disable-slash-commands", "--output-format", "json", "--print", prompt,
          ], { cwd, signal: runningSignal, timeout: timeoutMs, maxBuffer: 256 * 1024 });
        } finally {
          clearInterval(timer);
          worker.abort();
          await pending;
        }
      })();
      if (leaseFailed) throw new Error(`Beads claim renewal failed for ${issue}; AGY stopped. Inspect the worktree and revalidate ownership before resuming.`);

      if (signal?.aborted) throw new Error("AGY was cancelled; inspect the workspace for partial changes.");
      if (result.truncated) throw new Error("AGY exceeded its output limit; inspect the workspace for partial changes.");
      if (result.killed) throw new Error("AGY exceeded its 10-minute timeout; inspect the workspace for partial changes.");
      let report: { status?: unknown; response?: unknown; denied_actions?: unknown } | null = null;
      try { report = JSON.parse(result.stdout); } catch { /* Handled below without surfacing raw output. */ }
      if (Array.isArray(report?.denied_actions) && report.denied_actions.length > 0) {
        throw new Error(`AGY non-interactive permission: ${denialSummary(report.denied_actions)}. Inspect partial edits. Run shell checks in the coordinator; do not infer a filesystem write denial.`);
      }
      if (result.code === 73 && !result.stdout) throw new Error("The worktree lock is busy or AGY exited before reporting; check for an active writer before retrying.");
      if (result.code !== 0) throw new Error(`AGY exited with code ${result.code}; inspect the workspace for partial changes.`);
      if (report === null) throw new Error("AGY returned no JSON report; inspect the workspace for partial changes.");
      if (report?.status !== "SUCCESS" || typeof report.response !== "string" || !report.response.trim()) {
        throw new Error("AGY returned no successful report; inspect the workspace for partial changes.");
      }
      const output = truncateHead(report.response.trim(), { maxBytes: 16 * 1024, maxLines: 500 });
      const note = output.truncated ? "\n[Worker response truncated; full output was not saved by Pi.]" : "";
      return { content: [{ type: "text", text: `${launch} reported:\n${output.content}${note}` }], details };
    },
  });
}
