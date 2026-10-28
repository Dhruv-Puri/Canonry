import type { NextConfig } from "next";

const ENGINE = process.env.CANONRY_ENGINE_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  experimental: {
    // The whole app renders behind <IdentityGate> (welcome screen until someone
    // identifies themselves), so no route can promise an instantly rendered
    // shell. Validate instant navigation only where a page opts in with
    // `export const instant` instead of reporting every gated segment.
    instantInsights: { validationLevel: "manual-warning" },
  },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  async rewrites() {
    // Same-origin proxy: the browser talks to /engine/*, Next forwards to the
    // FastAPI engine. Session cookies pass through transparently.
    return [
      { source: "/engine/:path*", destination: `${ENGINE}/:path*` },
      { source: "/engine", destination: `${ENGINE}/` },
    ];
  },
};

export default nextConfig;
