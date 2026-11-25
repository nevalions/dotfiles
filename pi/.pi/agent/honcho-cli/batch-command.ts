import path from "node:path";
import { fileURLToPath } from "node:url";

interface ExecResult {
  code?: number | null;
  killed?: boolean;
  truncated?: boolean;
  stdout?: string;
  stderr?: string;
}

interface ExecOptions {
  cwd?: string;
  timeout?: number;
  maxBuffer?: number;
}

interface CommandUI {
  notify?: (message: string, level?: "info" | "warning" | "error") => void;
  setStatus?: (key: string, text: string | undefined) => void;
  editor?: (title: string, prefill?: string) => Promise<string | undefined>;
  confirm?: (title: string, message: string) => Promise<boolean>;
}

interface SessionManagerLike {
  getSessionId?: () => string | undefined;
  getCwd?: () => string | undefined;
}

interface CommandContext {
  mode?: string;
  hasUI?: boolean;
  cwd?: string;
  isIdle?: () => boolean;
  ui?: CommandUI;
  sessionManager?: SessionManagerLike;
}

interface SessionStartEvent {
  reason?: string;
}

interface ExtensionAPI {
  on?: (event: string, handler: (event: SessionStartEvent, ctx: CommandContext) => void | Promise<void>) => void;
  registerCommand: (
    name: string,
    options: {
      description: string;
      handler: (args: string, ctx: CommandContext) => Promise<void>;
    },
  ) => void;
  exec: (command: string, args: string[], options?: ExecOptions) => Promise<ExecResult>;
  sendMessage?: (
    message: {
      customType: string;
      content: string;
      display: boolean;
    },
    options?: { triggerTurn?: boolean },
  ) => void | Promise<void>;
}

interface PreviewResponse {
  digest: string;
  preview: string;
}

type BatchStatus = "verified" | "already present" | "blocked";

interface ApplyResultItem {
  repo: string;
  status: BatchStatus;
  reason: string;
}

interface ApplyResponse {
  digest: string;
  results: ApplyResultItem[];
}

const MANIFEST_ENV = "PI_HONCHO_BATCH_MANIFEST";
const PUBLISH_GRANT_ENV = "PI_HONCHO_PUBLISH_GRANT";
const OFFLINE_ENV = "PI_OFFLINE";
const STATUS_KEY = "honcho-batch";
const CUSTOM_MESSAGE_TYPE = "honcho-batch-status";
const PYTHON_BIN = "/usr/bin/python3";
const LAUNCH_PIN_SYMBOL = Symbol.for("pi.honcho.batch.launchPin");

interface LaunchPin {
  manifest: string;
  sessionId: string | null;
  cwd: string | null;
  invalid: boolean;
  inFlight: boolean;
}

const PREVIEW_TIMEOUT_MS = 180_000;
const APPLY_TIMEOUT_MS = 900_000;
const MAX_PREVIEW_JSON_BYTES = 1024 * 1024;
const MAX_PREVIEW_TEXT_CHARS = 512 * 1024;
const MAX_APPLY_JSON_BYTES = 128 * 1024;
const MAX_ITEMS = 32;

const SHA256_RE = /^[0-9a-f]{64}$/;
const REPO_ID_RE = /^[A-Za-z0-9._-]+$/;
const SAFE_REASON_RE = /^[\x20-\x7e]{1,200}$/;
const ALLOWED_STATUSES = new Set<BatchStatus>(["verified", "already present", "blocked"]);

function hasEnv(name: string): boolean {
  return Object.prototype.hasOwnProperty.call(process.env, name) && process.env[name] !== undefined;
}

function getLaunchPin(): LaunchPin | undefined {
  const store = globalThis as Record<symbol, unknown>;
  return store[LAUNCH_PIN_SYMBOL] as LaunchPin | undefined;
}

function setLaunchPin(pin: LaunchPin): void {
  const store = globalThis as Record<symbol, unknown>;
  store[LAUNCH_PIN_SYMBOL] = pin;
}

function resolveBatchHelper(): string | null {
  if (typeof import.meta.url !== "string" || !import.meta.url.startsWith("file://")) {
    return null;
  }
  try {
    const modulePath = fileURLToPath(import.meta.url);
    const helperPath = path.join(path.dirname(modulePath), "batch.py");
    return path.isAbsolute(helperPath) ? helperPath : null;
  } catch {
    return null;
  }
}

function resolveConsistentCwd(ctx: CommandContext | undefined): string | null {
  let procCwd: string;
  try {
    procCwd = process.cwd();
  } catch {
    return null;
  }
  if (!path.isAbsolute(procCwd)) {
    return null;
  }
  if (typeof ctx?.cwd === "string" && ctx.cwd !== procCwd) {
    return null;
  }
  if (typeof ctx?.sessionManager?.getCwd === "function") {
    const smCwd = ctx.sessionManager.getCwd();
    if (typeof smCwd !== "string" || smCwd !== procCwd) {
      return null;
    }
  }
  return procCwd;
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function getValidSessionId(ctx: CommandContext | undefined): string | null {
  const sid = ctx?.sessionManager?.getSessionId?.();
  if (typeof sid !== "string" || sid.length === 0 || sid.length > 256 || /\s/.test(sid)) {
    return null;
  }
  return sid;
}

function parsePreviewOutput(result: ExecResult | null | undefined): PreviewResponse | null {
  if (!result || result.killed || result.truncated || result.code !== 0) {
    return null;
  }
  if (typeof result.stdout !== "string" || Buffer.byteLength(result.stdout, "utf8") > MAX_PREVIEW_JSON_BYTES) {
    return null;
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(result.stdout);
  } catch {
    return null;
  }
  if (!isPlainObject(parsed)) {
    return null;
  }
  const keys = Object.keys(parsed);
  if (keys.length !== 2 || !("digest" in parsed) || !("preview" in parsed)) {
    return null;
  }
  if (typeof parsed.digest !== "string" || !SHA256_RE.test(parsed.digest)) {
    return null;
  }
  if (
    typeof parsed.preview !== "string" ||
    parsed.preview.length === 0 ||
    parsed.preview.length > MAX_PREVIEW_TEXT_CHARS ||
    parsed.preview.includes("\0")
  ) {
    return null;
  }
  return { digest: parsed.digest, preview: parsed.preview };
}

function parseApplyOutput(result: ExecResult | null | undefined, expectedDigest: string): ApplyResponse | null {
  if (!result || result.killed || result.truncated || result.code !== 0) {
    return null;
  }
  if (typeof result.stdout !== "string" || Buffer.byteLength(result.stdout, "utf8") > MAX_APPLY_JSON_BYTES) {
    return null;
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(result.stdout);
  } catch {
    return null;
  }
  if (!isPlainObject(parsed)) {
    return null;
  }
  const keys = Object.keys(parsed);
  if (keys.length !== 2 || !("digest" in parsed) || !("results" in parsed)) {
    return null;
  }
  if (parsed.digest !== expectedDigest) {
    return null;
  }
  if (!Array.isArray(parsed.results) || parsed.results.length < 1 || parsed.results.length > MAX_ITEMS) {
    return null;
  }
  const validated: ApplyResultItem[] = [];
  for (const item of parsed.results) {
    if (!isPlainObject(item)) {
      return null;
    }
    const itemKeys = Object.keys(item);
    if (itemKeys.length !== 3 || !("repo" in item) || !("status" in item) || !("reason" in item)) {
      return null;
    }
    if (typeof item.repo !== "string" || !REPO_ID_RE.test(item.repo)) {
      return null;
    }
    if (typeof item.status !== "string" || !ALLOWED_STATUSES.has(item.status as BatchStatus)) {
      return null;
    }
    if (typeof item.reason !== "string" || !SAFE_REASON_RE.test(item.reason)) {
      return null;
    }
    validated.push({
      repo: item.repo,
      status: item.status as BatchStatus,
      reason: item.reason,
    });
  }
  return { digest: parsed.digest, results: validated };
}

function formatStatusReport(digest: string, results: ApplyResultItem[]): string {
  const counts: Record<BatchStatus, number> = {
    verified: 0,
    "already present": 0,
    blocked: 0,
  };
  for (const item of results) {
    counts[item.status] += 1;
  }
  const lines = [
    `Honcho batch apply report (digest=${digest})`,
    `Summary: ${counts.verified} verified, ${counts["already present"]} already present, ${counts.blocked} blocked`,
  ];
  for (const item of results) {
    lines.push(`- ${item.repo}: ${item.status} (${item.reason})`);
  }
  if (counts.blocked > 0) {
    lines.push(
      "Blocked items were not retried automatically. Never blindly retry; rerun /honcho-batch under a new preview and approval with the same private state directory for safe exact-readback recovery.",
    );
  }
  return lines.join("\n");
}

function formatAbortedReport(digest: string): string {
  return [
    `Honcho batch apply aborted or returned an invalid report (digest=${digest}).`,
    "Some repositories may already have been attempted and may retain local pending markers.",
    "Never blindly retry; rerun /honcho-batch under a new preview and explicit approval with the same private state directory for safe exact-readback recovery.",
  ].join("\n");
}

async function emitReport(pi: ExtensionAPI, content: string): Promise<void> {
  if (typeof pi.sendMessage === "function") {
    await Promise.resolve(
      pi.sendMessage(
        {
          customType: CUSTOM_MESSAGE_TYPE,
          content,
          display: true,
        },
        { triggerTurn: false },
      ),
    );
  }
}

/**
 * Registers the launcher-only /honcho-batch slash command for interactive TUI review and apply.
 */
export default function batchCommandExtension(pi: ExtensionAPI): void {
  const manifest = process.env[MANIFEST_ENV];
  if (typeof manifest !== "string" || !path.isAbsolute(manifest) || hasEnv(PUBLISH_GRANT_ENV)) {
    return;
  }

  const batchHelper = resolveBatchHelper();
  if (batchHelper === null) {
    return;
  }

  if (typeof pi.on === "function") {
    pi.on("session_start", (event, ctx) => {
      if (event?.reason !== "startup") {
        return;
      }
      if (getLaunchPin() !== undefined) {
        return;
      }
      const sid = getValidSessionId(ctx);
      const cwd = resolveConsistentCwd(ctx);
      if (sid === null || cwd === null) {
        setLaunchPin({
          manifest,
          sessionId: null,
          cwd: null,
          invalid: true,
          inFlight: false,
        });
        return;
      }
      setLaunchPin({
        manifest,
        sessionId: sid,
        cwd,
        invalid: false,
        inFlight: false,
      });
    });
  }

  pi.registerCommand("honcho-batch", {
    description: "Preview, confirm, and apply the launch-bound Honcho batch manifest",
    handler: async (args: string, ctx: CommandContext) => {
      if (ctx?.mode !== "tui" || ctx?.hasUI !== true) {
        ctx?.ui?.notify?.("Honcho batch requires an interactive TUI session.", "error");
        return;
      }
      if (typeof ctx.isIdle !== "function" || ctx.isIdle() !== true) {
        ctx.ui?.notify?.("Honcho batch can only run while the session is idle.", "warning");
        return;
      }
      if (hasEnv(OFFLINE_ENV)) {
        ctx.ui?.notify?.("Honcho batch is disabled while PI_OFFLINE is set.", "error");
        return;
      }
      if (args !== undefined && args !== null && String(args).trim() !== "") {
        ctx.ui?.notify?.("Honcho batch does not accept command arguments.", "error");
        return;
      }
      if (process.env[MANIFEST_ENV] !== manifest || hasEnv(PUBLISH_GRANT_ENV)) {
        ctx.ui?.notify?.("Honcho batch launch environment mismatch; aborting.", "error");
        return;
      }

      const pin = getLaunchPin();
      if (!pin || pin.invalid || pin.manifest !== manifest || pin.sessionId === null || pin.cwd === null) {
        ctx.ui?.notify?.("Honcho batch requires an original startup session pin; aborting.", "error");
        return;
      }
      if (pin.inFlight) {
        ctx.ui?.notify?.("Honcho batch is already in progress.", "warning");
        return;
      }

      const currentCwd = resolveConsistentCwd(ctx);
      if (currentCwd === null || currentCwd !== pin.cwd) {
        ctx.ui?.notify?.("Honcho batch working directory changed since launch; aborting.", "error");
        return;
      }

      const sessionId = getValidSessionId(ctx);
      if (sessionId === null) {
        ctx.ui?.notify?.("Honcho batch could not verify the active Pi session id.", "error");
        return;
      }
      if (sessionId !== pin.sessionId) {
        ctx.ui?.notify?.("Honcho batch requires the original launch session; aborting.", "error");
        return;
      }
      if (typeof ctx.ui?.editor !== "function" || typeof ctx.ui?.confirm !== "function") {
        ctx.ui?.notify?.("Honcho batch requires editor and confirmation UI support.", "error");
        return;
      }

      const pinnedSessionId = pin.sessionId;
      const execCwd = pin.cwd;

      const bindingStillValid = (): boolean => {
        const currentPin = getLaunchPin();
        if (!currentPin || currentPin.invalid) {
          return false;
        }
        if (currentPin.manifest !== manifest || process.env[MANIFEST_ENV] !== manifest) {
          return false;
        }
        if (hasEnv(PUBLISH_GRANT_ENV) || hasEnv(OFFLINE_ENV)) {
          return false;
        }
        if (currentPin.sessionId !== pinnedSessionId || currentPin.cwd !== execCwd) {
          return false;
        }
        const currentSid = getValidSessionId(ctx);
        const activeCwd = resolveConsistentCwd(ctx);
        return currentSid !== null && currentSid === pinnedSessionId && activeCwd === execCwd;
      };

      pin.inFlight = true;
      try {
        ctx.ui.setStatus?.(STATUS_KEY, "Honcho batch: generating offline preview...");
        let previewExec: ExecResult;
        try {
          previewExec = await pi.exec(
            PYTHON_BIN,
            ["-I", "-B", batchHelper, "preview", manifest, pinnedSessionId],
            { cwd: execCwd, timeout: PREVIEW_TIMEOUT_MS, maxBuffer: MAX_PREVIEW_JSON_BYTES },
          );
        } catch {
          ctx.ui.notify?.("Honcho batch preview failed; nothing applied.", "error");
          return;
        }

        if (!bindingStillValid()) {
          ctx.ui.notify?.("Honcho batch aborted: session, environment, or working directory changed during preview.", "error");
          return;
        }

        const previewData = parsePreviewOutput(previewExec);
        if (!previewData) {
          ctx.ui.notify?.("Honcho batch preview failed validation; nothing applied.", "error");
          return;
        }

        ctx.ui.setStatus?.(STATUS_KEY, "Honcho batch: awaiting preview review...");
        let editedText: string | undefined;
        try {
          editedText = await ctx.ui.editor(
            `Honcho batch preview (${previewData.digest.slice(0, 12)})`,
            previewData.preview,
          );
        } catch {
          ctx.ui.notify?.("Honcho batch review UI aborted; nothing applied.", "error");
          return;
        }

        if (!bindingStillValid()) {
          ctx.ui.notify?.("Honcho batch aborted: session, environment, or working directory changed during review.", "error");
          return;
        }
        if (editedText === undefined) {
          ctx.ui.notify?.("Honcho batch cancelled; nothing applied.", "info");
          return;
        }
        if (editedText !== previewData.preview) {
          ctx.ui.notify?.("Honcho batch aborted: preview text was modified; nothing applied.", "warning");
          return;
        }

        let confirmed: boolean;
        try {
          confirmed = await ctx.ui.confirm(
            `Confirm Honcho batch (${previewData.digest.slice(0, 12)})`,
            `Apply approved Honcho batch with digest ${previewData.digest}?\n\nConfirm only if you reviewed the unchanged preview above. Never blindly retry if interrupted.`,
          );
        } catch {
          ctx.ui.notify?.("Honcho batch confirmation failed; nothing applied.", "error");
          return;
        }

        if (!bindingStillValid()) {
          ctx.ui.notify?.("Honcho batch aborted: session, environment, or working directory changed before apply.", "error");
          return;
        }
        if (confirmed !== true) {
          ctx.ui.notify?.("Honcho batch declined; nothing applied.", "info");
          return;
        }

        ctx.ui.setStatus?.(STATUS_KEY, "Honcho batch: applying approved conclusions...");
        ctx.ui.notify?.(`Honcho batch: applying digest ${previewData.digest.slice(0, 12)}...`, "info");

        let applyExec: ExecResult | null = null;
        try {
          applyExec = await pi.exec(
            PYTHON_BIN,
            ["-I", "-B", batchHelper, "apply", manifest, pinnedSessionId, previewData.digest],
            { cwd: execCwd, timeout: APPLY_TIMEOUT_MS, maxBuffer: MAX_APPLY_JSON_BYTES },
          );
        } catch {
          applyExec = null;
        }

        if (!bindingStillValid()) {
          ctx.ui.notify?.(
            "Honcho batch aborted: session, environment, or working directory changed during apply; status report suppressed.",
            "error",
          );
          return;
        }

        const applyData = parseApplyOutput(applyExec, previewData.digest);
        if (!applyData) {
          const abortedReport = formatAbortedReport(previewData.digest);
          await emitReport(pi, abortedReport);
          ctx.ui.notify?.("Honcho batch apply aborted or returned an invalid response; see chat report.", "error");
          return;
        }

        const report = formatStatusReport(applyData.digest, applyData.results);
        await emitReport(pi, report);
        ctx.ui.notify?.("Honcho batch complete; see chat report for per-repo status.", "info");
      } finally {
        pin.inFlight = false;
        ctx.ui?.setStatus?.(STATUS_KEY, undefined);
      }
    },
  });
}
