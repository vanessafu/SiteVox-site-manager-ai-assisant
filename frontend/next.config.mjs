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
  webpack(config, { dev, isServer }) {
    // Workaround für einen Next.js-Bug (15.5, flight-manifest-plugin: `if (concatenatedModId)`):
    // Bekommt ein zusammengefasstes Client-Seitenmodul zufällig die deterministische ID 0, fehlt es im
    // React Client Manifest → "Could not find the module … in the React Client Manifest" (HTTP 500).
    // Benannte IDs (wie im Dev-Modus) sind nie 0.
    if (!dev && !isServer) config.optimization.moduleIds = "named";
    return config;
  },
};
export default nextConfig;
