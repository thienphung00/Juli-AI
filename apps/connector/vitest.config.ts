import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "node",
    include: ["test/**/*.test.ts"],
    // 0.3.24: a fill job waits for the form, re-reads and watches every field (fake clock, but
    // jsdom's style reads are slow): the first, cold fill test of a file can pass 5 s under load.
    testTimeout: 20_000,
  },
});
