import { spawn } from "node:child_process";
import { homedir } from "node:os";
import { createInterface } from "node:readline";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

const STATUS = "provider-usage";
const REFRESH_MS = 60_000;
const TIMEOUT_MS = 8_000;

function record(value: unknown): Record<string, unknown> | undefined {
	return value !== null && typeof value === "object" ? value as Record<string, unknown> : undefined;
}

export function formatQuota(value: unknown, clock = (date: Date) => date.toLocaleString()): string | undefined {
	const result = record(value);
	const limits = record(record(result?.rateLimitsByLimitId)?.codex) ?? record(result?.rateLimits);
	const windows: string[] = [];
	for (const [minutes, label] of [[300, "5h"], [10080, "week"]] as const) {
		const window = [record(limits?.primary), record(limits?.secondary)].find(w => w?.windowDurationMins === minutes);
		const used = window?.usedPercent;
		if (typeof used !== "number" || !Number.isFinite(used) || used < 0 || used > 100) continue;
		const resetsAt = window?.resetsAt;
		const reset = typeof resetsAt === "number" && resetsAt > 0 ? new Date(resetsAt * 1000) : undefined;
		const resetText = reset && Number.isFinite(reset.getTime()) ? ` (resets ${clock(reset)})` : "";
		windows.push(`${label} ${Number((100 - used).toFixed(1))}% left${resetText}`);
	}
	return windows.length ? `Codex CLI quota: ${windows.join(" · ")}` : undefined;
}

function readQuota(signal: AbortSignal): Promise<string | undefined> {
	return new Promise(resolve => {
		const child = spawn("codex", ["app-server", "--listen", "stdio://"], {
			cwd: homedir(), stdio: ["pipe", "pipe", "ignore"], signal,
		});
		const lines = createInterface({ input: child.stdout });
		let finished = false;
		const timeout = setTimeout(() => finish(), TIMEOUT_MS);
		function finish(status?: string) {
			if (finished) return;
			finished = true;
			clearTimeout(timeout);
			lines.close();
			child.stdin.destroy();
			if (child.exitCode === null && child.signalCode === null) child.kill("SIGKILL");
			resolve(status);
		}
		function send(message: object) {
			if (!finished) child.stdin.write(`${JSON.stringify(message)}\n`);
		}
		child.on("error", () => finish());
		child.stdin.on("error", () => finish());
		child.stdout.on("error", () => finish());
		child.on("exit", () => finish());
		lines.on("line", line => {
			let message: Record<string, unknown> | undefined;
			try { message = record(JSON.parse(line)); } catch { return; }
			if (message?.id === 1) {
				if (!message.result) return finish();
				send({ method: "initialized" });
				send({ id: 2, method: "account/rateLimits/read" });
			} else if (message?.id === 2) {
				finish(formatQuota(message.result, date => date.toLocaleString(undefined, {
					month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
				})));
			}
		});
		send({ id: 1, method: "initialize", params: { clientInfo: { name: "pi-provider-usage", version: "1.0.0" } } });
	});
}

export default function (pi: ExtensionAPI) {
	let active: ExtensionContext | undefined;
	let lastAttempt = 0;
	let status: string | undefined;
	let pending: Promise<void> | undefined;
	const controller = new AbortController();

	function render() {
		active?.ui.setStatus(STATUS, active.model?.provider === "openai-codex" ? status : undefined);
	}

	function update(ctx: ExtensionContext, force = false) {
		if (ctx.mode !== "tui" || controller.signal.aborted) return;
		active = ctx;
		render();
		if (ctx.model?.provider !== "openai-codex") return;
		if (pending) return pending;
		if (!force && Date.now() - lastAttempt < REFRESH_MS) return;
		lastAttempt = Date.now();
		pending = readQuota(controller.signal).catch(() => undefined).then(value => {
			status = value;
			render();
		}).finally(() => { pending = undefined; });
		return pending;
	}

	pi.on("session_start", (_event, ctx) => { void update(ctx); });
	pi.on("model_select", (_event, ctx) => { void update(ctx); });
	pi.on("agent_end", (_event, ctx) => { void update(ctx); });
	pi.on("session_shutdown", () => { active = undefined; controller.abort(); });
	pi.registerCommand("usage-quota", {
		description: "Refresh the Codex CLI account quota shown in Pi's footer",
		handler: async (_args, ctx) => {
			if (ctx.mode !== "tui") return;
			if (ctx.model?.provider !== "openai-codex") {
				ctx.ui.notify("No account quota adapter for this provider. Session usage is in the footer.", "info");
				return;
			}
			await update(ctx, true);
			if (!status) ctx.ui.notify("Codex CLI quota unavailable. Check the Codex CLI login.", "warning");
		},
	});
}
