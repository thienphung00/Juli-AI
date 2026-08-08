import { defineConfig, devices } from "@playwright/test";

const DEMO_PORT = process.env.DEMO_E2E_PORT ?? "3100";
const baseURL = `http://127.0.0.1:${DEMO_PORT}`;

// Issue #837 (PRD #820): CI builds the release artifact once, then runs this
// exit-gate suite against a server started *from that artifact* — the artifact's
// own .next and its own production dependency tree. Point DEMO_E2E_ARTIFACT_DIR
// at the staged artifact and the suite starts it instead of rebuilding, so what
// the browser checks is what ships rather than a second, differently-built copy.
// Unset (local runs, the demo-e2e job), the rebuild-then-start path is unchanged.
const artifactDir = process.env.DEMO_E2E_ARTIFACT_DIR;

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
    command: artifactDir
      ? `node_modules/.bin/next start -p ${DEMO_PORT}`
      : `cd ../.. && pnpm build:demo && cd apps/demo && pnpm exec next start -p ${DEMO_PORT}`,
    cwd: artifactDir ?? ".",
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
        ...devices["Pixel 5"],
        viewport: { width: 390, height: 844 },
      },
    },
  ],
});
