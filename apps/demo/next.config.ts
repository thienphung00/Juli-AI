import type { NextConfig } from "next";

// Standard next build + next start from apps/demo (matches juli-web / App Review).
// Do not use output: "standalone" — see ADR-058 (docs/adr/058-release-packaging-shape.md)
// for the measured reasoning. In short: the #835 spike proved the pnpm symlink tree
// resolves through a release-slot indirection, so the risk that would have forced
// self-contained output did not materialise, and standalone's entrypoint path is derived
// from the inferred workspace root rather than fixed.
// juli-demo.service starts node_modules/.bin/next directly from this directory.
const nextConfig: NextConfig = {
  transpilePackages: ["@juli/ui", "@juli/utils"],
};

export default nextConfig;
