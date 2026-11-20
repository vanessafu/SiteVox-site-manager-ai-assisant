// HTTPS-Server für die PWA: Mikrofon (MediaRecorder) und Kamera funktionieren auf dem Handy nur über HTTPS.
//   bash ../scripts/make_cert.sh && npm run build && npm run start:https    → https://<IP>:3443
//   npm run dev:https                                                       → Entwicklung mit Hot Reload
// Die Rewrites aus next.config.mjs (/api, /files → FastAPI) gelten auch hier.
import { createServer as createHttps } from "node:https";
import { createServer as createHttp } from "node:http";
import { readFileSync, existsSync } from "node:fs";
import { networkInterfaces } from "node:os";
import next from "next";

const dev = process.argv.includes("--dev");
const port = Number(process.env.HTTPS_PORT || 3443);
const httpPort = Number(process.env.HTTP_REDIRECT_PORT || 0); // optional: http→https-Umleitung
const certDir = new URL("./certs/", import.meta.url);
if (!existsSync(new URL("cert.pem", certDir))) {
  console.error("Kein Zertifikat gefunden. Zuerst: bash scripts/make_cert.sh");
  process.exit(1);
}
const app = next({ dev, hostname: "0.0.0.0", port });
const handle = app.getRequestHandler();
await app.prepare();

createHttps({ key: readFileSync(new URL("key.pem", certDir)), cert: readFileSync(new URL("cert.pem", certDir)) },
  (req, res) => handle(req, res)).listen(port, "0.0.0.0", () => {
  const ips = Object.values(networkInterfaces()).flat().filter((n) => n && n.family === "IPv4" && !n.internal).map((n) => n.address);
  console.log(`SiteVox HTTPS bereit (${dev ? "dev" : "prod"}):`);
  for (const h of ["localhost", ...ips]) console.log(`  https://${h}:${port}/m/BV-RIEM   (Baustelle)   https://${h}:${port}/p/BV-RIEM   (Büro)`);
});
if (httpPort) {
  createHttp((req, res) => {
    const host = (req.headers.host || "localhost").split(":")[0];
    res.writeHead(301, { Location: `https://${host}:${port}${req.url}` }).end();
  }).listen(httpPort, "0.0.0.0");
}
