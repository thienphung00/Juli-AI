import type { NextConfig } from "next";

// Standard next build + next start from apps/landing (mirrors apps/demo).
// Do not use output: "standalone" — deployment runs `pnpm run start` in this directory.
const nextConfig: NextConfig = {
  transpilePackages: ["@juli/ui", "@juli/brand"],
};

export default nextConfig;
