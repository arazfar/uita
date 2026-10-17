import type { E2EConfig } from "e2e";
import { web } from "@e2e-dev/web";
export default {
  targets: [
    {
      name: "chromium",
      engine: web({ viewport: { width: 1440, height: 1000 } }),
      app: { url: "http://127.0.0.1:5190" },
    },
  ],
  workers: 1,
  retries: 0,
  timeout: 600000,
  assertionTimeout: 120000,
  trace: "retain-on-failure",
  cache: "off",
} satisfies E2EConfig;
