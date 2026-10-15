import { defineConfig } from "vitest/config";

/**
 * `pnpm check:seo` — checks the BUILT site, so run `pnpm build` first (or point
 * SEO_BASE_URL at a running `next start` / the live site). Not part of
 * `pnpm test`, which must not depend on a build.
 */
export default defineConfig({
  test: {
    environment: "jsdom",
    include: ["src/seo-check/**/*.check.ts"],
    testTimeout: 30_000,
  },
});
