"""
Fehlerhafte Test-Pipeline.

Diese Pipeline demonstriert eine fehlerhafte Pipeline-Ausführung,
die mit einem Exit-Code != 0 beendet wird. Nützlich zum Testen
von Fehlerbehandlung und Logging.
"""

import sys

print("Test-Pipeline 'test_failing' gestartet")
print("Diese Pipeline wird absichtlich fehlschlagen...")

# Pipeline mit Fehler beenden
print("Fehler: Pipeline schlägt absichtlich fehl")
sys.exit(1)
