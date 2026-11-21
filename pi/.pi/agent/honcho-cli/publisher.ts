import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { fileURLToPath } from "node:url";

export default function (pi: ExtensionAPI) {
  const grant = process.env.PI_HONCHO_PUBLISH_GRANT;
  if (!grant) return;
  pi.registerMcpServer("honcho_publish", {
    command: "/usr/bin/python3",
    args: [fileURLToPath(new URL("./gateway.py", import.meta.url)), grant],
    exposure: "codemode",
    description: "Publish one verified conclusion to the operator-approved scope; inspect the grant first.",
  });
}
