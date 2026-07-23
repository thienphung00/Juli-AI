import { defineConfig, devices } from "@playwright/test";

const DEMO_PORT = process.env.DEMO_E2E_PORT ?? "3100";
const baseURL = `http://127.0.0.1:${DEMO_PORT}`;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  reporter: process.env.CI ? "github" : "list",
  timeout: 90_000,
  expect: { timeout: 15_000 },
  use: {
    baseURL,
    trace: "on-first-retry",
    locale: "vi-VN",
  },
  webServer: {
    command: `cd ../.. && pnpm build:demo && cd apps/demo && pnpm exec next start -p ${DEMO_PORT}`,
    cwd: ".",
    url: baseURL,
    reuseExistingServer: !process.env.CI,
    timeout: 360_000,
  },
  projects: [
    {
      name: "desktop",
      use: {
        viewport: { width: 960, height: 900 },
      },
    },
    {
      name: "mobile-web",
      use: {
        ...devices["iPhone 13"],
        viewport: { width: 390, height: 844 },
      },
    },
  ],
});
