import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: [
      // Brand raster assets are binary; tests consume a StaticImageData stub.
      // Anchored to the full specifier: `@juli/brand/assets/*` and the
      // package's internal relative imports (`../assets/*`).
      {
        find: /^@juli\/brand\/assets\/[\w-]+\.(png|webp)$/,
        replacement: fileURLToPath(
          new URL("./src/__tests__/helpers/static-image-stub.ts", import.meta.url),
        ),
      },
      {
        find: /^(?:\.\.?[\\/])+assets[\\/][\w-]+\.(png|webp)$/,
        replacement: fileURLToPath(
          new URL("./src/__tests__/helpers/static-image-stub.ts", import.meta.url),
        ),
      },
    ],
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    exclude: ["**/node_modules/**"],
  },
});
