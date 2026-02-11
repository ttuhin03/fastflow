"""
Einfache Test-Pipeline ohne Dependencies.

Diese Pipeline demonstriert eine einfache Pipeline-Ausführung
ohne externe Dependencies. Sie gibt einfach eine Nachricht aus
und beendet sich erfolgreich.
"""

import os
import sys

print("Test-Pipeline 'test_simple' gestartet")
print(f"Python-Version: {sys.version}")

# Test Environment-Variablen
test_env = os.getenv("TEST_ENV_VAR", "default_value")
print(f"TEST_ENV_VAR: {test_env}")

# Pipeline erfolgreich beendet
print("Test-Pipeline 'test_simple' erfolgreich abgeschlossen")
