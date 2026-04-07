import path from "node:path";
import { fileURLToPath } from "node:url";

import type { NextConfig } from "next";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const allowedDevOrigins = (process.env.ALLOWED_DEV_ORIGINS ||
  "localhost,127.0.0.1,192.168.15.49")
  .split(",")
  .map((value) => value.trim())
  .filter(Boolean);

const nextConfig: NextConfig = {
  outputFileTracingRoot: path.join(__dirname, ".."),
  allowedDevOrigins,
  reactStrictMode: true,
};

export default nextConfig;
