/** API und Dateien werden an FastAPI weitergereicht → gleiche Origin für Handy im WLAN, kein CORS. */
const BACKEND = process.env.BACKEND_URL || "http://localhost:8000";

/** @type {import('next').NextConfig} */
const nextConfig = {
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${BACKEND}/api/:path*` },
      { source: "/files/:path*", destination: `${BACKEND}/files/:path*` },
    ];
  },
};
export default nextConfig;
