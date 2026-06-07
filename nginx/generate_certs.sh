#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# CodEdu — Generate Self-Signed TLS Certificates (Development)
# ═══════════════════════════════════════════════════════════════
# For production: replace with Let's Encrypt / ACME certificates
# Usage: ./generate_certs.sh

set -euo pipefail

CERT_DIR="$(dirname "$0")/ssl"
mkdir -p "$CERT_DIR"

echo "[CodEdu] Generating self-signed TLS certificate for development..."

openssl req -x509 -nodes \
    -days 365 \
    -newkey rsa:2048 \
    -keyout "$CERT_DIR/server.key" \
    -out "$CERT_DIR/server.crt" \
    -subj "/C=ID/ST=JawaTimur/L=Surabaya/O=CodEdu/OU=Engineering/CN=localhost" \
    -addext "subjectAltName=DNS:localhost,DNS:*.localhost,IP:127.0.0.1"

echo "[CodEdu] Certificates generated:"
echo "  Key:  $CERT_DIR/server.key"
echo "  Cert: $CERT_DIR/server.crt"
echo ""
echo "[CodEdu] For production, replace these with real certificates from Let's Encrypt."
