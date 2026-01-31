---
sidebar_position: 1
---

# Fast-Flow – Übersicht

**Der schlanke, Docker-native, Python-zentrische Task-Orchestrator.**

![Fast-Flow Banner](/img/fastflow_banner.png)

Fast-Flow ist die Antwort auf die Komplexität von Airflow und die Schwerfälligkeit traditioneller CI/CD-Tools. Er wurde für Entwickler gebaut, die echte Isolation wollen, ohne auf die Geschwindigkeit lokaler Skripte zu verzichten.

:::tip In 30 Sekunden
**Ein Python-Skript pro Pipeline.** Kein DAG, kein Image-Build. `git push` → Sync → Run. Jede Pipeline läuft in einem isolierten Docker-Container mit **uv** (JIT-Dependencies). Ein FastAPI-Container + Docker-Socket-Proxy – fertig.
:::

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

| Ziel | Seite | Dauer (ca.) |
|------|--------|-------------|
| Sofort starten | [**Schnellstart**](/docs/schnellstart) | ~5 Min. |
| Vollständig einrichten | [**Setup-Anleitung**](/docs/setup) | ~15 Min. |
| Erste Pipeline schreiben | [**Erste Pipeline**](/docs/pipelines/erste-pipeline) | ~10 Min. |
| Philosophie verstehen | [**Manifesto**](/docs/manifesto) | ~5 Min. |
| Architektur verstehen | [**Architektur**](/docs/architektur) | ~5 Min. |
| Pipelines im Detail | [**Pipelines – Übersicht**](/docs/pipelines/uebersicht) | — |
| Probleme lösen | [**Troubleshooting**](/docs/troubleshooting) | — |
| Rechtliches | [**Disclaimer**](/docs/disclaimer) | — |
