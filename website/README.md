# Fast-Flow marketing site

Static marketing site for [Fast-Flow](https://github.com/ttuhin03/fastflow) — no build step.

## Preview locally

```bash
cd website
python3 -m http.server 4173
# open http://localhost:4173
```

## Structure

```
website/
├── index.html       # interactive marketing landing page
├── manifesto.html   # Anti-Overhead Manifesto
├── support.js       # DC runtime (loads React from CDN)
├── .nojekyll        # keep GitHub Pages from running Jekyll
└── README.md
```

## Deploy with GitHub Pages

The workflow [`.github/workflows/deploy-website.yml`](../.github/workflows/deploy-website.yml) publishes this folder on every push to `main` that touches `website/`.

One-time setup in the repo:

1. **Settings → Pages → Build and deployment → Source**: GitHub Actions
2. Merge this branch (or push `website/` to `main`)
3. Site URL: `https://ttuhin03.github.io/fastflow/`

You can also run the workflow manually via **Actions → Deploy marketing website → Run workflow**.

## `support.js` ist Vendor-Code

`support.js` ist ein **generiertes** Bundle der Design-Canvas-Runtime (`dc-runtime`).
Der Header der Datei sagt `do not edit`, und das Quellverzeichnis `dc-runtime/`
gehoert nicht zu diesem Repo — die Datei wird also als Vendor-Artefakt gepflegt und
nicht von Hand gepatcht. Sie ist in [`.sonarcloud.properties`](../.sonarcloud.properties)
per `sonar.exclusions` aus der statischen Analyse ausgenommen.

### Bewertetes Finding: `jssecurity:S8476` (False Positive)

SonarQube meldet in `boot()` eine *Client-Side Request Forgery* auf:

```js
fetch(location.href).then((res) => res.ok ? res.text() : "")
```

Der Call laedt das **eigene Dokument** noch einmal, um das rohe `<x-dc>`-Template zu
bekommen — die DOM-Variante wurde zu dem Zeitpunkt schon geparst und ersetzt.

Kein Angriffspfad, weil:

- `location.href` **ist** die URL, aus der das Dokument geladen wurde. Der Request ist
  damit konstruktionsbedingt same-origin; er laesst sich nicht auf einen fremden Host
  umlenken, ohne dass der Angreifer die Seite ohnehin schon kontrolliert.
- Es ist ein `GET` ohne Seiteneffekt — nichts, was sich zu einem state-changing
  Request forgen liesse.
- Die Antwort sind die eigenen Bytes der Seite. Was daraus via `parseDcText` →
  `updateHtml` → `compileTemplate` ins DOM geht, ist das Markup, das der Browser
  sowieso schon geladen hat — kein zusaetzlicher Injection-Vektor.

Sonar taggt hier generisch `location.*` als *tainted source*; gemeint ist die Klasse
`fetch(<angreiferwaehlbares Ziel>)`, z. B. aus einem Query-Parameter. Das liegt hier
nicht vor.
