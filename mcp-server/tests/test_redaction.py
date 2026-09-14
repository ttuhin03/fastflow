"""Tests für die Maskierung von Zugangsdaten.

Der Filter ist bewusst als unvollständig dokumentiert. Die Tests halten
deshalb beides fest: was er erkennt **und** was er nachweislich nicht
erkennt – damit niemand ihn später für vollständig hält.
"""

import pytest

from fastflow_mcp.redaction import PLACEHOLDER, redact, redact_if

FASTFLOW_TOKEN = "ffp_abcd1234_" + "x" * 43


@pytest.mark.parametrize(
    "secret",
    [
        FASTFLOW_TOKEN,
        "ghp_" + "a" * 36,
        "gho_" + "b" * 36,
        "github_pat_" + "c" * 30,
        "AKIAIOSFODNN7EXAMPLE",
        "ASIAIOSFODNN7EXAMPLE",
        "xoxb-123456789012-abcdefghijkl",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ0ZXN0In0.c2lnbmF0dXJlX2hlcmU",
    ],
)
def test_known_secret_shapes_are_removed(secret):
    text = f"vorher {secret} nachher"
    result = redact(text)

    assert secret not in result
    assert PLACEHOLDER in result
    # Der umgebende Kontext bleibt lesbar – sonst verliert der Agent die Stelle.
    assert result.startswith("vorher ")
    assert result.endswith(" nachher")


def test_private_key_block_is_removed_entirely():
    text = (
        "config:\n"
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "MIIEowIBAAKCAQEA1234567890\nabcdefghij\n"
        "-----END RSA PRIVATE KEY-----\n"
        "done"
    )
    result = redact(text)

    assert "MIIEowIBAAKCAQEA" not in result
    assert "abcdefghij" not in result
    assert "BEGIN RSA PRIVATE KEY" not in result
    assert result.startswith("config:\n")
    assert result.endswith("done")


@pytest.mark.parametrize(
    "line,expected",
    [
        ("password=hunter2", f"password={PLACEHOLDER}"),
        ("PASSWORD = hunter2", f"PASSWORD = {PLACEHOLDER}"),
        # Anführungszeichen bleiben stehen, damit die Zeile gültiges JSON bleibt.
        ('"api_key": "abcdef123456"', f'"api_key": "{PLACEHOLDER}"'),
        ("client_secret: s3cr3tvalue", f"client_secret: {PLACEHOLDER}"),
    ],
)
def test_credential_assignments_keep_their_label(line, expected):
    """Der Schlüssel bleibt sichtbar, nur der Wert verschwindet.

    ``password=[redacted]`` sagt dem Agenten, *dass* dort etwas stand –
    ein blankes ``[redacted]`` verliert diese Information.
    """
    assert redact(line) == expected


def test_aws_secret_key_is_caught_by_the_access_key_label():
    """Der AWS Secret Key hat keine erkennbare Form – nur sein Label verrät ihn.

    Gefunden wird hier ``ACCESS_KEY=``; ``SECRET`` allein greift nicht, weil
    darauf kein Zuweisungszeichen folgt.
    """
    result = redact("AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCY")

    assert "wJalrXUtnFEMI" not in result
    assert result.startswith("AWS_SECRET_ACCESS_KEY=")
    assert result.endswith(PLACEHOLDER)


def test_url_credentials_keep_host_and_user():
    result = redact("clone https://deploy:s3cret@github.com/org/repo.git")

    assert "s3cret" not in result
    assert "https://deploy:" in result
    assert "@github.com/org/repo.git" in result


def test_ordinary_log_output_is_untouched():
    text = (
        "2026-09-13 10:00:00 INFO Pipeline gestartet\n"
        "Verarbeite 1234 Zeilen aus orders.csv\n"
        "Traceback (most recent call last):\n"
        '  File "main.py", line 42, in run\n'
        "ValueError: unerwarteter Spaltentyp in Zeile 7\n"
    )

    assert redact(text) == text


def test_documented_blind_spot_password_in_prose():
    """Festgehalten, weil die Doku es zusagt: Fließtext wird nicht erkannt.

    Schlägt dieser Test eines Tages fehl, weil ein neues Muster greift, ist
    das eine Verbesserung – dann gehört die Dokumentation angepasst, nicht
    der Test gelöscht.
    """
    text = "login failed for user admin with password hunter2"

    assert redact(text) == text


@pytest.mark.parametrize("value", ["", None])
def test_empty_input_normalises_to_empty_string(value):
    assert redact(value) == ""


def test_redact_if_respects_the_switch():
    assert redact_if(FASTFLOW_TOKEN, enabled=False) == FASTFLOW_TOKEN
    assert FASTFLOW_TOKEN not in redact_if(FASTFLOW_TOKEN, enabled=True)
