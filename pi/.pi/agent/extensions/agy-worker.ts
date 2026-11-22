import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { truncateHead } from "@earendil-works/pi-coding-agent";
import { realpath } from "node:fs/promises";
import { isAbsolute } from "node:path";
import { Type } from "typebox";

const efforts = ["low", "medium", "high", "xhigh", "max"];
const timeoutMs = 10 * 60_000;
const defaultModel = "gemini-4-hydrogen-high";
const defaultEffort = "high";

export default function (pi: ExtensionAPI) {
  pi.registerFlag("agy-model", { type: "string", default: defaultModel, description: "Plain Pi worker model ID from agy models" });
  pi.registerFlag("agy-effort", { type: "string", default: defaultEffort, description: "Plain Pi worker effort: low, medium, high, xhigh, or max" });
  pi.registerFlag("agy-team", { type: "boolean", default: false, description: "Require a linked task worktree and pin the team worker to Hydrogen High" });

  pi.registerTool({
    name: "agy_worker",
    label: "AGY Worker",
    description: "Delegate a coding task to agy. Plain Pi uses its current directory; pi-team requires the linked task worktree root. Returns up to 16 KiB of the worker's final response.",
    promptGuidelines: [
      "In plain Pi, use agy_worker only when the user explicitly requests AGY delegation. In pi-team, follow the team workflow. Send a self-contained assignment, not chat history or secrets.",
      "Do not write to the workspace while agy_worker is running. Inspect the actual diff and independently verify the result before reporting success.",
    ],
    executionMode: "sequential",
    parameters: Type.Object({
      task: Type.String({ minLength: 1, maxLength: 16000 }),
      cwd: Type.Optional(Type.String({ description: "Absolute linked task worktree root (required in pi-team; omit in plain Pi)" })),
    }, { additionalProperties: false }),
    async execute(_id, { task, cwd: worktree }, signal, onUpdate, ctx) {
      const team = pi.getFlag("agy-team") === true;
      const model = team ? defaultModel : pi.getFlag("agy-model");
      const effort = team ? defaultEffort : pi.getFlag("agy-effort");
      if (typeof model !== "string" || !/^[A-Za-z0-9][A-Za-z0-9._/-]*$/.test(model) ||
          typeof effort !== "string" || !efforts.includes(effort)) {
        throw new Error("Set --agy-model to an ID from agy models and --agy-effort to low, medium, high, xhigh, or max.");
      }
      if (!task.trim() || task.includes("\0")) throw new Error("Provide a non-empty AGY assignment without NUL characters.");
      signal?.throwIfAborted();

      let cwd = ctx.cwd;
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
      } else if (worktree !== undefined) {
        throw new Error("Start plain Pi in the desired workspace and omit cwd.");
      }
      signal?.throwIfAborted();
      const details = { model, effort, cwd };
      const launch = `agy (${model}, ${effort}) in ${cwd}`;
      onUpdate?.({ content: [{ type: "text", text: `Running ${launch}…` }], details });
      const prompt = [
        "Work only on the assignment below in the current directory. Do not commit, push, deploy, change tracker state, or delegate.",
        "Report files changed, checks actually run and their results, and any blockers. Do not include credentials or raw logs.",
        "",
        task.trim(),
      ].join("\n");

      const result = await pi.exec("agy", [
        "--model", model, "--effort", effort, "--mode", "accept-edits",
        "--disable-slash-commands", "--output-format", "json", "--print", prompt,
      ], { cwd, signal, timeout: timeoutMs, maxBuffer: 256 * 1024 });

      if (signal?.aborted) throw new Error("AGY was cancelled; inspect the workspace for partial changes.");
      if (result.truncated) throw new Error("AGY exceeded its output limit; inspect the workspace for partial changes.");
      if (result.killed) throw new Error("AGY exceeded its 10-minute timeout; inspect the workspace for partial changes.");
      if (result.code !== 0) throw new Error(`AGY exited with code ${result.code}; inspect the workspace for partial changes.`);

      let report: { status?: unknown; response?: unknown; denied_actions?: unknown } | null;
      try {
        report = JSON.parse(result.stdout);
      } catch {
        throw new Error("AGY returned invalid JSON; inspect the workspace for partial changes.");
      }
      if (Array.isArray(report?.denied_actions) && report.denied_actions.length > 0) {
        throw new Error("AGY could not get tool permission in non-interactive mode; inspect the workspace for partial changes. Do not assume the task completed.");
      }
      if (report?.status !== "SUCCESS" || typeof report.response !== "string" || !report.response.trim()) {
        throw new Error("AGY returned no successful report; inspect the workspace for partial changes.");
      }
      const output = truncateHead(report.response.trim(), { maxBytes: 16 * 1024, maxLines: 500 });
      const note = output.truncated ? "\n[Worker response truncated; full output was not saved by Pi.]" : "";
      return { content: [{ type: "text", text: `${launch} reported:\n${output.content}${note}` }], details };
    },
  });
}
