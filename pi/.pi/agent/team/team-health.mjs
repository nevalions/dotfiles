const routes = ["openai-codex/gpt-6.1-sol", "opencode-go/deepseek-v4.1-flash"];

export function alternate(registry, primary, excluded = new Set()) {
  const available = registry?.getAvailable() ?? [];
  for (const ref of routes) {
    const [provider, id] = ref.split("/");
    if (provider !== primary?.split("/")[0] && !excluded.has(provider) &&
        available.some(m => m.provider === provider && m.id === id)) return ref;
  }
}

export function warn(ctx, message) {
  if (ctx.hasUI) ctx.ui.notify(message, "warning");
  else console.error(message);
}

export function routeIssue(diagnostic = "") {
  if (/\b(?:429|RESOURCE_EXHAUSTED|insufficient_quota|rate.limit.exceeded)\b|\b(?:rate|usage|capacity) limit\b|\bquota (?:reached|exceeded|exhausted|will reset)\b|\b(?:exhausted|exceeded) (?:your |the )?(?:quota|capacity)\b|\btoo many requests\b/i.test(diagnostic)) return "provider rate or quota limit";
  if (/unsupported_country|(?:unsupported|blocked) (?:region|country)|(?:country|region|location).{0,50}(?:blocked|unsupported|not supported|restricted)|not available in your (?:country|region)/i.test(diagnostic)) return "provider location restriction";
  if (/\b(?:401|invalid_api_key|authentication_error)\b|no api key|not authenticated|login required|failed to authenticate|invalid api key/i.test(diagnostic)) return "provider authentication unavailable";
  if (/model_not_found|\b(?:unknown|unavailable) model\b|model .{0,60}(?:not found|not available)|no models? found/i.test(diagnostic)) return "model unavailable";
  if (/\b(?:502 bad gateway|503 service unavailable|504 gateway timeout|overloaded_error|ECONNREFUSED|ETIMEDOUT)\b/i.test(diagnostic)) return "provider unavailable";
}

export function installCoordinatorRecovery(pi) {
  const failed = new Set();
  let last;
  pi.on("before_agent_start", () => { failed.clear(); last = undefined; });
  pi.on("message_end", event => { if (event.message.role === "assistant") last = event.message; });
  pi.on("agent_before_settle", async (event, ctx) => {
    if (event.outcome !== "error" || ctx.signal?.aborted) return;
    if (last?.stopReason !== "error") return;
    const issue = routeIssue(last.errorMessage);
    if (!issue || !ctx.model) return;
    const {provider, id} = ctx.model;
    failed.add(provider);
    const next = alternate(ctx.modelRegistry, provider, failed);
    const model = next && ctx.modelRegistry.find(...next.split("/"));
    if (model && await pi.setModel(model).catch(() => false)) {
      warn(ctx, `Coordinator ${provider}/${id}: ${issue}; continuing with ${next}.`);
      return {continue: true, entries: [...event.entries, {type: "custom_message", customType: "team-provider-fallback",
        content: "Continue the interrupted assignment from verified state. Do not repeat completed tool actions.", display: false}]};
    }
    warn(ctx, `Coordinator ${provider}/${id}: ${issue}; no approved fallback remains.`);
  });
}

export async function readOnlyAttempt(ctx, resolved, signal, attempt) {
  const result = await attempt(resolved);
  if (!result.routeIssue || signal?.aborted) return result;
  const role = resolved.agent;
  if (role?.source !== "user" || !["scout", "planner", "planner-quick", "reviewer", "reviewer-quick"].includes(role.name) ||
      !role.tools?.length || !role.tools.every(t => ["read", "grep", "find", "ls"].includes(t))) return result;
  const next = alternate(ctx.modelRegistry, result.model);
  if (!next) return result;
  const effort = role.model?.match(/:(low|medium|high|xhigh|max)$/)?.[0] ?? "";
  warn(ctx, `${role.name}: ${result.model}: ${result.routeIssue}; retrying once with ${next}${effort}.`);
  return attempt({...resolved, agent: {...role, model: next + effort}});
}

const progress = {
  type: "bool",
  instructions: "Does recent worker activity show the assignment is still progressing?",
  criteria: {
    true: "The worker recently produced model output, completed tools or changed worktree files.",
    false: "The worker is silent or its only evidence of activity is stale.",
  },
};

export function activityLease({windowMs, registry, notify, expire, label, decisionMs = 4000}) {
  let timer, judgement, stopped = false, extensions = 0;
  let counters, last;
  const reset = () => {
    counters = {outputEvents: 0, toolEvents: 0, fileChanges: 0};
    last = undefined;
    timer = setTimeout(check, windowMs);
  };
  const dispose = () => {
    stopped = true;
    clearTimeout(timer);
    judgement?.abort();
  };
  async function check() {
    if (stopped) return;
    if (extensions >= 2) { expire("extension limit reached"); return; }
    const state = {windowMs, ...counters, lastProgressMsAgo: last === undefined ? null : Date.now() - last};
    let probability;
    judgement = new AbortController();
    const request = judgement;
    const timeout = setTimeout(() => request.abort(), decisionMs);
    try {
      const model = registry?.getModelOfType("classifier", "typesafe", "jev-latest");
      if (model) {
        const result = await Promise.race([
          registry.classify(model, {state, questions: {progress}}, {signal: request.signal}),
          new Promise(resolve => request.signal.addEventListener("abort", () => resolve(null), {once: true})),
        ]);
        const answer = result?.answers?.progress;
        if (result?.stopReason === "stop" && answer?.type === "bool" &&
            Number.isFinite(answer.probability) && answer.probability >= 0 && answer.probability <= 1) probability = answer.probability;
      }
    } catch { /* Unavailable is not a negative judgement. */ }
    finally { clearTimeout(timeout); }
    if (stopped) return;
    const recent = last !== undefined && Date.now() - last <= Math.min(windowMs, 90_000);
    const reason = probability === undefined ? "Jev unavailable" : `Jev progress ${probability.toFixed(2)}`;
    if (recent && (probability >= 0.7 || ((probability === undefined || probability > 0.3) && extensions === 0))) {
      extensions++;
      notify(`${label}: ${reason}; granting another ${windowMs} ms (${extensions}/2).`);
      reset();
    } else expire(reason);
  }
  reset();
  return {dispose, record(kind) {
    if (!stopped && Object.hasOwn(counters, kind)) { counters[kind]++; last = Date.now(); }
  }};
}
