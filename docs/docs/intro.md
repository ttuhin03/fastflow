---
sidebar_position: 1
---

# Fast-Flow – Übersicht

**Der schlanke, Docker-native, Python-zentrische Task-Orchestrator.**

![Fast-Flow Banner](/img/fastflow_banner.png)

Fast-Flow ist die Antwort auf die Komplexität von Airflow und die Schwerfälligkeit traditioneller CI/CD-Tools. Er wurde für Entwickler gebaut, die echte Isolation wollen, ohne auf die Geschwindigkeit lokaler Skripte zu verzichten.

:::tip
Lies das [Anti-Overhead-Manifesto](/docs/manifesto), um zu verstehen, warum Fast-Flow die Alternative zu Airflow, Dagster & Co. ist.
:::

:::info
Nutze das **[fastflow-pipeline-template](https://github.com/ttuhin03/fastflow-pipeline-template)** für einen schnellen Einstieg und eine klare Pipeline-Struktur.
:::

## Was ist Fast-Flow?

- **Code First:** Dein Python-Skript läuft, wie es ist – ohne DAG-Dekorateure, Operatoren oder IO-Manager.
- **uv + Docker:** Jede Pipeline läuft in einem isolierten Container; Dependencies kommen per uv-Cache in Millisekunden. Die Python-Version ist beliebig pro Pipeline wählbar (z.B. 3.10, 3.11, 3.12).
- **Git als Quelle:** Push to Deploy – kein Image-Build, kein manueller Upload. Der Orchestrator zieht Änderungen per Webhook oder Sync.
- **Ein Container:** Kein Cluster, keine Worker-Farm. Ein FastAPI-Container plus Docker-Socket-Proxy.

## Nächste Schritte

- [**Schnellstart**](/docs/schnellstart) – Fast-Flow in wenigen Minuten starten
- [**Setup-Anleitung**](/docs/setup) – Ausführlich: Env-Variablen, OAuth, Verzeichnisse
- [**Erste Pipeline**](/docs/pipelines/erste-pipeline) – Tutorial von null an
- [**Manifesto**](/docs/manifesto) – Die Philosophie und der Vergleich zu Airflow, Dagster, Mage
- [**Architektur**](/docs/architektur) – Runner-Cache, Container-Lifecycle, Datenfluss
- [**Pipelines**](/docs/pipelines/uebersicht) – Struktur, `main.py`, `requirements.txt`, `pipeline.json`
- [**Troubleshooting**](/docs/troubleshooting) – Häufige Fehler und Lösungen
- [**Disclaimer & Haftungsausschluss**](/docs/disclaimer) – Sicherheit, Beta-Status, Haftung
