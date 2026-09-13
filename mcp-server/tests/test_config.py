"""Tests für das Laden der Konfiguration.

Fehlkonfiguration soll beim Start scheitern, mit einer Meldung, die sagt was zu
tun ist – nicht später an unklaren Tool-Fehlern.
"""

import pytest

from fastflow_mcp.config import Config, ConfigError, load_config

VALID_TOKEN = "ffp_abcd1234_" + "x" * 43


def env(**overrides) -> dict[str, str]:
    base = {"FASTFLOW_URL": "https://fastflow.example.com", "FASTFLOW_TOKEN": VALID_TOKEN}
    base.update({k: v for k, v in overrides.items() if v is not None})
    for key, value in overrides.items():
        if value is None:
            base.pop(key, None)
    return base


def test_minimal_configuration():
    config = load_config(env())

    assert config.base_url == "https://fastflow.example.com"
    assert config.api_url == "https://fastflow.example.com/api"
    assert config.redact_secrets is True
    assert config.verify_tls is True


def test_trailing_slash_is_stripped():
    config = load_config(env(FASTFLOW_URL="https://fastflow.example.com/"))

    assert config.api_url == "https://fastflow.example.com/api"


@pytest.mark.parametrize("missing", ["FASTFLOW_URL", "FASTFLOW_TOKEN"])
def test_missing_required_values_name_the_variable(missing):
    with pytest.raises(ConfigError) as exc:
        load_config(env(**{missing: None}))

    assert missing in str(exc.value)


@pytest.mark.parametrize("url", ["fastflow.example.com", "ftp://host", "  "])
def test_unusable_url_is_rejected(url):
    with pytest.raises(ConfigError) as exc:
        load_config(env(FASTFLOW_URL=url))

    assert "FASTFLOW_URL" in str(exc.value)


def test_session_jwt_is_rejected_with_an_explanation():
    """Ein Browser-Token läuft nach Stunden ab und taugt nicht für Dauerbetrieb."""
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.signature"

    with pytest.raises(ConfigError) as exc:
        load_config(env(FASTFLOW_TOKEN=jwt))

    message = str(exc.value)
    assert "ffp_" in message
    assert "API-Tokens" in message


def test_timeout_bounds_are_enforced():
    assert load_config(env(FASTFLOW_TIMEOUT_SECONDS="60")).timeout_seconds == 60.0

    for bad in ("0.1", "1000", "abc"):
        with pytest.raises(ConfigError):
            load_config(env(FASTFLOW_TIMEOUT_SECONDS=bad))


@pytest.mark.parametrize("raw,expected", [("0", False), ("false", False), ("no", False),
                                          ("1", True), ("true", True), ("on", True)])
def test_boolean_switches(raw, expected):
    assert load_config(env(FASTFLOW_REDACT_SECRETS=raw)).redact_secrets is expected
    assert load_config(env(FASTFLOW_VERIFY_TLS=raw)).verify_tls is expected


def test_repr_masks_the_token():
    """Ein Traceback darf das Token nicht mitliefern."""
    config = Config(base_url="https://x", token=VALID_TOKEN)

    text = repr(config)
    assert VALID_TOKEN not in text
    # Sichtbar maskiert, nicht weggelassen – sonst liest sich das wie "nicht gesetzt".
    assert "token='***'" in text
