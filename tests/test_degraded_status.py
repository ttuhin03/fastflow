"""
Tests für die Sichtbarmachung gestörter Backend-Zustände.

Hintergrund: Bei einem Datenbankausfall scheiterte bisher jeder geschützte
Endpoint bereits an der Auth-Dependency (get_current_user liest die Session aus
der DB) und lieferte einen nichtssagenden 500. Das Frontend konnte den Zustand
deshalb weder erkennen noch benennen. Abgedeckt sind hier:

- die Redaction von Infrastruktur-Details in unauthentifizierten Antworten
- /api/system/status als auth- und DB-unabhängige Statusquelle
- die Übersetzung von DB-Verbindungsfehlern in 503 + DATABASE_UNAVAILABLE
"""

import pytest
from sqlalchemy.exc import OperationalError

from app.core.readiness import redact_checks, redact_error


# Die Meldung, die im Produktionsvorfall tatsächlich im Log stand.
REAL_ERROR = (
    '(psycopg2.OperationalError) connection to server at '
    '"fastflow-db-rw.fastflow.svc" (10.96.48.225), port 5432 failed: '
    'FATAL:  password authentication failed for user '
    '"v-kubernet-fastflow-uOsRMVxRA9pl712dOcio-1789112989"'
)


class TestRedaction:
    def test_entfernt_host_ip_und_datenbankbenutzer(self):
        redacted = redact_error(REAL_ERROR)
        assert "fastflow-db-rw.fastflow.svc" not in redacted
        assert "10.96.48.225" not in redacted
        assert "v-kubernet-fastflow" not in redacted
        # Der diagnostisch nützliche Teil muss erhalten bleiben.
        assert "password authentication failed" in redacted

    def test_entfernt_verbindungs_url_mit_passwort(self):
        redacted = redact_error("could not connect: postgresql://u:s3cret@db.internal:5432/ff")
        assert "s3cret" not in redacted
        assert "db.internal" not in redacted

    def test_entfernt_hostnamen_aus_den_uebrigen_psycopg_meldungen(self):
        """
        Nicht nur die "connection to server at"-Form: Faellt die DNS-Aufloesung
        aus – der haeufigste Fall, wenn Service oder Namespace weg sind – meldet
        psycopg "could not translate host name". Beide Meldungen landen
        unauthentifiziert in /api/system/status und /ready.

        Die Kurzform service.namespace hat nur zwei Labels und wird deshalb von
        der generischen FQDN-Regel nicht erfasst; sie haengt allein an der
        Schluesselwort-Regel.
        """
        dns = redact_error(
            'could not translate host name "fastflow-db-rw.fastflow" to address: '
            "Name or service not known"
        )
        assert "fastflow-db-rw.fastflow" not in dns
        assert "translate host name" in dns

        refused = redact_error(
            "could not connect to server: Connection refused Is the server "
            'running on host "fastflow-db-rw.fastflow" (10.96.48.225) and '
            "accepting TCP/IP connections on port 5432?"
        )
        assert "fastflow-db-rw.fastflow" not in refused
        assert "10.96.48.225" not in refused
        assert "Connection refused" in refused

    def test_entfernt_den_datenbanknamen(self):
        redacted = redact_error('FATAL:  database "fastflow_prod" does not exist')
        assert "fastflow_prod" not in redacted
        assert "does not exist" in redacted

    def test_laesst_die_fehlerklasse_lesbar(self):
        """
        Redaction darf die Meldung nicht unbrauchbar machen: Die Exception-Klasse
        ist der erste Hinweis fuer den Operator und hat mit Infrastruktur nichts
        zu tun.
        """
        redacted = redact_error("(psycopg2.OperationalError) server closed the connection")
        assert "psycopg2.OperationalError" in redacted

    def test_kuerzt_lange_meldungen(self):
        redacted = redact_error("x" * 500)
        assert len(redacted) <= 200

    def test_laesst_nicht_string_werte_unangetastet(self):
        checks = redact_checks({"database": REAL_ERROR, "disk_free_gb": 12.5, "docker": "ok"})
        assert checks["disk_free_gb"] == 12.5
        assert checks["docker"] == "ok"
        assert "10.96.48.225" not in checks["database"]


class TestSystemStatusEndpoint:
    def test_ist_ohne_authentifizierung_erreichbar(self, client):
        response = client.get("/api/system/status")
        assert response.status_code == 200
        assert response.json()["status"] in ("ok", "degraded")

    def test_antwortet_immer_mit_200(self, client, monkeypatch):
        """
        Auch im Störungsfall 200 – nur so kann das Frontend "Backend meldet
        degraded" von "Backend gar nicht erreichbar" unterscheiden.
        """
        monkeypatch.setattr(
            "app.core.readiness._check_database", lambda: (False, REAL_ERROR)
        )
        _clear_status_cache()
        response = client.get("/api/system/status")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "degraded"
        assert "database" in body["failing"]

    def test_gibt_keine_infrastruktur_details_preis(self, client, monkeypatch):
        monkeypatch.setattr(
            "app.core.readiness._check_database", lambda: (False, REAL_ERROR)
        )
        _clear_status_cache()
        raw = client.get("/api/system/status").text
        assert "fastflow-db-rw.fastflow.svc" not in raw
        assert "10.96.48.225" not in raw
        assert "v-kubernet-fastflow" not in raw

    def test_meldet_sqlite_fallback(self, client, monkeypatch):
        monkeypatch.setattr("app.core.database.SQLITE_FALLBACK_ACTIVE", True)
        _clear_status_cache()
        body = client.get("/api/system/status").json()
        assert "sqlite_fallback" in body["failing"]
        assert body["status"] == "degraded"


class TestStatusAlter:
    """
    age_seconds ist die Grundlage dafuer, dass das Frontend eine gecachte
    Antwort von einer frischen unterscheiden kann. Ohne die Angabe blendet ein
    "ok" aus dem Cache die gerade erst gemeldete Stoerung wieder aus.
    """

    def test_frische_messung_ist_null_sekunden_alt(self, client):
        body = client.get("/api/system/status").json()
        assert body["age_seconds"] == 0.0

    def test_gecachte_antwort_weist_ihr_alter_aus(self, client, monkeypatch):
        import app.core.readiness as readiness

        # Erste Anfrage fuellt den Cache, die zweite wird daraus bedient.
        client.get("/api/system/status")
        calls: list[int] = []
        monkeypatch.setattr(
            readiness, "_build_public_status", lambda: calls.append(1) or {}
        )

        # Uhr vorstellen, ohne zu warten: 3s < TTL, der Cache bleibt gueltig.
        real_monotonic = readiness.time.monotonic
        monkeypatch.setattr(
            readiness.time, "monotonic", lambda: real_monotonic() + 3.0
        )

        body = client.get("/api/system/status").json()
        assert calls == [], "Antwort kam nicht aus dem Cache"
        assert body["age_seconds"] >= 3.0


class TestReadyRedaction:
    def test_ready_gibt_keine_rohen_verbindungsfehler_preis(self, client, monkeypatch):
        def broken_checks():
            return {"database": REAL_ERROR, "docker": "ok"}, False

        monkeypatch.setattr("app.core.readiness.run_readiness_checks", broken_checks)
        response = client.get("/api/ready")
        assert response.status_code == 503
        assert "10.96.48.225" not in response.text
        assert "v-kubernet-fastflow" not in response.text


class TestDatabaseUnavailableHandler:
    def test_verbindungsfehler_wird_zu_503_mit_error_code(
        self, authenticated_client, monkeypatch
    ):
        """
        Ein DB-Verbindungsfehler in einem beliebigen Endpoint muss als 503 mit
        maschinenlesbarem error_code ankommen, nicht als anonymer 500.
        """
        def explode(*_args, **_kwargs):
            raise OperationalError("SELECT 1", {}, Exception(REAL_ERROR))

        monkeypatch.setattr("app.core.readiness.run_readiness_checks", explode)

        response = authenticated_client.get("/api/settings/system-status")
        assert response.status_code == 503
        detail = response.json()["detail"]
        assert detail["error_code"] == "DATABASE_UNAVAILABLE"
        assert response.headers.get("Retry-After") == "15"

    def test_503_antwort_enthaelt_keine_zugangsdaten(
        self, authenticated_client, monkeypatch
    ):
        def explode(*_args, **_kwargs):
            raise OperationalError("SELECT 1", {}, Exception(REAL_ERROR))

        monkeypatch.setattr("app.core.readiness.run_readiness_checks", explode)
        raw = authenticated_client.get("/api/settings/system-status").text
        assert "v-kubernet-fastflow" not in raw
        assert "10.96.48.225" not in raw


def _clear_status_cache() -> None:
    """Der öffentliche Status ist gecacht; Tests müssen frisch messen."""
    import app.core.readiness as readiness
    readiness._public_status_cache = None


@pytest.fixture(autouse=True)
def _reset_status_cache():
    _clear_status_cache()
    yield
    _clear_status_cache()
