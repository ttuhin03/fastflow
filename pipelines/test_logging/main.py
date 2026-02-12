"""
Test-Pipeline für Logging und Frontend-Tests.

Diese Pipeline wartet 20 Sekunden und gibt währenddessen regelmäßig
Logs aus, um das Frontend-Log-Streaming und die UI zu testen.
"""

import time
import sys
import os
from datetime import datetime

print("=" * 60)
print("Test-Pipeline 'test_logging' gestartet")
print("=" * 60)
print(f"Python-Version: {sys.version}")
print(f"Start-Zeitpunkt: {datetime.now().isoformat()}")
print()

# Environment-Variablen anzeigen
print("Environment-Variablen:")
print("-" * 60)
test_env = os.getenv("TEST_ENV_VAR", "not_set")
print(f"TEST_ENV_VAR: {test_env}")

log_level = os.getenv("LOG_LEVEL", "INFO")
print(f"LOG_LEVEL: {log_level}")

custom_var = os.getenv("CUSTOM_VAR", "default")
print(f"CUSTOM_VAR: {custom_var}")
print()

# 20 Sekunden warten mit regelmäßigen Logs
print("Starte 20-Sekunden-Wartezeit mit Logging...")
print("-" * 60)

for i in range(20):
    elapsed = i + 1
    remaining = 20 - elapsed
    
    # Verschiedene Log-Level simulieren
    if i % 5 == 0:
        print(f"[INFO] Sekunde {elapsed}/20 - Verbleibend: {remaining}s")
    elif i % 3 == 0:
        print(f"[DEBUG] Progress: {elapsed * 5}% - Status: Running")
    else:
        print(f"[LOG] Tick {elapsed} - Zeitstempel: {datetime.now().strftime('%H:%M:%S')}")
    
    # Alle 5 Sekunden einen Status-Update
    if i % 5 == 4:
        print(f"[STATUS] Checkpoint erreicht - {elapsed} Sekunden vergangen")
        print()
    
    time.sleep(1)

print("-" * 60)
print("Wartezeit abgeschlossen!")
print()

# Finale Zusammenfassung
print("=" * 60)
print("Pipeline-Zusammenfassung:")
print("=" * 60)
print(f"Gesamt-Dauer: 20 Sekunden")
print(f"End-Zeitpunkt: {datetime.now().isoformat()}")
print(f"Log-Zeilen generiert: ~25")
print(f"Status: Erfolgreich abgeschlossen")
print("=" * 60)

# Pipeline erfolgreich beendet
sys.exit(0)
