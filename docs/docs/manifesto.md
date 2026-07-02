---
sidebar_position: 4
---

# Why Fast-Flow? The Anti-Overhead Manifesto

```text
.-----------------------------------------------------------.
|                                                           |
|   F A S T - F L O W   M A N I F E S T O                   |
|                                                           |
|   [ ] No Air-Castles (Airflow)                            |
|   [ ] No Magic Spells (Mage)                              |
|   [ ] No Complex Assets (Dagster)                         |
|                                                           |
|   [X] JUST. RUN. THE. SCRIPT.                             |
|                                                           |
|   >_ Python 3.11 + Docker + uv speed                      |
'-----------------------------------------------------------'
```

## 1. The philosophy: "Code First, Infrastructure Second"

Most modern orchestrators (Airflow, Dagster, Mage) suffer from the same disease: They force you to write your code for the tool, instead of the tool supporting your code.

We built Fast-Flow because we were tired of:

- Spending weeks arguing with DevOps about why `prophet` or `torch` cannot be imported in the cluster even though it works locally.
- Writing hundreds of lines of boilerplate code (decorators, operators, IO managers) just to automate a simple SQL query.
- Finding out that the tool does not support certain Python patterns because "DAG serialization" fails.

**Fast-Flow Rule #1:** If it runs in a local script, it runs here too. Without modification.

## 2. The deep dive: Why uv caching changes everything

The biggest pain point in orchestration is dependency hell.

- **Airflow/Dagster approach:** Either you use a huge "shared environment" (where libraries conflict) or you build a new Docker image for every change (which takes 5–10 minutes).
- **Fast-Flow approach:** We use uv cache JIT (Just-In-Time).

### Why this is better

When you add a heavy library like `prophet`:

- **Isolation:** Each pipeline gets its own virtual layer in the container. No conflicts.
- **Speed:** `uv` uses hardlinks. If `pandas` was loaded once on the server, it is available in every subsequent pipeline in 0.1 seconds.
- **DevOps freedom:** You do not have to ask anyone to build a new image for you. Write it in `requirements.txt`, the orchestrator handles the rest on startup.

## 3. Voices from the trenches

*The following quotes are representative paraphrases. They summarize the general consensus and the most common pain points as repeatedly expressed in the data engineering community (e.g. on Reddit).*

### Apache Airflow: "A full-time job in itself"

> "I spent months getting Airflow to run stably. It's great for huge teams with their own DevOps department, but for smaller projects it just feels clunky and oversized."

> "The problem is dependency hell. As soon as you use more than a few libraries, they conflict. In the end you hide everything in Docker containers just to save the environment."

### Dagster: "The asset abstraction as a golden cage"

> "The learning curve is extremely steep. You have to completely restructure your code to fit it into 'assets' or 'ops'. Once you're in, it's hard to get out."

### Mage & modern stack fatigue

> "Teams are tired of managing 20 different tools at the same time. We're seeing a return to simple Python-first workflows."

## 4. Why Fast-Flow is the answer

- **Against Airflow's clunkiness:** We are a single container. Ready in 60 seconds, instead of 6 months of "head against the wall."
- **Against Dagster's lock-in:** We have no IO managers. Your code belongs to you.
- **Against dependency hell:** uv caching, lightning-fast, isolated environments.

![Cognitive Load Comparison](/img/cognitive_load.png)

## 5. The reality check: A medium-complexity workflow

**The Fast-Flow way (pure Python) – `main.py`:**

```python
import requests
import pandas as pd
from sqlalchemy import create_engine
import os

# 1. Extraction
data = requests.get("https://api.example.com/metrics").json()
df = pd.DataFrame(data)

# 2. Transformation
df['processed'] = df['value'] * 1.2

# 3. Load (Postgres)
engine = create_engine(os.getenv("POSTGRES_URL"))
df.to_sql("metrics", engine, if_exists="append")

print("Pipeline completed successfully.")
```

## 6. The comparison

| Feature | Airflow | Dagster | Mage | **Fast-Flow** |
| --- | --- | --- | --- | --- |
| **Code adaptation** | High | High | Medium | **None (Plain Python)** |
| **Local testing** | Hard | Medium | Medium | **Easy** |
| **Heavy libs (Prophet)** | Painful | Painful | Medium | **Instant (uv cache)** |
| **Infrastructure** | 5–7 containers | 3–4 containers | 2–3 containers | **1 container (+ proxy)** |

## 7. The conclusion

We did not build Fast-Flow because we wanted more features. We built it because we wanted **less friction**.

Fast-Flow is for people who love their job (coding) but hate everything around it.

---

**Ready?** Use the **[Fast-Flow Pipeline Template](https://github.com/ttuhin03/fastflow-pipeline-template)** for your first pipeline.
