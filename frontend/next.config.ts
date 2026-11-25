import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Emits .next/standalone: a minimal server.js plus only the node_modules
  // files it actually imports. The production Docker image (frontend/
  // Dockerfile) copies just that, instead of the full dependency tree.
  output: "standalone",
};

export default nextConfig;
