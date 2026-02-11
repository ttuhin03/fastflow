"""
Test-Pipeline mit Dependencies.

Diese Pipeline demonstriert eine Pipeline-Ausführung mit
externen Dependencies aus requirements.txt. Sie verwendet
die 'requests'-Bibliothek um eine HTTP-Anfrage zu stellen.
"""

import os
import sys

print("Test-Pipeline 'test_with_requirements' gestartet")
print(f"Python-Version: {sys.version}")

try:
    # Import externer Dependency
    import requests
    
    # Test HTTP-Anfrage (falls möglich)
    print("requests-Bibliothek erfolgreich importiert")
    print(f"requests Version: {requests.__version__}")
    
    # Pipeline erfolgreich beendet
    print("Test-Pipeline 'test_with_requirements' erfolgreich abgeschlossen")
    
except ImportError as e:
    print(f"Fehler: Dependency konnte nicht importiert werden: {e}")
    sys.exit(1)
