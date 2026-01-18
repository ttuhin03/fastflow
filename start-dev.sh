#!/bin/bash

# Fast-Flow Orchestrator - Development Start-Skript
# Startet Backend + Frontend in Development-Modus

set -e

echo "🚀 Fast-Flow Orchestrator - Development Mode"
echo "=============================================="
echo ""

# Prüfe ob wir im richtigen Verzeichnis sind
if [ ! -f "docker-compose.dev.yaml" ]; then
    echo "❌ Fehler: docker-compose.dev.yaml nicht gefunden"
    exit 1
fi

# Prüfe Docker
if ! docker ps > /dev/null 2>&1; then
    echo "❌ Fehler: Docker läuft nicht. Bitte starte Docker Desktop."
    exit 1
fi
echo "✅ Docker läuft"

# Prüfe .env-Datei
if [ ! -f ".env" ]; then
    echo "⚠️  .env-Datei nicht gefunden. Erstelle sie aus .env.example..."
    cp .env.example .env
fi
echo "✅ .env-Datei vorhanden"

# Erstelle Verzeichnisse
echo "📁 Erstelle Verzeichnisse..."
mkdir -p pipelines logs data data/uv_cache
echo "✅ Verzeichnisse erstellt"

# Prüfe ob Frontend-Dependencies installiert sind
if [ ! -d "frontend/node_modules" ]; then
    echo "📦 Installiere Frontend-Dependencies..."
    cd frontend
    npm install
    cd ..
    echo "✅ Frontend-Dependencies installiert"
fi

# Baue Docker-Images
echo "🔨 Baue Docker-Images..."
docker-compose -f docker-compose.dev.yaml build

# Starte Container
echo "🚀 Starte Container (Backend + Frontend)..."
docker-compose -f docker-compose.dev.yaml up

echo ""
echo "========================================"
echo "✅ Development-Server gestartet!"
echo ""
echo "📝 URLs:"
echo "   Frontend: http://localhost:3000"
echo "   Backend:  http://localhost:8000"
echo "   Login:    Mit GitHub (GITHUB_CLIENT_ID, INITIAL_ADMIN_EMAIL in .env)"
echo ""
echo "💡 Nützliche Befehle:"
echo "   - Container stoppen: docker-compose -f docker-compose.dev.yaml down"
echo "   - Logs ansehen: docker-compose -f docker-compose.dev.yaml logs -f"
