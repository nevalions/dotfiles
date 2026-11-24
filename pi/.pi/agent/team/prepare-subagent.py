import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile


def prepare(source, cache):
    text = source.read_text(encoding="utf-8")
    watchdog = Path(__file__).resolve().with_name("subagent-watchdog.mjs")
    blockers = watchdog.with_name("subagent-blockers.mjs")

    def replace(old, new):
        nonlocal text
        if text.count(old) != 1:
            raise ValueError(f"unsupported bundled subagent layout (anchor: {old.splitlines()[0].strip()})")
        text = text.replace(old, new)

    replace('from "./agents.ts";', f"from {json.dumps(str(source.with_name('agents.ts')))};")
    replace('import { spawn } from "node:child_process";',
            'import { spawn } from "node:child_process";\n'
            f'import {{ subagentTimeout, watchSubagent }} from {json.dumps(str(watchdog))};\n'
            f'import {{ childBlocker, cwdBlocker, installBlockerGuard }} from {json.dumps(str(blockers))};')
    replace('\terrorMessage?: string;\n\tterminationSignal?', '\terrorMessage?: string;\n\tblocker?: string;\n\tterminationSignal?')
    replace('\tcwd: string;\n}\n\nfunction resolveAgent', '\tcwd: string;\n\tblocker?: string;\n}\n\nfunction resolveAgent')
    replace('\tconst discovery = discoverAgents(effectiveCwd, scope);',
            '\tconst blocker = cwdBlocker(cwd, effectiveCwd);\n'
            '\tif (blocker) return { cwd: effectiveCwd, available: [], blocker };\n'
            '\tconst discovery = discoverAgents(effectiveCwd, scope);')
    replace('\tconst effectiveCwd = resolvedAgent.cwd;',
            '\tif (resolvedAgent.blocker) {\n'
            '\t\treturn { ...createUnstartedResult(agentName, task, step, "failed", resolvedAgent.blocker), blocker: resolvedAgent.blocker };\n'
            '\t}\n\tconst effectiveCwd = resolvedAgent.cwd;')
    replace('export default function (pi: ExtensionAPI) {',
            'export default function (pi: ExtensionAPI) {\n\tinstallBlockerGuard(pi);')
    replace('["--mode", "json", "-p", "--no-session"]',
            '["--mode", "json", "-p", "--no-session", "--no-extensions", "--no-mcp"]')
    replace('\tspawnError?: Error;', '\tspawnError?: Error;\n\ttimeoutError?: string;')
    replace('\t\t\tlet exited = false;\n\t\t\tlet closed = false;\n\t\t\tlet killTimer: ReturnType<typeof setTimeout> | undefined;',
            '\t\t\tconst hardMs = subagentTimeout();\n\t\t\tlet watchdog: ReturnType<typeof watchSubagent> | undefined;')
    replace('\t\t\t\tif (event.type !== "message_end") return;',
            '\t\t\t\tif (event.type === "agent_end") watchdog?.endTurn();\n'
            '\t\t\t\tif (event.type !== "message_end") return;')
    replace('\t\t\t\tclosed = true;\n\t\t\t\tif (killTimer) clearTimeout(killTimer);',
            '\t\t\t\twatchdog?.dispose();')
    replace('\t\t\t\tresolve(result);', '\t\t\t\tresolve({ ...result, timeoutError: watchdog?.error });')
    replace('''\t\t\t\tif (closed || exited || proc.exitCode !== null || proc.signalCode !== null) return;
\t\t\t\tif (!proc.kill("SIGTERM")) return;
\t\t\t\twasAborted = true;
\t\t\t\tkillTimer = setTimeout(() => {
\t\t\t\t\tif (!closed && !exited) proc.kill("SIGKILL");
\t\t\t\t}, 5000);''', '''\t\t\t\tif (settled || watchdog?.error) return;
\t\t\t\twasAborted = true;
\t\t\t\twatchdog?.cancel();''')
    replace('\t\t\tproc.stdout?.on("data", (data) => {',
            '\t\t\twatchdog = watchSubagent(proc, () => finish({ code: proc.exitCode, signal: proc.signalCode }), { hardMs });\n'
            '\t\t\tproc.stdout?.on("data", (data) => {')
    replace('\t\t\tproc.on("exit", () => {\n\t\t\t\texited = true;\n\t\t\t});\n', '')
    replace('\t\tif (wasAborted) {',
            '\t\tif (outcome.timeoutError) {\n\t\t\tcurrentResult.status = "failed";\n'
            '\t\t\tcurrentResult.errorMessage = currentResult.blocker = outcome.timeoutError;\n\t\t} else if (wasAborted) {')
    replace('\t\treturn currentResult;\n\t} finally {',
            '\t\tconst blocker = childBlocker(currentResult, outcome);\n'
            '\t\tif (blocker) {\n'
            '\t\t\tcurrentResult.status = "failed";\n'
            '\t\t\tcurrentResult.errorMessage = currentResult.blocker = blocker;\n'
            '\t\t}\n\t\treturn currentResult;\n\t} finally {')

    data = text.encode("utf-8")
    cache.mkdir(mode=0o700, parents=True, exist_ok=True)
    dest = cache / f"subagent-{hashlib.sha256(data).hexdigest()}.ts"
    if not dest.is_file() or dest.read_bytes() != data:
        with tempfile.NamedTemporaryFile(dir=cache, delete=False) as temp:
            try:
                temp.write(data)
                temp.close()
                os.replace(temp.name, dest)
            finally:
                Path(temp.name).unlink(missing_ok=True)
    return dest


if __name__ == "__main__":
    try:
        print(prepare(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()))
    except (OSError, ValueError) as exc:
        sys.exit(f"pi-team: could not prepare the bounded subagent extension: {exc}")
