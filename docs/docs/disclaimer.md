---
sidebar_position: 30
---

# Disclaimer & Haftungsausschluss

:::caution Wichtiger Hinweis zu Sicherheit und Haftung
Dieses Projekt befindet sich in einem **frühen Stadium / Beta-Status**. Der Orchestrator benötigt Zugriff auf den **Docker-Socket**, um Pipelines auszuführen. Bei **unsachgemäßer Konfiguration** besteht ein **Sicherheitsrisiko** für das Host-System.
:::

## Nutzung auf eigene Gefahr

Die Software wird **„wie besehen“ (as is)** zur Verfügung gestellt. Der Autor übernimmt **keinerlei Haftung** für:

- Schäden an Hardware
- Datenverlust
- Sicherheitslücken
- Betriebsunterbrechungen

die durch die Nutzung dieser Software entstehen könnten.

## Keine Gewährleistung

Es besteht **keine Garantie** für:

- die **Richtigkeit** der Software,
- ihre **Funktionsfähigkeit** oder
- ihre **ständige Verfügbarkeit**.

## Sicherheitsempfehlung

- **Nie** diesen Orchestrator **ungeschützt im öffentlichen Internet** betreiben.
- **Immer** den empfohlenen **Docker-Socket-Proxy** und eine **starke Authentifizierung** (OAuth, sichere JWT- und Encryption-Keys) verwenden.

Ausführlich: [Docker Socket Proxy](/docs/deployment/DOCKER_PROXY), [Setup-Anleitung](/docs/setup) (Produktions-Checkliste), [Deployment](/docs/deployment/PRODUCTION).
