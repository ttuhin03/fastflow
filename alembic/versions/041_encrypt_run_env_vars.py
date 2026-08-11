"""Add encrypted_env_vars to pipeline_runs and scrub plaintext env_vars

Revision ID: 041_encrypt_run_env_vars
Revises: 040_add_user_last_login
Create Date: 2026-08-11

pipeline_runs.env_vars hat bisher den vollständig gemergten Env-Satz eines Runs
gespeichert - inklusive der entschlüsselten Secrets aus der secrets-Tabelle und
aus pipeline.json/encrypted_env. Damit lagen Klartext-Credentials in der
Datenbank, in Read-Replicas, in pg_dump-Ausgaben und in Backups.

Diese Migration:
1. legt die Spalte encrypted_env_vars an (Fernet-Ciphertext der ad-hoc
   Env-Vars des Aufrufers, nur die sind beim Retry nicht neu auflösbar)
2. entfernt aus bestehenden env_vars-Zeilen alle Werte, deren Key nicht mit
   "_fastflow_" beginnt

ACHTUNG - Schritt 2 ist bewusst destruktiv und nicht umkehrbar. Für Alt-Zeilen
ist die Provenienz nicht rekonstruierbar (die Information, welcher Key aus
welcher Merge-Stufe kam, existiert nicht mehr), deshalb wird konservativ jeder
Nicht-Metadaten-Key entfernt. Das kostet historisches Audit-Detail und ist für
einen Security-Fix der richtige Trade-off. downgrade() stellt diese Werte NICHT
wieder her.

ACHTUNG - dieser Scrub räumt nur die Live-Datenbank auf. Bestehende Backups und
Dumps enthalten die Klartext-Werte weiterhin. Die eigentliche Remediation für
betroffene Credentials ist Rotation.

Die Scrub-Logik ist absichtlich als eigene Kopie hier drin und importiert nicht
app.services.run_env: Migrationen sind historische Artefakte und dürfen sich
nicht mit App-Code mitverändern.
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "041_encrypt_run_env_vars"
down_revision = "040_add_user_last_login"
branch_labels = None
depends_on = None

# Keys mit diesem Präfix sind interne Run-Metadaten (Fehlertyp, Retry-Zähler)
# und enthalten keine Secret-Werte - sie bleiben erhalten.
_METADATA_PREFIX = "_fastflow_"

# Zeilen pro Batch. Begrenzt Speicherverbrauch UND - weil jeder Batch im
# autocommit_block() einzeln committet - die Dauer, die eine einzelne
# Transaktion Schreib-Locks auf pipeline_runs hält.
_CHUNK_SIZE = 500


def _scrub(env_vars):
    """Behält nur _fastflow_*-Metadaten. Gibt None zurück, wenn nichts zu tun ist."""
    if not isinstance(env_vars, dict) or not env_vars:
        return None
    scrubbed = {k: v for k, v in env_vars.items() if str(k).startswith(_METADATA_PREFIX)}
    if len(scrubbed) == len(env_vars):
        return None  # war schon sauber
    return scrubbed


def _scrub_rows(conn) -> int:
    """
    Entfernt Klartext-Werte aus pipeline_runs.env_vars. Gibt die Zahl der
    geänderten Zeilen zurück.

    Die Tabelle wird reflektiert statt per sa.table() deklariert: env_vars ist
    unter PostgreSQL JSON und unter SQLite TEXT, und id ist ein nativer
    uuid-Typ bzw. CHAR. Nur mit den echten Typen funktionieren `IN (...)` und
    der Bind-Parameter des UPDATE auf beiden Backends.
    """
    runs = sa.Table("pipeline_runs", sa.MetaData(), autoload_with=conn)

    # Keine LIMIT/OFFSET-Pagination: bei n Zeilen scannt die O(n²/chunk) und war
    # auf großen Tabellen messbar superlinear. Die IDs einmal holen (schmal) und
    # dann per IN-Batch nachladen ist linear.
    ids = [row[0] for row in conn.execute(sa.select(runs.c.id))]

    update_stmt = (
        runs.update()
        .where(runs.c.id == sa.bindparam("_row_id"))
        .values(env_vars=sa.bindparam("_new_env", type_=runs.c.env_vars.type))
    )

    scrubbed_count = 0
    for start in range(0, len(ids), _CHUNK_SIZE):
        batch_ids = ids[start : start + _CHUNK_SIZE]
        rows = conn.execute(
            sa.select(runs.c.id, runs.c.env_vars).where(runs.c.id.in_(batch_ids))
        ).fetchall()

        params = []
        for row_id, env_vars in rows:
            # Je nach Backend/Treiber kommt die JSON-Spalte als str zurück.
            if isinstance(env_vars, str):
                try:
                    env_vars = json.loads(env_vars)
                except ValueError:
                    continue
            scrubbed = _scrub(env_vars)
            if scrubbed is None:
                continue
            params.append({"_row_id": row_id, "_new_env": scrubbed})

        if params:
            # executemany: ein Roundtrip pro Batch statt pro Zeile.
            conn.execute(update_stmt, params)
            scrubbed_count += len(params)

    return scrubbed_count


def upgrade() -> None:
    # ALTER TABLE nimmt unter PostgreSQL ein ACCESS EXCLUSIVE Lock auf
    # pipeline_runs. Eine nullable Spalte ohne Default anzuhängen ist O(1), das
    # Lock ist also nur kurz gehalten.
    op.add_column(
        "pipeline_runs",
        sa.Column("encrypted_env_vars", sa.Text(), nullable=True),
    )

    # Der Scrub läuft AUSSERHALB der Migrations-Transaktion. Sonst würde das
    # ACCESS EXCLUSIVE Lock von oben für die gesamte Scrub-Dauer gehalten -
    # alembic wickelt run_migrations() in eine einzige Transaktion, und weil
    # weder lock_timeout noch statement_timeout gesetzt sind, würden parallele
    # Leser (Surge-Pod beim Rolling Update, Read-Replica, BI-Client) nicht
    # scheitern sondern unbegrenzt hängen. Im autocommit_block committet jeder
    # Batch einzeln und nimmt nur kurz ROW EXCLUSIVE.
    with op.get_context().autocommit_block():
        scrubbed_count = _scrub_rows(op.get_bind())

    print(f"041: env_vars von {scrubbed_count} Run-Zeile(n) von Klartext-Werten befreit")


def downgrade() -> None:
    # Die gescrubbten Klartext-Werte kommen nicht zurück - siehe Docstring.
    op.drop_column("pipeline_runs", "encrypted_env_vars")
