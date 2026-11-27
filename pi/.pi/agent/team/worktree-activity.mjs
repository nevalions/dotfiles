import { lstat } from "node:fs/promises";
import { join } from "node:path";

export function worktreeSampler(pi, cwd, signal, record, gitBinary = "git") {
  let previous;
  return async () => {
    const listing = await pi.exec(gitBinary, ["--no-optional-locks", "-c", "core.fsmonitor=false", "ls-files", "-m", "-o", "--exclude-standard", "-z"], {
      cwd, signal, timeout: 3000, maxBuffer: 128 * 1024,
    });
    if (listing.code !== 0 || listing.truncated || signal.aborted) return;
    const files = listing.stdout.split("\0").filter(Boolean).slice(0, 128);
    const current = new Map(await Promise.all(files.map(async file => {
      const info = await lstat(join(cwd, file), {bigint: true}).catch(() => undefined);
      return [file, info ? `${info.mtimeNs}:${info.size}` : "missing"];
    })));
    if (previous && (current.size !== previous.size || [...current].some(([file, stamp]) => previous.get(file) !== stamp))) record();
    previous = current;
  };
}
