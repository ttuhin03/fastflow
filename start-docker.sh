#!/bin/bash

# Fast-Flow Orchestrator - Docker Start-Skript
# Dieses Skript startet die Anwendung in Docker

set -e

echo "🐳 Fast-Flow Orchestrator - Docker Start"
echo "=========================================="
echo ""

# Prüfe ob wir im richtigen Verzeichnis sind
if [ ! -f "docker-compose.yaml" ]; then
    echo "❌ Fehler: Bitte führe dieses Skript im Projekt-Root aus"
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
    
    # Generiere ENCRYPTION_KEY falls nicht vorhanden
    if ! grep -q "ENCRYPTION_KEY=" .env || grep -q "ENCRYPTION_KEY=your-fernet-key-here" .env; then
        echo "🔑 Generiere ENCRYPTION_KEY..."
        # Versuche Key zu generieren (mit Docker, falls Python nicht verfügbar)
        if command -v python3 &> /dev/null; then
            if python3 -c "from cryptography.fernet import Fernet" 2>/dev/null; then
                KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
                if [[ "$OSTYPE" == "darwin"* ]]; then
                    sed -i '' "s|ENCRYPTION_KEY=.*|ENCRYPTION_KEY=$KEY|" .env
                else
                    sed -i "s|ENCRYPTION_KEY=.*|ENCRYPTION_KEY=$KEY|" .env
                fi
                echo "✅ ENCRYPTION_KEY generiert und in .env gespeichert"
            else
                echo "⚠️  cryptography nicht installiert. Verwende Docker zum Generieren..."
                KEY=$(docker run --rm python:3.11-slim python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" 2>/dev/null || echo "")
                if [ ! -z "$KEY" ]; then
                    if [[ "$OSTYPE" == "darwin"* ]]; then
                        sed -i '' "s|ENCRYPTION_KEY=.*|ENCRYPTION_KEY=$KEY|" .env
                    else
                        sed -i "s|ENCRYPTION_KEY=.*|ENCRYPTION_KEY=$KEY|" .env
                    fi
                    echo "✅ ENCRYPTION_KEY generiert (via Docker) und in .env gespeichert"
                else
                    echo "⚠️  Konnte ENCRYPTION_KEY nicht generieren. Bitte setze ihn manuell in .env"
                fi
            fi
        else
            echo "⚠️  Python3 nicht gefunden. Verwende Docker zum Generieren..."
            KEY=$(docker run --rm python:3.11-slim python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" 2>/dev/null || echo "")
            if [ ! -z "$KEY" ]; then
                if [[ "$OSTYPE" == "darwin"* ]]; then
                    sed -i '' "s|ENCRYPTION_KEY=.*|ENCRYPTION_KEY=$KEY|" .env
                else
                    sed -i "s|ENCRYPTION_KEY=.*|ENCRYPTION_KEY=$KEY|" .env
                fi
                echo "✅ ENCRYPTION_KEY generiert (via Docker) und in .env gespeichert"
            else
                echo "⚠️  Konnte ENCRYPTION_KEY nicht generieren. Bitte setze ihn manuell in .env"
            fi
        fi
    fi
fi
echo "✅ .env-Datei vorhanden"

# Erstelle Verzeichnisse (für Volume-Mounts)
echo "📁 Erstelle Verzeichnisse..."
mkdir -p pipelines logs data data/uv_cache
echo "✅ Verzeichnisse erstellt"

# Baue Docker-Image (falls nötig)
echo "🔨 Baue Docker-Image (falls nötig)..."
docker-compose build

# Starte Container
echo "🚀 Starte Container..."
docker-compose up -d

echo ""
echo "========================================"
echo "✅ Container gestartet!"
echo ""
echo "📝 Nächste Schritte:"
echo "   1. Warte 10-20 Sekunden bis die Anwendung startet"
echo "   2. Öffne im Browser: http://localhost:8000"
echo "   3. Login: admin / admin"
echo ""
echo "💡 Development-Modus (Frontend + Backend getrennt):"
echo "   docker-compose -f docker-compose.dev.yaml up"
echo ""
echo "💡 Nützliche Befehle:"
echo "   - Logs ansehen: docker-compose logs -f orchestrator"
echo "   - Container stoppen: docker-compose down"
echo "   - Container neu starten: docker-compose restart"
echo "   - Status prüfen: docker-compose ps"
echo ""

# Zeige Logs (optional)
read -p "Logs jetzt anzeigen? (j/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[JjYy]$ ]]; then
    docker-compose logs -f orchestrator
fi
