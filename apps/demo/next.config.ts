import type { NextConfig } from "next";

// Standard next build + next start from apps/demo (matches juli-web / App Review).
// Do not use output: "standalone" — systemd runs `pnpm run start` in this directory.
const nextConfig: NextConfig = {
  transpilePackages: ["@juli/ui", "@juli/utils"],
};

export default nextConfig;
