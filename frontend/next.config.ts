import type { NextConfig } from "next";

const API_ORIGIN = process.env.BACKEND_ORIGIN || "http://localhost:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  // Proxy /api/* to the FastAPI backend so the browser only ever talks to the
  // frontend origin. This keeps a single public URL (one tunnel), avoids CORS,
  // and sidesteps the /audit + /onboarding path collisions between frontend
  // pages and backend endpoints.
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_ORIGIN}/:path*` }];
  },
};

export default nextConfig;
