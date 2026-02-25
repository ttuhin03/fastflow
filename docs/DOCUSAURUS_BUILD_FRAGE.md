# Docusaurus-Build-Fix („reading 'date'“)

**Status: Behoben.** Der Docs-Build läuft mit den Patches in `patches/` plus folgenden manuellen Anpassungen in `node_modules` (falls nach `npm install` der Build wieder fehlschlägt, diese erneut anwenden oder `npx patch-package` mit vollen Rechten ausführen, um die Patches zu aktualisieren):

- **@docusaurus/plugin-content-blog** `lib/client/structuredDataUtils.js`: In `getBlogPost` Guard `if (!metadata?.date) return null` und `.filter(Boolean)` nach dem Map; in `useBlogPostStructuredData` früher Return mit `if (!metadata?.date)`.
- **@docusaurus/theme-classic** `lib/theme/BlogPostItem/Header/Info/index.js` und `lib/theme/BlogPostPage/Metadata/index.js`: `if (!metadata?.date) return null` vor der Destrukturierung von `metadata`.

Ursache war das bekannte Docusaurus-3.9.x-Problem: Structured-Data/SEO-Logik erwartet teils ein `date`-Feld (Blog), während Docs nur `lastUpdatedAt` haben; bei Kategorie-/Tag-Seiten oder geteilten Metadaten-Utilities führt das zu `Cannot read properties of undefined (reading 'date')`.
