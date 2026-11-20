#!/usr/bin/env bash
# Erzeugt ein TLS-Zertifikat für die PWA (Handy-Mikrofon/Kamera brauchen HTTPS = "secure context").
# Enthält localhost + alle LAN-IPs dieses Rechners. Mit mkcert (falls installiert) vertrauenswürdig,
# sonst selbstsigniert (Browser-Warnung einmal bestätigen).
#   bash scripts/make_cert.sh            → frontend/certs/{cert,key}.pem
#   EXTRA_HOSTS="sitevox.local 10.0.0.5" bash scripts/make_cert.sh
set -euo pipefail
OUT="$(cd "$(dirname "$0")/.." && pwd)/frontend/certs"
mkdir -p "$OUT"
IPS=$( (ipconfig getifaddr en0; ipconfig getifaddr en1; hostname -I 2>/dev/null | tr ' ' '\n') 2>/dev/null | grep -E '^[0-9.]+$' | sort -u || true)
HOSTS="localhost 127.0.0.1 $(hostname) $IPS ${EXTRA_HOSTS:-}"
echo "Hosts: $HOSTS"
if command -v mkcert >/dev/null 2>&1; then
  mkcert -cert-file "$OUT/cert.pem" -key-file "$OUT/key.pem" $HOSTS
  echo "mkcert-Zertifikat erstellt. Für das Handy: $(mkcert -CAROOT)/rootCA.pem auf dem Handy installieren & vertrauen."
  exit 0
fi
SAN=""
i=1; j=1
for h in $HOSTS; do
  if [[ $h =~ ^[0-9.]+$ ]]; then SAN="$SAN,IP.$i:$h"; i=$((i+1)); else SAN="$SAN,DNS.$j:$h"; j=$((j+1)); fi
done
SAN="${SAN#,}"
openssl req -x509 -newkey rsa:2048 -nodes -sha256 -days 825 \
  -keyout "$OUT/key.pem" -out "$OUT/cert.pem" \
  -subj "/CN=SiteVox Dev" -addext "subjectAltName=$SAN" \
  -addext "keyUsage=digitalSignature,keyEncipherment" -addext "extendedKeyUsage=serverAuth" 2>/dev/null
echo "Selbstsigniertes Zertifikat erstellt ($SAN)."
echo "Handy: https://<IP>:3443 öffnen und die Zertifikatswarnung einmal bestätigen (oder cert.pem installieren)."
