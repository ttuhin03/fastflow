# Coding Guidelines & Dokumentations-Standards

**Diese Datei sollte am Anfang jedes Prompts in Cursor mitgeschickt werden, um konsistente Code-Dokumentation und Standards zu gewährleisten.**

---

## 1. Code-Dokumentation

### Python Docstrings
- **Format**: Google-Style Docstrings
- **Alle Funktionen und Klassen** müssen Docstrings haben
- **Typ-Hints**: Alle Funktionen sollten Type Hints haben

**Beispiel:**
```python
def run_pipeline(
    name: str,
    env_vars: Optional[Dict[str, str]] = None,
    parameters: Optional[Dict[str, str]] = None
) -> PipelineRun:
    """
    Startet eine Pipeline mit optionalen Environment-Variablen und Parametern.
    
    Args:
        name: Name der Pipeline (muss existieren)
        env_vars: Dictionary mit Environment-Variablen (werden als Secrets injiziert)
        parameters: Dictionary mit Pipeline-Parametern (werden als Env-Vars injiziert)
    
    Returns:
        PipelineRun: Der erstellte PipelineRun-Datensatz mit Status PENDING
        
    Raises:
        ValueError: Wenn Pipeline nicht existiert
        RuntimeError: Wenn Concurrency-Limit erreicht ist
    """
    pass
```

### Inline-Kommentare
- **Komplexe Logik**: Erkläre "Warum", nicht "Was"
- **Workarounds/Hacks**: Immer mit Kommentar markieren (`# TODO:`, `# HACK:`, `# FIXME:`)
- **Business-Logic**: Wichtige Geschäftsregeln kommentieren

### Module-Dokumentation
- Jede Python-Datei sollte einen Module-Docstring am Anfang haben
- Kurze Beschreibung der Verantwortlichkeit des Moduls

**Beispiel:**
```python
"""
Docker Container Execution Module.

Dieses Modul verwaltet die Ausführung von Pipeline-Containern:
- Container-Start mit Resource-Limits
- Log-Streaming und Persistenz
- Metrics-Monitoring (CPU/RAM)
- Container-Cleanup
"""
```

---

## 2. README & Dokumentation

### README.md Struktur
Die `README.md` muss folgende Abschnitte enthalten:

1. **Übersicht**: Kurze Beschreibung des Projekts
2. **Features**: Liste der Hauptfeatures
3. **Schnellstart**: Installation und erste Schritte
4. **Konfiguration**: Wichtige Environment-Variablen
5. **Development**: Setup für Entwickler
6. **Architektur**: Überblick über die Architektur (optional, detailliert in `docs/`)
7. **Troubleshooting**: Häufige Probleme und Lösungen

### Dokumentations-Dateien
- **`docs/` Ordner**: Für detaillierte Dokumentation
- **API-Dokumentation**: Automatisch generiert (FastAPI `/docs`), aber wichtige Endpoints in README erwähnen
- **Architektur-Dokumentation**: In `docs/ARCHITECTURE.md` (optional)

### Code-Beispiele
- README sollte immer funktionierende Code-Beispiele enthalten
- Beispiele müssen aktuell und getestet sein

---

## 3. Changelog

### Format: Keep a Changelog
Wir verwenden das [Keep a Changelog](https://keepachangelog.com/de/1.0.0/)-Format.

### Datei: `CHANGELOG.md`
- **Ort**: Im Root-Verzeichnis des Projekts
- **Format**: Markdown
- **Einträge**: Alle Änderungen müssen dokumentiert werden

### Kategorien
- **Added**: Neue Features
- **Changed**: Änderungen an bestehenden Features
- **Deprecated**: Features, die bald entfernt werden
- **Removed**: Entfernte Features
- **Fixed**: Bug-Fixes
- **Security**: Sicherheits-Updates

### Beispiel-Struktur:
```markdown
# Changelog

Alle nennenswerten Änderungen an diesem Projekt werden in dieser Datei dokumentiert.

Das Format basiert auf [Keep a Changelog](https://keepachangelog.com/de/1.0.0/),
und dieses Projekt hält sich an [Semantic Versioning](https://semver.org/lang/de/).

## [Unreleased]

### Added
- Pipeline-Statistiken (total_runs, successful_runs, failed_runs)
- Resource-Limits (Hard/Soft) mit Metadaten-JSON
- Live CPU/RAM Monitoring für Container

### Changed
- SQLite WAL-Mode aktiviert für bessere Concurrency

### Fixed
- Race-Condition bei Concurrency-Limits behoben
- Container-Cleanup mit Error-Handling

## [1.0.0] - 2024-01-15

### Added
- Initial Release
- Docker-in-Docker Executor
- Git-Sync mit GitHub Apps
- Basic Authentication
- NiceGUI Frontend
```

### Changelog-Regeln
- **Jede Code-Änderung**: Muss im Changelog dokumentiert werden
- **Datum**: Format `YYYY-MM-DD`
- **Versionen**: Semantic Versioning (MAJOR.MINOR.PATCH)
- **Unreleased**: Änderungen, die noch nicht released sind
- **Beschreibung**: Klar und verständlich, auf Deutsch

---

## 4. Allgemeine Coding-Standards

### Code-Style
- **Python**: PEP 8 konform
- **Linting**: `black` für Formatierung, `ruff` für Linting
- **Line Length**: Max 100 Zeichen (wenn möglich)

### Error-Handling
- **Spezifische Exceptions**: Verwende spezifische Exception-Types
- **Error-Messages**: Klar und hilfreich, auf Deutsch
- **Logging**: Wichtige Fehler immer loggen

### Testing
- **Test-Dokumentation**: Test-Funktionen müssen Docstrings haben
- **Test-Namen**: Aussagekräftig (`test_pipeline_start_with_invalid_name`)

### Git-Commit-Messages
- **Format**: Conventional Commits (optional, aber empfohlen)
- **Beispiele**:
  - `feat: Add pipeline statistics tracking`
  - `fix: Resolve race condition in concurrency limits`
  - `docs: Update README with new features`

---

## 5. Wichtige Hinweise für LLM-Chats

### Bei Unsicherheiten
- **Wichtig**: Wenn du dir bei etwas nicht sicher bist (API-Nutzung, Best Practices, Framework-Spezifika), solltest du:
  1. **Zuerst**: Den Nutzer fragen oder nach Klärung bitten
  2. **Alternativ**: Im Internet recherchieren (web_search) um aktuelle Informationen zu erhalten
  3. **Nicht**: Raten oder unsichere Annahmen treffen
- **Ziel**: Fehler vermeiden durch Klarstellung vor der Implementierung

### Bei Code-Änderungen
- **Immer**: Docstrings aktualisieren, wenn sich Funktions-Signatur ändert
- **Immer**: Changelog aktualisieren
- **Bei neuen Features**: README aktualisieren

### Bei neuen Features
1. Code schreiben mit vollständigen Docstrings
2. README.md aktualisieren (Features-Liste, Beispiele)
3. CHANGELOG.md aktualisieren (Unreleased → Added)
4. Ggf. Dokumentation in `docs/` ergänzen

### Bei Bug-Fixes
1. Code fixen
2. CHANGELOG.md aktualisieren (Unreleased → Fixed)
3. Ggf. README Troubleshooting aktualisieren

### Bei Breaking Changes
1. Code ändern
2. CHANGELOG.md aktualisieren (Unreleased → Changed/Breaking)
3. README.md aktualisieren (Migration Guide)
4. Version im Changelog setzen (neue Major-Version)

---

## 6. Checkliste vor Commits

- [ ] Code hat Docstrings (Funktionen, Klassen, Module)
- [ ] Type Hints vorhanden
- [ ] Kommentare für komplexe Logik
- [ ] CHANGELOG.md aktualisiert
- [ ] README.md aktualisiert (wenn nötig)
- [ ] Code formatiert (black)
- [ ] Keine Linting-Fehler (ruff)

---

## 7. Dokumentations-Prioritäten

### Hoch (Muss immer)
- Code-Docstrings
- Changelog-Einträge
- README-Updates bei neuen Features

### Mittel (Sollte)
- Inline-Kommentare bei komplexer Logik
- Troubleshooting-Dokumentation
- API-Dokumentation-Ergänzungen

### Niedrig (Kann)
- Architektur-Dokumentation
- Detaillierte How-To-Guides
- Diagramme und Visualisierungen
