"""
Run-Env-Handling.

Kapselt, was von den Environment-Variablen eines Runs wie persistiert wird:

- interne ``_fastflow_*``-Metadaten (Fehlertyp, Retry-Zähler) im Klartext
- die Namen der injizierten Secrets im Klartext (Namen sind nicht geheim,
  erhalten aber den Audit-Wert: "welche deklarierten Secrets hat dieser Run
  bekommen?")
- die ad-hoc vom Aufrufer übergebenen Werte Fernet-verschlüsselt
- die Secret-Werte selbst: gar nicht

Hintergrund: ``PipelineRun.env_vars`` hat früher den vollständig gemergten
Env-Satz inklusive entschlüsselter Secrets gespeichert (siehe
``app/executor/core.py``). Damit lagen Klartext-Credentials in der Datenbank,
in Read-Replicas, in ``pg_dump``-Ausgaben und in Backups - was den kompletten
Fernet-Entwurf aushebelt: Der Master-Key schützt die ``secrets``-Tabelle und
``pipeline.json``, und dann gibt jede Run-Zeile den Klartext wieder heraus.

Secrets aus der Datenbank bzw. aus ``encrypted_env`` werden bewusst NICHT hier
abgelegt - die löst ``run_pipeline()`` beim Retry über die in ``pipeline.json``
deklarierte Allow-List neu auf. Das schließt zugleich einen Bypass: Ein Replay
des gespeicherten Env-Satzes landete in Precedence-Stufe 6 und überschrieb
damit die Allow-List aus Stufe 5.
"""

import json
import logging
from typing import Dict, Iterable, Optional

from app.services.secrets import decrypt, encrypt

logger = logging.getLogger(__name__)

# Präfix der internen Run-Metadaten, die in PipelineRun.env_vars im Klartext
# stehen dürfen (und von der API unmaskiert zurückgegeben werden).
RUN_METADATA_ENV_PREFIX = "_fastflow_"

# Namen (nicht Werte) der aus einer Secret-Quelle injizierten Env-Vars.
INJECTED_SECRET_KEYS_FIELD = f"{RUN_METADATA_ENV_PREFIX}injected_secret_keys"

# Namen (nicht Werte) aller Env-Vars, deren Wert nicht aus einer Secret-Quelle
# stammt: default_env aus pipeline.json/schedules und die ad-hoc Werte des
# Aufrufers. Erhält die Anzeige im UI, nachdem die Werte nicht mehr im Klartext
# an der Run-Zeile hängen.
PLAIN_ENV_KEYS_FIELD = f"{RUN_METADATA_ENV_PREFIX}env_keys"

# Von build_run_env_metadata() selbst gesetzte Felder. Werden aus der
# Aufrufer-Metadaten-Kopie ausgeschlossen, damit ein Aufrufer die Audit-Listen
# nicht fälschen kann.
_RESERVED_FIELDS = frozenset({PLAIN_ENV_KEYS_FIELD, INJECTED_SECRET_KEYS_FIELD})

# Platzhalter für Werte, die die API nicht ausliefert. Das Frontend erkennt
# Secrets daran (siehe kindOf() in frontend/src/components/RunEnvSection.tsx).
MASKED_VALUE = "***"


def is_run_metadata_key(key: str) -> bool:
    """True für interne ``_fastflow_*``-Metadaten-Keys."""
    return key.startswith(RUN_METADATA_ENV_PREFIX)


def encrypt_run_env_vars(env_vars: Optional[Dict[str, str]]) -> Optional[str]:
    """
    Verschlüsselt die ad-hoc vom Aufrufer übergebenen Env-Vars eines Runs.

    Nur diese Werte sind beim Retry nicht aus der Quelle rekonstruierbar (frei
    getippte Werte aus UI/API/Webhook), deshalb werden sie verschlüsselt
    mitgeführt. Interne ``_fastflow_*``-Metadaten werden ausgelassen - die
    stehen unverschlüsselt in ``PipelineRun.env_vars``.

    Returns:
        Fernet-Ciphertext oder None, wenn es nichts zu speichern gibt.
    """
    if not env_vars:
        return None
    payload = {k: v for k, v in env_vars.items() if not is_run_metadata_key(k)}
    if not payload:
        return None
    return encrypt(json.dumps(payload))


def decrypt_run_env_vars(cipher_text: Optional[str]) -> Dict[str, str]:
    """
    Entschlüsselt die ad-hoc Env-Vars eines Runs (Gegenstück zu
    :func:`encrypt_run_env_vars`).

    Fehlertolerant: Ist nichts gespeichert, wurde der Wert mit einem anderen
    ENCRYPTION_KEY verschlüsselt (Key-Rotation) oder ist das Format unerwartet,
    wird ein leeres Dict zurückgegeben. Ein Retry startet dann ohne die ad-hoc
    Werte, statt zu scheitern - dieselbe Fehlertoleranz wie bei
    ``encrypted_env`` in ``app/executor/core.py``.

    Fehlermeldungen enthalten bewusst keine Werte: ``_fastflow_error_message``
    wird von der API unmaskiert ausgeliefert (siehe ``_mask_env_vars`` in
    ``app/api/runs.py``).
    """
    if not cipher_text:
        return {}
    try:
        data = json.loads(decrypt(cipher_text))
    except ValueError as e:
        logger.warning("Ad-hoc Env-Vars eines Runs nicht entschlüsselbar: %s", e)
        return {}
    if not isinstance(data, dict):
        logger.warning(
            "Ad-hoc Env-Vars eines Runs haben unerwartetes Format: %s",
            type(data).__name__,
        )
        return {}
    return {str(k): str(v) for k, v in data.items()}


def build_run_env_metadata(
    caller_env_vars: Optional[Dict[str, str]],
    secret_keys: Optional[Iterable[str]] = None,
    plain_keys: Optional[Iterable[str]] = None,
) -> Dict[str, str]:
    """
    Baut den Klartext-Anteil von ``PipelineRun.env_vars``.

    Enthält ausschließlich:
    - die ``_fastflow_*``-Metadaten des Aufrufers (u. a. ``_fastflow_retry_count``
      und ``_fastflow_previous_run_id``, die die Retry-Kette zusammenhalten -
      gehen sie verloren, zählt der Retry-Zähler nie hoch)
    - die Namen der injizierten Secrets und der übrigen Env-Vars

    Die selbst gesetzten Audit-Felder werden aus der Aufrufer-Kopie
    ausgeschlossen: sonst könnte ein Aufrufer (UI, API, Webhook) per
    ``env_vars={"_fastflow_injected_secret_keys": "..."}`` eine Secret-Liste
    fälschen, die der Run nie erhalten hat.

    Args:
        caller_env_vars: Der ``env_vars``-Parameter von ``run_pipeline()``,
            also die ad-hoc Werte VOR dem Merge.
        secret_keys: Keys, deren Werte aus einer Secret-Quelle stammen
            (``encrypted_env`` oder ``secrets``-Tabelle via Allow-List).
        plain_keys: Keys aus nicht-geheimen Quellen (``default_env`` von
            Pipeline und Schedule). Nur die Namen, damit das UI dieselben
            Zeilen zeigt wie vor der Umstellung.

    Returns:
        Dict ohne jeden Secret-Wert.
    """
    caller_env_vars = caller_env_vars or {}
    metadata = {
        k: v
        for k, v in caller_env_vars.items()
        if is_run_metadata_key(k) and k not in _RESERVED_FIELDS
    }

    secret_names = set(secret_keys or ())
    # Secret-Keys gewinnen: ein Key kann in default_env stehen und von einem
    # Secret überschrieben werden (Merge-Stufen 3-5 nach 1-2).
    plain_names = {k for k in caller_env_vars if not is_run_metadata_key(k)}
    plain_names.update(plain_keys or ())
    plain_names -= secret_names

    if plain_names:
        metadata[PLAIN_ENV_KEYS_FIELD] = ",".join(sorted(plain_names))
    if secret_names:
        metadata[INJECTED_SECRET_KEYS_FIELD] = ",".join(sorted(secret_names))

    return metadata


def env_vars_for_display(env_vars: Optional[Dict[str, str]]) -> Dict[str, str]:
    """
    Baut die Anzeige-Sicht auf die Env-Vars eines Runs.

    Die Namenslisten aus :func:`build_run_env_metadata` werden wieder zu
    einzelnen Zeilen mit maskiertem Wert expandiert. Das UI zeigt damit
    dieselben Keys wie vor der Umstellung (Key + ``***``) - nur dass der
    Klartext diesmal nie gespeichert war. Die Werte waren auch vorher schon
    maskiert, es geht also keine Information verloren.

    Werte von Alt-Zeilen, die vor Migration 041 geschrieben wurden, werden
    maskiert statt ausgeliefert (Defense-in-Depth).
    """
    env_vars = env_vars or {}

    display: Dict[str, str] = {}
    for field in (PLAIN_ENV_KEYS_FIELD, INJECTED_SECRET_KEYS_FIELD):
        for name in (env_vars.get(field) or "").split(","):
            name = name.strip()
            if name:
                display[name] = MASKED_VALUE

    for key, value in env_vars.items():
        if key in _RESERVED_FIELDS:
            continue
        display[key] = value if is_run_metadata_key(key) else MASKED_VALUE

    return display


def scrub_persisted_env_vars(env_vars: Optional[Dict[str, str]]) -> Dict[str, str]:
    """
    Entfernt alle Nicht-Metadaten-Werte aus einem persistierten ``env_vars``-Dict.

    Wird für die Invariante genutzt, dass ``PipelineRun.env_vars`` keine
    Secret-Werte enthält. Die Alembic-Migration ``041`` führt dieselbe Logik
    bewusst als eigene Kopie (Migrationen sind historische Artefakte und dürfen
    sich nicht mit App-Code mitverändern).
    """
    if not env_vars:
        return {}
    return {k: v for k, v in env_vars.items() if is_run_metadata_key(k)}
