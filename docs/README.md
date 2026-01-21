# Fast-Flow Doku (Docusaurus)

Die Dokumentation wird mit [Docusaurus](https://docusaurus.io/) erzeugt.

## Voraussetzungen

- **Node.js** ≥ 20
- **npm** (im Projektroot: `npm install` für Workspaces)

## Installation

Im Projektroot:

```bash
npm install
```

Oder nur im `docs/`-Ordner:

```bash
cd docs
npm install
```

## Lokale Entwicklung

```bash
# Ab Projektroot
npm run docs:dev
```

oder

```bash
cd docs
npm run start
```

Die Doku läuft unter [http://localhost:3000](http://localhost:3000). Änderungen an Markdown werden automatisch neu geladen.

## Build

```bash
# Ab Projektroot
npm run docs:build
```

oder

```bash
cd docs
npm run build
```

Die statischen Dateien liegen in `docs/build/`. Lokaler Vorschau-Server: `npm run serve` (in `docs/`).

## Deployment (z.B. GitHub Pages)

```bash
cd docs
npm run deploy
```

Für GitHub Pages mit SSH: `USE_SSH=true npm run deploy`.  
Ohne SSH: `GIT_USER=<Dein-GitHub-User> npm run deploy`.

## Mermaid-Diagramme

In Markdown werden [Mermaid](https://mermaid.js.org/)-Diagramme per ` ```mermaid ` Code-Blöcke gerendert (z.B. in `docs/architektur.md`).

## Struktur

- `docs/` – Markdown-Quellen
- `src/` – React-Komponenten, CSS
- `static/img/` – Bilder, Favicon, Logo
- `sidebars.ts` – Sidebar-Reihenfolge (autogeneriert aus `docs/`)
