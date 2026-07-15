import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  transpilePackages: ["@juli/ui", "@juli/utils"],
};

export default nextConfig;
