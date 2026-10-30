#!/usr/bin/env bash
# ============================================================
# Aura AI — macOS launcher
# ============================================================
set -e
cd "$(dirname "$0")"

VENV=".venv"

# Pick a Python ≥ 3.10 — the Deepgram SDK v3 uses match/case (3.10+ syntax),
# so the default `python3` (which may be 3.9) is not enough.
PYBIN=""
for cand in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$cand" >/dev/null 2>&1; then
        ver=$("$cand" -c 'import sys; print("%d%d" % sys.version_info[:2])' 2>/dev/null)
        if [ -n "$ver" ] && [ "$ver" -ge 310 ] 2>/dev/null; then
            PYBIN="$cand"; break
        fi
    fi
done
if [ -z "$PYBIN" ]; then
    echo "❌ Need Python 3.10 or newer (Deepgram SDK requires it). Please install it."
    exit 1
fi

# Create virtual environment if it doesn't exist
if [ ! -d "$VENV" ]; then
    echo "📦 Creating Python virtual environment with $PYBIN ($("$PYBIN" --version 2>&1))…"
    "$PYBIN" -m venv "$VENV"
fi

# Activate
source "$VENV/bin/activate"

# Install / update dependencies
echo "📥 Installing dependencies…"
if ! python -m pip --version >/dev/null 2>&1; then
    python -m ensurepip --upgrade
fi
python -m pip install -q --upgrade pip
python -m pip install -q -r requirements.txt

if [ ! -x build/AuraSystemAudio ]; then
    echo "🔊 Building native Mac playback helper…"
    python native/build_audio.py
fi

# ── SSL Certificate Fix (macOS) ─────────────────────────────────────────────
# macOS Python doesn't bundle CA certificates, causing:
#   [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed
# on all HTTPS/WSS connections (Deepgram WebSocket, AI providers, etc.)
# We point Python at certifi's bundle (already in requirements.txt).
SSL_CERT="$(python3 -c 'import certifi; print(certifi.where())' 2>/dev/null)"
if [ -n "$SSL_CERT" ]; then
    export SSL_CERT_FILE="$SSL_CERT"
    export REQUESTS_CA_BUNDLE="$SSL_CERT"
    echo "🔐 SSL certificates: $SSL_CERT"
else
    # Fallback: macOS system certificate store
    SYS_CERT="/etc/ssl/cert.pem"
    if [ -f "$SYS_CERT" ]; then
        export SSL_CERT_FILE="$SYS_CERT"
        export REQUESTS_CA_BUNDLE="$SYS_CERT"
        echo "🔐 SSL certificates: $SYS_CERT (system fallback)"
    else
        echo "⚠️  Could not locate CA bundle — SSL connections may fail"
    fi
fi
# ────────────────────────────────────────────────────────────────────────────

# main.py selects an available local port when 8002 is already in use.

# Copy .env.example → .env if missing
if [ ! -f ".env" ] && [ -f ".env.example" ]; then
    cp ".env.example" ".env"
    echo "📄 Created .env from .env.example — fill in your API keys!"
fi

# Copy ai_providers.example.json → ai_providers.json if missing
if [ ! -f "ai_providers.json" ] && [ -f "ai_providers.example.json" ]; then
    cp "ai_providers.example.json" "ai_providers.json"
    echo "📄 Created ai_providers.json — add your AI provider API keys!"
fi

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║           Aura AI — macOS                ║"
echo "║  Global hotkeys need Accessibility       ║"
echo "║  System Settings → Privacy & Security    ║"
echo "╚══════════════════════════════════════════╝"
echo ""

python main.py
