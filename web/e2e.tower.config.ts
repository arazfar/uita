import type { E2EConfig } from "e2e";
import { web } from "@e2e-dev/web";
export default {
  targets: [
    {
      name: "chromium",
      engine: web({ viewport: { width: 1440, height: 900 } }),
      app: { url: "http://127.0.0.1:5188" },
    },
  ],
  workers: 1,
  retries: 0,
  timeout: 120000,
  assertionTimeout: 30000,
  trace: "retain-on-failure",
  cache: "off",
} satisfies E2EConfig;
