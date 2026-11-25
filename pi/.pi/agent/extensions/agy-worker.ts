import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { truncateHead } from "@earendil-works/pi-coding-agent";
import type { Stats } from "node:fs";
import { lstat, mkdtemp, realpath, rm, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { isAbsolute, join, relative } from "node:path";
import { activityLease, routeIssue, warn, writeAlternate } from "../team/team-health.mjs";
import { runAgyStream } from "../team/agy-stream.mjs";
import { worktreeSampler } from "../team/worktree-activity.mjs";
import { Type } from "typebox";

const efforts = ["low", "medium", "high", "xhigh", "max"];
const timeoutMs = 10 * 60_000;
const heartbeatMs = 30_000;
export const namespaceArgs = (cwd: string, privateAgentDir?: string) => [
  "--unshare-pid", "--die-with-parent", "--ro-bind", "/", "/", "--bind", cwd, cwd,
  ...(privateAgentDir ? ["--overlay-src", privateAgentDir, "--tmp-overlay", privateAgentDir] : []),
  "--dev", "/dev", "--proc", "/proc", "--",
];

type DenialCategory = "shell" | "file edit" | "file read/search";
type TargetScope =
  | "existing in-worktree regular file"
  | "other existing in-worktree path"
  | "outside worktree path"
  | "target scope unavailable"
  | "target scope unknown";

const actionGroups: Record<DenialCategory, readonly string[]> = {
  shell: [
    "command", "bash", "sh", "zsh", "shell", "terminal",
    "run_command", "execute_command", "exec_command", "command_execution",
  ],
  "file edit": [
    "edit", "edit_file", "write", "write_file", "write_to_file", "create_file",
    "delete_file", "remove_file", "move_file", "rename_file",
    "replace_file_content", "multi_replace_file_content",
    "apply_patch", "patch", "str_replace", "str_replace_editor",
  ],
  "file read/search": [
    "read", "read_file", "view_file", "view_file_outline", "view_code_item", "read_many_files",
    "ls", "list", "list_dir", "list_directory", "list_files",
    "grep", "grep_search", "search", "search_files", "search_content", "ripgrep", "rg",
    "find", "find_files", "find_by_name", "glob",
  ],
};
const actionCategory = new Map<string, DenialCategory>(
  (Object.entries(actionGroups) as [DenialCategory, readonly string[]][])
    .flatMap(([category, names]) => names.map(name => [name, category])),
);

const pathFields = ["path", "target"] as const;
const reasonFields = ["decision", "reason_code"] as const;
const knownReasons: Record<string, string> = {
  ask: "requires approval",
  requires_approval: "requires approval",
  approval_required: "requires approval",
  user_approval_required: "requires approval",
  interactive_approval_required: "requires approval",
  deny: "denied by policy",
  denied: "denied by policy",
  explicit_deny: "denied by policy",
  policy_deny: "denied by policy",
  policy_denied: "denied by policy",
  denied_by_policy: "denied by policy",
};
const maxScopeProbes = 8;
const maxPathDepth = 12;
const scopeTimeoutMs = 250;
const maxUniqueDescriptors = 12;

function extractTargetField(entry: Record<string, unknown>): { present: boolean; value?: string } {
  let present = false;
  let value: string | undefined;
  for (const field of pathFields) {
    if (!Object.hasOwn(entry, field) || entry[field] === undefined) continue;
    present = true;
    const raw = entry[field];
    if (typeof raw !== "string") return { present: true };
    if (value !== undefined && value !== raw) return { present: true };
    value = raw;
  }
  return { present, value };
}

function extractKnownReason(entry: Record<string, unknown>): string | undefined {
  let matched: string | undefined;
  for (const field of reasonFields) {
    if (!Object.hasOwn(entry, field) || entry[field] === undefined) continue;
    const raw = entry[field];
    if (typeof raw !== "string") return undefined;
    const normalized = raw.trim().toLowerCase();
    if (!Object.hasOwn(knownReasons, normalized)) return undefined;
    const label = knownReasons[normalized];
    if (matched !== undefined && matched !== label) return undefined;
    matched = label;
  }
  return matched;
}

function parseCandidatePath(rawPath: string): { absolute: boolean; parts: string[] } | undefined {
  if (!rawPath || rawPath.length > 4096 || rawPath.trim() !== rawPath) return undefined;
  if (/[\x00-\x1f\x7f]/.test(rawPath) || rawPath.includes("\\")) return undefined;
  if (/^[a-zA-Z][a-zA-Z0-9+.-]*:\/\//.test(rawPath) || /^(?:data|mailto|about|javascript|blob|file):/i.test(rawPath)) return undefined;
  if (/^[A-Za-z]:(?:\/|$)/.test(rawPath) || /^~(?:[^/]*)(?:\/|$)/.test(rawPath)) return undefined;
  if (/[*?]|\[[^\]]*\]|\{[^}]*,[^}]*\}/.test(rawPath)) return undefined;

  const segments = rawPath.split("/");
  if (segments.includes("..")) return undefined;
  return {
    absolute: isAbsolute(rawPath),
    parts: segments.filter(s => s !== "" && s !== "."),
  };
}

export async function denialSummary(actions: unknown[], cwd?: string): Promise<string> {
  const counts = new Map<string, number>();
  const scopeCache = new Map<string, TargetScope>();
  const lstatCache = new Map<string, Stats | null>();
  let fsProbes = 0;
  let realCwd: string | undefined;
  let cwdParts: string[] | undefined;
  let cwdResolved = false;

  let timer: ReturnType<typeof setTimeout> | undefined;
  let timedOut = false;
  let timeoutPromise: Promise<null> | undefined;

  const ensureTimeout = () => {
    if (!timeoutPromise) {
      timeoutPromise = new Promise<null>(resolve => {
        timer = setTimeout(() => {
          timedOut = true;
          resolve(null);
        }, scopeTimeoutMs);
        timer.unref?.();
      });
    }
    return timeoutPromise;
  };

  const withTimeout = <T>(promise: Promise<T>): Promise<T | null> => (
    timedOut ? Promise.resolve(null) : Promise.race([promise.catch(() => null), ensureTimeout()])
  );

  const ensureCwd = async (): Promise<boolean> => {
    if (cwdResolved) return realCwd !== undefined;
    cwdResolved = true;
    if (!cwd) return false;
    const resolved = await withTimeout(realpath(cwd));
    if (typeof resolved !== "string" || !resolved) return false;
    realCwd = resolved;
    cwdParts = resolved.split("/").filter(Boolean);
    return true;
  };

  const probeLstat = async (targetPath: string): Promise<Stats | null> => {
    if (timedOut) return null;
    if (lstatCache.has(targetPath)) return lstatCache.get(targetPath)!;
    const st = await withTimeout(lstat(targetPath));
    lstatCache.set(targetPath, st);
    return st;
  };

  const classifyPathScope = async (rawPath: string): Promise<TargetScope> => {
    const parsed = parseCandidatePath(rawPath);
    if (!parsed) return "target scope unknown";
    if (!(await ensureCwd()) || !realCwd || !cwdParts) return "target scope unknown";

    let relParts: string[];
    if (parsed.absolute) {
      const inCwd = parsed.parts.length >= cwdParts.length &&
        cwdParts.every((seg, idx) => parsed.parts[idx] === seg);
      if (!inCwd) return "outside worktree path";
      relParts = parsed.parts.slice(cwdParts.length);
    } else {
      relParts = parsed.parts;
    }

    if (relParts.length > maxPathDepth || timedOut || fsProbes >= maxScopeProbes) return "target scope unknown";
    fsProbes++;

    if (relParts.length === 0) {
      const st = await probeLstat(realCwd);
      if (!st || st.isSymbolicLink()) return "target scope unknown";
      return st.isFile() ? "existing in-worktree regular file" : "other existing in-worktree path";
    }

    let cur = realCwd;
    for (let i = 0; i < relParts.length; i++) {
      cur = join(cur, relParts[i]);
      const st = await probeLstat(cur);
      if (!st || st.isSymbolicLink()) return "target scope unknown";
      if (i < relParts.length - 1) {
        if (!st.isDirectory()) return "target scope unknown";
      } else {
        return st.isFile() ? "existing in-worktree regular file" : "other existing in-worktree path";
      }
    }
    return "target scope unknown";
  };

  try {
    for (const action of actions) {
      const entry = action && typeof action === "object" && !Array.isArray(action) ? action as Record<string, unknown> : {};
      const rawName = typeof action === "string"
        ? action
        : [entry.action, entry.tool_name, entry.toolName, entry.name, entry.tool].find(v => typeof v === "string");
      const kind = typeof rawName === "string" ? rawName.trim().toLowerCase() : "";
      const category = actionCategory.get(kind) ?? "unrecognized tool";
      const canonical = actionCategory.has(kind) ? kind : "unknown";
      const reason = extractKnownReason(entry);

      const details: string[] = [];
      if (category === "file edit" || category === "file read/search") {
        const target = extractTargetField(entry);
        let scope: TargetScope;
        if (!target.present) {
          scope = "target scope unavailable";
        } else if (target.value === undefined) {
          scope = "target scope unknown";
        } else if (scopeCache.has(target.value)) {
          scope = scopeCache.get(target.value)!;
        } else {
          scope = await classifyPathScope(target.value);
          if (scopeCache.size < 256) scopeCache.set(target.value, scope);
        }
        details.push(scope);
      }
      if (reason) details.push(reason);

      const descriptor = details.length > 0
        ? `${category}: ${canonical} [${details.join(", ")}]`
        : `${category}: ${canonical}`;
      counts.set(descriptor, (counts.get(descriptor) ?? 0) + 1);
    }
  } finally {
    if (timer !== undefined) clearTimeout(timer);
  }

  const parts: string[] = [];
  let shown = 0;
  for (const [descriptor, count] of counts) {
    if (shown >= maxUniqueDescriptors) break;
    parts.push(count > 1 ? `${descriptor} x${count}` : descriptor);
    shown++;
  }
  if (counts.size > maxUniqueDescriptors) parts.push(`+${counts.size - maxUniqueDescriptors} more`);
  return `${actions.length} denied (${parts.join("; ")})`;
}
const defaultModel = "gemini-4-hydrogen-high";
const defaultEffort = "high";

export default function (pi: ExtensionAPI, stream = runAgyStream) {
  let recovery: { key: string; model: string; thinking?: string; excluded: Set<string> } | undefined;
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
      resumeWithFallback: Type.Optional(Type.Boolean({ description: "Team only: after a routing failure and inspection of partial edits, resume with the offered restricted Pi writer." })),
      task: Type.String({ minLength: 1, maxLength: 16000 }),
      cwd: Type.Optional(Type.String({ description: "Absolute linked task worktree root (required in pi-team; omit in plain Pi)" })),
      issue: Type.Optional(Type.String({ pattern: "^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$", description: "Existing Beads issue claimed by the coordinator (pi-team only)" })),
      actor: Type.Optional(Type.String({ pattern: "^[A-Za-z0-9][A-Za-z0-9:._-]{0,159}$", description: "Exact unique Beads claim actor (pi-team only)" })),
    }, { additionalProperties: false }),
    async execute(_id, { task, cwd: worktree, issue, actor, resumeWithFallback }, signal, onUpdate, ctx) {
      const team = pi.getFlag("agy-team") === true;
      let model = team ? defaultModel : pi.getFlag("agy-model");
      let effort = team ? defaultEffort : pi.getFlag("agy-effort");
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
      } else if (resumeWithFallback !== undefined || worktree !== undefined || issue !== undefined || actor !== undefined) {
        throw new Error("Start plain Pi in the desired workspace and omit cwd, issue and actor.");
      }
      const homeFromWorkspace = relative(cwd, await realpath(homedir()));
      if (cwd === "/" || (homeFromWorkspace !== ".." && !homeFromWorkspace.startsWith("../"))) {
        throw new Error("AGY requires a workspace that does not contain your home directory. Start Pi in the project directory.");
      }
      const sandbox = namespaceArgs(cwd, resumeWithFallback ? await realpath(process.env.PI_CODING_AGENT_DIR || join(homedir(), ".pi/agent")) : undefined);
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
      const key = JSON.stringify([cwd, issue, actor]);
      const attempted = new Set<string>();
      if (resumeWithFallback) {
        if (!recovery || recovery.key !== key) throw new Error("No pending writer fallback for this claim and worktree.");
        model = recovery.model;
        if (recovery.thinking) effort = recovery.thinking;
        for (const provider of recovery.excluded) attempted.add(provider);
        attempted.add(model.split("/")[0]);
      }
      const details = { model, effort, cwd };
      const launch = `${resumeWithFallback ? "restricted Pi writer" : "agy"} (${model}, ${effort}) in ${cwd}`;
      onUpdate?.({ content: [{ type: "text", text: `Running ${launch}…` }], details });
      const prompt = [
        "Work only on the assignment below in the current directory. Do not commit, push, deploy, change tracker state, or delegate.",
        "Use native file tools to inspect and edit exact named paths in the current worktree; only search when explicitly scoped in the assignment.",
        "Do not probe outside the worktree or normally protected data; if required context is missing, stop and ask the coordinator. The coordinator handles discovery and checks.",
        "Do not invoke terminal tools. Report files changed and any blockers. Do not include credentials or raw logs.",
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
      let expiry: string | undefined;
      const lease = team ? activityLease({windowMs: timeoutMs, registry: ctx.modelRegistry, label: launch,
        notify: message => warn(ctx, message), expire: reason => { expiry = reason; worker.abort(); },
      }) : undefined;
      const sample = worktreeSampler(pi, cwd, runningSignal, () => lease?.record("fileChanges"));
      let sampling: Promise<void> | undefined;
      const tick = () => sampling ??= sample().catch(() => {}).finally(() => { sampling = undefined; });
      let samplingTimer;
      const writerArgs = resumeWithFallback
        ? [join(homedir(), ".pi/agent/bin/pi.managed"), "--mode", "text", "-p", "--no-approve", "--no-session", "--no-extensions",
          "--no-mcp", "--no-skills", "--tools", "read,grep,find,ls,edit,write", "--model", model, "--thinking", effort, prompt]
        : ["agy", "--model", model, "--effort", effort, "--mode", "accept-edits",
          "--disable-slash-commands", "--output-format", "stream-json", "--print", prompt];
      const result = await (async () => {
        try {
          if (team) {
            await tick();
            samplingTimer = setInterval(tick, heartbeatMs);
            if (resumeWithFallback) warn(ctx, `Resuming with ${launch} after inspection.`);
            recovery = undefined;
          }
          runningSignal.throwIfAborted();
          const args = ["--no-fork", "--nonblock", "--conflict-exit-code", "73", cwd, "bwrap", ...sandbox, ...writerArgs];
          if (resumeWithFallback) return await pi.exec("flock", args, { cwd, signal: runningSignal, maxBuffer: 256 * 1024 });
          return await stream("flock", args, {
            cwd, signal: runningSignal, timeout: team ? undefined : timeoutMs,
            onProgress: onUpdate && ((summary: string) => onUpdate({ content: [{ type: "text", text: `AGY · ${summary}` }], details })),
            record: (kind: string) => lease?.record(kind),
          });
        } finally {
          lease?.dispose();
          clearInterval(samplingTimer);
          clearInterval(timer);
          worker.abort();
          await Promise.all([pending, sampling]);
        }
      })();
      if (leaseFailed) throw new Error(`Beads claim renewal failed for ${issue}; AGY stopped. Inspect the worktree and revalidate ownership before resuming.`);

      if (signal?.aborted) throw new Error("AGY was cancelled; inspect the workspace for partial changes.");
      if (result.truncated) throw new Error("AGY exceeded its output limit; inspect the workspace for partial changes.");
      if (expiry) throw new Error(`Writer timed out (${expiry}); inspect partial changes.`);
      if (result.killed && !("protocolError" in result && result.protocolError)) throw new Error("AGY exceeded its 10-minute timeout; inspect the workspace for partial changes.");
      let report: { status?: unknown; response?: unknown; denied_actions?: unknown; error?: unknown } | null = null;
      if (resumeWithFallback) report = {status: result.code === 0 ? "SUCCESS" : "ERROR", response: result.stdout};
      else try { report = JSON.parse(result.stdout); } catch { /* Empty or non-JSON CLI diagnostic. */ }
      if (Array.isArray(report?.denied_actions) && report.denied_actions.length > 0) {
        throw new Error(
          `AGY non-interactive permission: ${await denialSummary(report.denied_actions, cwd)}. ` +
          "AGY print mode cannot request interactive approval, and the current CLI can omit target scope and denial reason. " +
          "Inspect partial edits and run shell checks in the coordinator; do not guess the underlying rule or infer a filesystem write denial."
        );
      }
      if (result.code === 73 && !result.stdout) throw new Error("The worktree lock is busy or AGY exited before reporting; check for an active writer before retrying.");
      if (team && (result.code !== 0 || (report?.status && report.status !== "SUCCESS"))) {
        const diagnostic = [result.stderr, report?.error && JSON.stringify(report.error),
          !resumeWithFallback && (report ? report.response : result.stdout)].filter(Boolean).join("\n");
        const problem = /bwrap: execvp .*: (?:No such file or directory|Permission denied)/i.test(result.stderr)
          ? "CLI unavailable" : ("diagnosticIssue" in result && result.diagnosticIssue) || routeIssue(diagnostic);
        if (problem) {
          const next = writeAlternate(ctx.modelRegistry, resumeWithFallback ? model : undefined, attempted);
          if (next) recovery = {key, model: next.ref, thinking: next.thinking, excluded: attempted};
          const nextEffort = next ? next.thinking ?? defaultEffort : undefined;
          const message = `${launch}: ${problem}. Inspect partial edits and revalidate the claim. ${next
            ? `Then use resumeWithFallback for ${next.ref} (${nextEffort}); no work has been replayed.` : "No approved fallback remains."}`;
          warn(ctx, message);
          throw new Error(message);
        }
      }
      if (result.code !== 0) throw new Error(`Worker exited with code ${result.code}; inspect the workspace for partial changes.`);
      if ("protocolError" in result && result.protocolError) throw new Error("Invalid AGY event stream; inspect the workspace for partial changes.");
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
