import type { NextConfig } from "next";

// In cloud mode the browser talks to /api on the same origin (first-party session cookie, no CORS);
// Next forwards it to the pdfctx cloud server.
const backend = process.env.PDFCTX_BACKEND ?? "http://127.0.0.1:8000";

const config: NextConfig = {
  reactStrictMode: true,
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backend}/:path*` }];
  },
};

export default config;
