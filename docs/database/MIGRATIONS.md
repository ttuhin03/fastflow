# Datenbank-Migrationen

Dieses Dokument erklärt, wie Datenbank-Migrationen in Fast-Flow manuell ausgeführt werden.

## Übersicht

Fast-Flow verwendet [Alembic](https://alembic.sqlalchemy.org/) für Datenbank-Migrationen. Migrationen werden **nicht automatisch** beim Container-Start ausgeführt, sondern müssen manuell ausgeführt werden.

## Migrationen ausführen

### Im Docker-Container

Wenn die Anwendung in einem Docker-Container läuft:

```bash
# Migrationen ausführen
docker-compose exec fastflow-orchestrator alembic upgrade head

# Oder wenn der Container anders heißt:
docker exec <container-name> alembic upgrade head
```

### Lokal (ohne Docker)

Wenn die Anwendung lokal läuft:

```bash
# Im Projektverzeichnis
cd /path/to/fastflow

# Migrationen ausführen
alembic upgrade head
```

## Migration-Status prüfen

Um zu sehen, welche Migrationen bereits ausgeführt wurden:

```bash
# Im Container
docker-compose exec fastflow-orchestrator alembic current

# Oder lokal
alembic current
```

Um alle verfügbaren Migrationen zu sehen:

```bash
# Im Container
docker-compose exec fastflow-orchestrator alembic history

# Oder lokal
alembic history
```

## Neue Migration erstellen

Wenn das Datenbankschema geändert wurde (z.B. neue Felder im Model), muss eine neue Migration erstellt werden:

```bash
# Im Container
docker-compose exec fastflow-orchestrator alembic revision --autogenerate -m "Beschreibung der Änderung"

# Oder lokal
alembic revision --autogenerate -m "Beschreibung der Änderung"
```

Die neue Migration wird in `alembic/versions/` erstellt und sollte vor dem Ausführen überprüft werden.

## Migration rückgängig machen

Um die letzte Migration rückgängig zu machen:

```bash
# Im Container
docker-compose exec fastflow-orchestrator alembic downgrade -1

# Oder lokal
alembic downgrade -1
```

Um zu einer spezifischen Revision zurückzukehren:

```bash
# Im Container
docker-compose exec fastflow-orchestrator alembic downgrade <revision-id>

# Oder lokal
alembic downgrade <revision-id>
```

## Verfügbare Migrationen

### 001_add_is_parameter_to_secret
Fügt das Feld `is_parameter` zur `secrets`-Tabelle hinzu.

### 002_add_webhook_fields
Fügt `webhook_runs` zur `pipelines`-Tabelle und `triggered_by` zur `pipeline_runs`-Tabelle hinzu.

### 003_add_user_management_fields
Fügt Nutzermanagement-Felder zur `users`-Tabelle hinzu:
- `email` (optional)
- `role` (READONLY, WRITE, ADMIN)
- `blocked` (boolean)
- `invitation_token`, `invitation_expires_at` (optional; in **006** wieder entfernt)
- `microsoft_id` (optional)

### 004_github_invitation
GitHub OAuth + Token-Einladung:
- Neue Tabelle `invitations` (recipient_email, token, is_used, expires_at, role, created_at)
- Neue Spalte `users.github_id` (optional, unique, für GitHub-Login)

### 005_make_password_hash_nullable
- `users.password_hash` war kurz nullable (Vorstufe für 007).

### 006_drop_user_invitation_columns
- Entfernt `users.invitation_token` und `users.invitation_expires_at` (Einladungen nur noch über Tabelle `invitations`).

### 007_drop_password_hash
- Entfernt `users.password_hash` (Login nur noch via GitHub OAuth).

### 008_add_google_avatar
- `users.google_id` (optional, unique) für Google OAuth.
- `users.avatar_url` (optional) für Profilbild von OAuth-Providern.

## Wichtige Hinweise

1. **Backup erstellen**: Vor dem Ausführen von Migrationen sollte ein Backup der Datenbank erstellt werden, besonders in Produktionsumgebungen.

2. **Migrationen prüfen**: Neue Migrationen sollten immer überprüft werden, bevor sie ausgeführt werden.

3. **SQLite-Besonderheiten**: SQLite unterstützt einige ALTER TABLE-Operationen nicht direkt. Alembic verwendet `batch_alter_table` für SQLite, was eine Tabelle kopieren kann. Bei großen Tabellen kann dies Zeit in Anspruch nehmen.

4. **Produktionsumgebungen**: In Produktionsumgebungen sollten Migrationen während eines Wartungsfensters ausgeführt werden.

## Troubleshooting

### Migration hängt
Wenn eine Migration hängt, kann es helfen:
- Die Datenbank zu prüfen, ob sie gelockt ist
- Den Container neu zu starten
- Die Migration manuell zu überprüfen

### Migration schlägt fehl
Wenn eine Migration fehlschlägt:
1. Prüfe die Fehlermeldung
2. Prüfe den aktuellen Status: `alembic current`
3. Bei Bedarf die Migration rückgängig machen: `alembic downgrade -1`
4. Die Migration korrigieren und erneut ausführen

### Enum-Werte korrigieren
Falls Enum-Werte in der Datenbank nicht mit dem Code übereinstimmen (z.B. 'readonly' statt 'READONLY'), werden sie automatisch beim Lesen korrigiert (`app/auth.py`, `get_current_user`).

## Beispiel-Workflow

```bash
# 1. Status prüfen
docker-compose exec fastflow-orchestrator alembic current

# 2. Migrationen ausführen
docker-compose exec fastflow-orchestrator alembic upgrade head

# 3. Status erneut prüfen
docker-compose exec fastflow-orchestrator alembic current
```

## Weitere Informationen

- [Alembic Dokumentation](https://alembic.sqlalchemy.org/)
- [SQLModel Dokumentation](https://sqlmodel.tiangolo.com/)
