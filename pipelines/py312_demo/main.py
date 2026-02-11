"""
Demo-Pipeline mit Python 3.12 und Dependencies.

Zeigt python_version 3.12 in Kombination mit requirements.txt.
"""

import sys

print("Pipeline 'py312_demo' gestartet")
print(f"Python: {sys.version}")

import requests
print(f"requests {requests.__version__}")

print("py312_demo erfolgreich abgeschlossen")
