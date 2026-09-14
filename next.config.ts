import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Public, build-time constants (never secrets). Defaulting them here means
  // they are always inlined as literals, so an api-mode build drops the
  // fixture server entirely instead of carrying it as an unused chunk.
  env: {
    NEXT_PUBLIC_API_MODE: process.env.NEXT_PUBLIC_API_MODE ?? "api",
    NEXT_PUBLIC_API_BASE: process.env.NEXT_PUBLIC_API_BASE ?? "",
  },
  // Same-origin proxy: the browser only ever talks to this app. Port 3000 is taken by
  // another project on this machine, and the engine's CORS allows a single origin —
  // proxying makes both irrelevant. LGE_API_ORIGIN is server-side only.
  async rewrites() {
    const engine = process.env.LGE_API_ORIGIN ?? "http://127.0.0.1:8000";
    return [{ source: "/api/:path*", destination: `${engine}/api/:path*` }];
  },
  // A stray package-lock.json in the user profile made Turbopack infer
  // C:\Users\ACER as the workspace root. Pin it to this project.
  turbopack: {
    root: path.resolve(__dirname),
  },
  // The dev badge sat on the rail's engine status and the case file's
  // outcome bar. Build and runtime errors still open the dev overlay.
  devIndicators: false,
};

export default nextConfig;
