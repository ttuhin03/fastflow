"""
Pipeline mit vielen Dependencies.

Lädt eine große Anzahl Bibliotheken – nützlich zum Testen von
uv-Setup, setup_duration und Pre-Heating.
"""

import sys

print("Pipeline 'heavy_deps' gestartet")
print(f"Python: {sys.version}")

# Einige Imports (repräsentativ; viele weitere in requirements.txt)
import numpy as np
import pandas as pd
import requests
import yaml
import pydantic

print(f"numpy {np.__version__}, pandas {pd.__version__}")
print(f"requests {requests.__version__}, pydantic {pydantic.__version__}")
print("heavy_deps erfolgreich abgeschlossen")
