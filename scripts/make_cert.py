#!/usr/bin/env python3
"""Plattformunabhängiges Gegenstück zu scripts/make_cert.sh (z. B. für Windows ohne bash/openssl/mkcert).

Erzeugt ein selbstsigniertes TLS-Zertifikat für die PWA (Handy-Mikrofon/Kamera brauchen HTTPS) mit
localhost, Rechnername und allen LAN-IPv4-Adressen dieses Rechners → frontend/certs/{cert,key}.pem.

  pip install cryptography
  python scripts/make_cert.py                    # LAN-IPs automatisch
  python scripts/make_cert.py 192.168.0.12       # zusätzliche IPs/Hosts
"""
from __future__ import annotations

import datetime
import ipaddress
import socket
import sys
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

OUT = Path(__file__).resolve().parents[1] / "frontend" / "certs"


def lan_ips() -> list[str]:
    ips: set[str] = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    try:  # Adresse der Standardroute (kein Paket wird gesendet)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            ips.add(s.getsockname()[0])
    except OSError:
        pass
    return sorted(i for i in ips if not i.startswith(("127.", "169.254.")))


def main() -> None:
    extra = sys.argv[1:]
    names: list[x509.GeneralName] = [x509.DNSName("localhost"), x509.DNSName(socket.gethostname())]
    hosts = ["127.0.0.1", *lan_ips(), *extra]
    for h in dict.fromkeys(hosts):
        try:
            names.append(x509.IPAddress(ipaddress.ip_address(h)))
        except ValueError:
            names.append(x509.DNSName(h))
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.datetime.now(datetime.timezone.utc)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "SiteVox Dev")])
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1)).not_valid_after(now + datetime.timedelta(days=825))
            .add_extension(x509.SubjectAlternativeName(names), critical=False)
            .add_extension(x509.KeyUsage(digital_signature=True, key_encipherment=True, content_commitment=False,
                                         data_encipherment=False, key_agreement=False, key_cert_sign=False,
                                         crl_sign=False, encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .sign(key, hashes.SHA256()))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "key.pem").write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                                    serialization.PrivateFormat.TraditionalOpenSSL,
                                                    serialization.NoEncryption()))
    (OUT / "cert.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    print("Selbstsigniertes Zertifikat:", ", ".join(str(n.value) for n in names))
    print("Handy: https://<IP>:3443 öffnen und die Zertifikatswarnung einmal bestätigen.")


if __name__ == "__main__":
    main()
