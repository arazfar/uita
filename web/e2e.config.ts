import type { E2EConfig } from 'e2e'
import { web } from '@e2e-dev/web'

export default {
  targets: [{
    name: 'chromium',
    engine: web({ viewport: { width: 1440, height: 960 } }),
    app: {
      url: 'http://127.0.0.1:0',
      command: {
        executable: 'bun',
        args: ['run', 'dev', '--host', '127.0.0.1', '--port', '{port}'],
        log: '.e2e/logs/app.log',
      },
    },
  }],
  workers: 1,
  retries: 0,
  timeout: 120000,
  // WebGL map startup can delay the first layout read in headless Chromium.
  assertionTimeout: 30000,
  trace: 'retain-on-failure',
  cache: 'off',
} satisfies E2EConfig
