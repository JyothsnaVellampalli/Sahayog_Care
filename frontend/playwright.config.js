import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: './tests', timeout: 30000, fullyParallel: false,
  use: { baseURL: 'http://127.0.0.1:5174', browserName: 'chromium', channel: 'msedge', headless: true },
  webServer: { command: 'npm run dev -- --host 127.0.0.1 --port 5174 --strictPort', url: 'http://127.0.0.1:5174', reuseExistingServer: !process.env.CI },
});
