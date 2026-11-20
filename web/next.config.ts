import type { NextConfig } from "next";

const config: NextConfig = {
  agentRules: false,
  compress: false,
  async rewrites() {
    const origin = process.env.BEAUTYADS_API_ORIGIN ?? "http://127.0.0.1:8000";
    return [{ source: "/api/:path*", destination: `${origin}/:path*` }];
  },
};

export default config;
