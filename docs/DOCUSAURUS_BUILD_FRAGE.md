# Docusaurus-Build-Fix („reading 'date'“)

**Status: Behoben.** Der Docs-Build nutzt Docusaurus **3.9.2-canary-6508** (Canary). Damit entfällt die Fehlermeldung `Cannot read properties of undefined (reading 'date')` ohne lokale Patches.

Ursache war das bekannte Docusaurus-3.9.x-Problem: Structured-Data/SEO-Logik erwartet teils ein `date`-Feld (Blog), während Docs nur `lastUpdatedAt` haben; bei Kategorie-/Tag-Seiten oder geteilten Metadaten-Utilities führte das zum Absturz. Die Canary-Version behebt diesen Edge-Case.

**Falls wieder auf stabile 3.9.2 gewechselt wird:** Dann wären die früheren Patches in `patches/` (plus `patch-package` im Root) wieder nötig, sofern Docusaurus 3.10+ noch nicht verfügbar ist.
