"""
Thread-Pools für blockierende Executor-Aufrufe.

Das Docker-SDK ist synchron: jeder API-Call belegt den aufrufenden Thread, bis er
zurückkehrt. Der Orchestrator lagert diese Calls deshalb in Thread-Pools aus.
Entscheidend ist die Trennung nach Blockierdauer — mit einem gemeinsamen Pool
verhungern die kurzen Calls hinter den langen:

``stream_pool``
    Aufrufe ohne verlässliche Obergrenze, die einem einzelnen Run zuzurechnen
    sind. Dauerhaft belegt sind pro laufendem Run drei Worker:
    ``next(container.logs(follow=True))``, ``next(container.stats(stream=True))``
    und ``container.wait()``. Dazu kommen die unbegrenzten Calls beim Start
    desselben Runs — ``ensure_python_version`` (kann ``uv python install``
    auslösen) und ``containers.run`` (docker-py zieht bei ``ImageNotFound``
    selbsttätig das Image). Sie laufen, bevor die drei Streams starten, und
    passen deshalb ins Budget des Runs. Der Pool skaliert mit
    ``MAX_CONCURRENT_RUNS``.

``control_pool``
    Calls, deren Dauer nach oben begrenzt ist: ``stop``, ``kill``, ``remove``,
    ``reload``, ``logs(tail=…)``, ``exec_run``, ``containers.list``. Sie
    gehören nicht zu einem einzelnen Run, sondern müssen auch dann noch
    durchkommen, wenn alle Runs laufen.

Warum getrennt: In einem gemeinsamen Pool ist ab ``max_workers / 3`` parallelen
Runs kein Worker mehr frei. ``client.containers.run()`` bekommt dann keinen
Worker — der nächste Run startet stillschweigend nicht. Schlimmer noch hängen
``cancel_run()`` und die Zombie-Reconciliation, also genau die Operationen, die
man in dieser Situation braucht. Der Control-Pool hat daher Kapazität, die von
den Streams nicht belegt werden kann; im Gegenzug darf dort nichts landen, was
unbegrenzt blockieren kann.

Warum das nicht verklemmen kann: Ein Stream-Worker wird frei, sobald der Docker-
Stream EOF liefert — also sobald der Container beendet oder entfernt ist. Beides
läuft über den Control-Pool. Die Abhängigkeitskette zeigt damit immer nur vom
Stream- in den Control-Pool, nie zurück; selbst ein voller Stream-Pool löst sich
also wieder auf, statt sich selbst zu blockieren.

Die Formel aus ``MAX_CONCURRENT_RUNS`` ist eine Untergrenze, keine Obergrenze:
Überschreitet die tatsächliche Nachfrage sie, wächst der Pool mit (bis
``MAX_POOL_WORKERS``) und meldet das. Das deckt die Fälle ab, die sich aus
``MAX_CONCURRENT_RUNS`` nicht herleiten lassen — Re-Attach nach Crash-Recovery
läuft ohne Concurrency-Check (``reconcile_zombie_containers``), Streams eines
beendeten Runs laufen noch nach, und bei ``PIPELINE_EXECUTOR=kubernetes``
bedeutet 0 "unbegrenzt". Ohne Mitwachsen würde in genau diesen Fällen wieder
still gewartet.

Abbruch-Semantik: Wird das Await abgebrochen (z. B. durch ``asyncio.wait_for``),
bricht nur das Future ab — der Thread läuft weiter, bis der Call zurückkehrt.
Die Auslastungszählung bildet das ab (siehe :meth:`BlockingCallPool.run`), damit
ein solcher Worker-Leak in den Logs sichtbar wird statt still die Kapazität zu
fressen.
"""

import asyncio
import logging
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable, Dict, Optional, TypeVar

from app.core.config import config

logger = logging.getLogger(__name__)

T = TypeVar("T")

#: Dauerhaft blockierende Calls pro laufendem Run: Log-Stream, Stats-Stream, ``wait()``.
BLOCKING_CALLS_PER_RUN = 3

#: Reserve im Stream-Pool für Runs im Auf- oder Abbau: Re-Attach nach
#: Crash-Recovery, noch nicht abgeräumte Streams eines beendeten Runs,
#: ``ensure_python_version`` eines gerade startenden Runs.
STREAM_POOL_HEADROOM = 4

#: Untergrenze für den Control-Pool. Darüber skaliert er mit
#: ``MAX_CONCURRENT_RUNS``: am Ende eines Runs fallen mehrere Control-Calls an
#: (``logs(tail=…)``, ``remove``), und ``stop`` blockiert bis zu seinem
#: Stop-Timeout plus dem Client-Timeout von docker-py.
CONTROL_POOL_MIN_WORKERS = 8

#: Reserve im Control-Pool über ``MAX_CONCURRENT_RUNS`` hinaus, damit Abbrechen
#: und Reconciliation auch dann Worker finden, wenn alle Runs gleichzeitig
#: aufräumen.
CONTROL_POOL_HEADROOM = 4

#: Fallback, wenn ``MAX_CONCURRENT_RUNS`` nicht gesetzt oder <= 0 ist — bei
#: ``PIPELINE_EXECUTOR=kubernetes`` bedeutet 0 "unbegrenzt".
DEFAULT_CONCURRENT_RUNS = 10

#: Harte Obergrenze je Pool, damit eine versehentlich sehr hohe
#: ``MAX_CONCURRENT_RUNS``-Einstellung nicht tausende Threads erzeugt.
MAX_POOL_WORKERS = 512

#: Mindestabstand zwischen zwei Sättigungs-Warnungen desselben Pools.
SATURATION_LOG_INTERVAL_SECONDS = 60.0


class BlockingCallPool:
    """Thread-Pool für blockierende Aufrufe, der bei Bedarf mitwächst.

    Der Pool wird beim ersten Aufruf erzeugt, nicht beim Import: ``config`` wird
    beim App-Start aus der DB überschrieben (Settings-UI) und ist auch zur
    Laufzeit änderbar. Die Kapazität wird deshalb vor jeder Submission neu
    ausgewertet.

    Gewachsen wird aus zwei Gründen: weil die konfigurierte Kapazität steigt,
    oder weil mehr Calls gleichzeitig laufen als der Pool Worker hat. Der zweite
    Fall ist die Absicherung gegen alles, was sich aus ``MAX_CONCURRENT_RUNS``
    nicht herleiten lässt; er verdoppelt die Grösse, damit nicht bei jedem
    weiteren Call ein neuer Pool entsteht.

    Der Pool schrumpft nie: laufende Streams halten ihren Worker bis zum Ende
    des jeweiligen Runs, ein Verkleinern würde sie abschneiden. Beim Wachsen
    wird ein neuer Pool angelegt und der alte mit ``wait=False``
    heruntergefahren; er arbeitet seine laufenden und eingereihten Calls noch ab
    und beendet seine Threads danach selbst.

    Sperren: ``_pool_lock`` schützt den Pool selbst, ``_state_lock`` die Zähler.
    Getrennt, weil ``_state_lock`` aus den Done-Callbacks genommen wird — also
    aus Threads, die dabei bereits das interne Lock des ``ThreadPoolExecutor``
    halten. Läge beides auf einer Sperre, stünden ``submit`` und ``shutdown`` in
    umgekehrter Sperrreihenfolge zueinander.
    """

    def __init__(self, name: str, capacity: Callable[[], int]) -> None:
        self._name = name
        self._capacity = capacity
        self._pool_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._pool: Optional[ThreadPoolExecutor] = None
        self._max_workers = 0
        self._in_flight = 0
        self._last_saturation_log = 0.0
        self._was_shut_down = False

    @property
    def name(self) -> str:
        return self._name

    async def run(self, fn: Callable[..., T], *args: Any) -> T:
        """
        Führt ``fn`` im Pool aus und wartet asynchron auf das Ergebnis.

        Wird das Await abgebrochen, bricht nur das Future ab; der Thread läuft
        weiter. Der Worker gilt deshalb erst als frei, wenn ``fn`` tatsächlich
        zurückgekehrt ist — nicht schon, wenn niemand mehr auf das Ergebnis
        wartet.
        """
        loop = asyncio.get_running_loop()
        return await asyncio.wrap_future(self.submit(fn, *args), loop=loop)

    def submit(self, fn: Callable[..., T], *args: Any) -> "Future[T]":
        """Reicht ``fn`` in den Pool ein und gibt das ``concurrent.futures``-Future zurück."""
        with self._state_lock:
            self._in_flight += 1
            in_flight = self._in_flight
        try:
            # Unter ``_pool_lock``, damit kein Call in einen Pool gerät, der im
            # selben Moment ersetzt oder heruntergefahren wird.
            with self._pool_lock:
                pool = self._ensure_pool_locked(in_flight)
                max_workers = self._max_workers
                future = pool.submit(fn, *args)
        except BaseException:
            with self._state_lock:
                self._in_flight -= 1
            raise
        # Ausserhalb der Sperren: bei einem bereits fertigen Future läuft der
        # Callback sofort im aufrufenden Thread und nimmt sich ``_state_lock``.
        future.add_done_callback(self._on_call_done)
        if in_flight > max_workers:
            self._log_saturation(in_flight, max_workers)
        return future

    def stats(self) -> Dict[str, int]:
        """Momentaufnahme der Auslastung (Diagnose/Logging)."""
        with self._state_lock:
            in_flight = self._in_flight
        with self._pool_lock:
            max_workers = self._max_workers
        return {"max_workers": max_workers, "in_flight": in_flight}

    def shutdown(self) -> None:
        """
        Fährt den Pool herunter, ohne auf blockierende Calls zu warten.

        Laufende Stream-Reads lassen sich nicht abbrechen; auf sie zu warten
        würde den Shutdown blockieren, bis der letzte Container beendet ist.
        Noch nicht gestartete Calls werden verworfen.

        Ein danach eintreffender Call legt den Pool neu an, statt zu scheitern:
        Nachzügler während des Shutdowns sollen nicht mit einem RuntimeError
        durch die Fehlerbehandlung laufen. Weil ein neuer Pool den Prozess-Exit
        wieder aufhalten kann, wird das als Warnung protokolliert.
        """
        with self._pool_lock:
            pool, self._pool = self._pool, None
            self._max_workers = 0
            self._was_shut_down = True
        if pool is not None:
            # Ausserhalb von ``_pool_lock``: cancel_futures löst die
            # Done-Callbacks der verworfenen Calls aus, die ``_state_lock``
            # nehmen — nie ``_pool_lock``.
            pool.shutdown(wait=False, cancel_futures=True)
            logger.debug("Thread-Pool '%s' heruntergefahren", self._name)

    # --- intern --------------------------------------------------------------

    def _ensure_pool_locked(self, in_flight: int) -> ThreadPoolExecutor:
        """
        Erzeugt oder vergrössert den Pool. Erwartet ``self._pool_lock``.

        ``in_flight`` schliesst den gerade einzureichenden Call ein: Nachfrage
        über der konfigurierten Kapazität lässt den Pool mitwachsen, statt den
        Call stillschweigend in die Queue zu legen.
        """
        requested = self._requested_capacity()
        configured = min(requested, MAX_POOL_WORKERS)
        if self._pool is not None and (
            self._max_workers >= max(configured, in_flight)
            # Am Limit nicht weiter wachsen – sonst entstünde pro Call ein
            # neuer Pool, sobald die Nachfrage MAX_POOL_WORKERS übersteigt.
            or self._max_workers >= MAX_POOL_WORKERS
        ):
            return self._pool

        if requested > MAX_POOL_WORKERS:
            logger.warning(
                "Thread-Pool '%s': benötigte Kapazität %d überschreitet das Limit von %d "
                "Workern und wird gekappt. Bei so vielen parallelen Runs MAX_CONCURRENT_RUNS "
                "senken oder die Last auf mehrere Orchestrator-Instanzen verteilen.",
                self._name, requested, MAX_POOL_WORKERS,
            )

        wanted, reason = self._growth_target(configured, in_flight)
        previous = self._pool
        self._pool = ThreadPoolExecutor(
            max_workers=wanted,
            thread_name_prefix=f"fastflow-{self._name}",
        )
        self._max_workers = wanted
        if previous is None:
            logger.info("Thread-Pool '%s' gestartet (max_workers=%d)", self._name, wanted)
        else:
            logger.info(
                "Thread-Pool '%s' auf max_workers=%d vergrössert (%s)",
                self._name, wanted, reason,
            )
            # Ohne cancel_futures: der alte Pool arbeitet laufende und bereits
            # eingereihte Calls zu Ende und beendet seine Threads danach selbst.
            # (cancel_futures wäre hier ein Deadlock – die Done-Callbacks der
            # verworfenen Calls bräuchten ``_state_lock``, und dieser Thread
            # hält währenddessen das interne Lock des Executors.)
            previous.shutdown(wait=False)
        if self._was_shut_down:
            self._was_shut_down = False
            logger.warning(
                "Thread-Pool '%s' wurde nach dem Shutdown neu angelegt – ein "
                "blockierender Call kann jetzt das Beenden des Prozesses verzögern",
                self._name,
            )
        return self._pool

    def _growth_target(self, configured: int, in_flight: int) -> "tuple[int, str]":
        """Zielgrösse und Begründung fürs Log. Erwartet ``self._pool_lock``."""
        if in_flight <= configured:
            return configured, "konfigurierte Kapazität gestiegen"
        if configured >= MAX_POOL_WORKERS:
            return MAX_POOL_WORKERS, "Limit erreicht"
        # Verdoppeln statt +1, damit nicht jeder weitere Call einen neuen Pool
        # erzeugt; die alten Pools halten ihre Threads bis zum Ende ihrer Calls.
        wanted = min(MAX_POOL_WORKERS, max(in_flight, self._max_workers * 2, configured))
        logger.warning(
            "Thread-Pool '%s': %d gleichzeitige Calls über der konfigurierten Kapazität "
            "von %d – Pool wächst auf %d. Erwartet werden %d Calls je laufendem Run; "
            "mehr deutet auf nicht freigegebene Worker oder Runs ausserhalb von "
            "MAX_CONCURRENT_RUNS hin (z. B. Re-Attach nach Crash-Recovery).",
            self._name, in_flight, configured, wanted, BLOCKING_CALLS_PER_RUN,
        )
        return wanted, "Nachfrage über der konfigurierten Kapazität"

    def _requested_capacity(self) -> int:
        try:
            requested = int(self._capacity())
        except (TypeError, ValueError):
            logger.warning(
                "Thread-Pool '%s': Kapazität nicht ermittelbar, nutze Default", self._name
            )
            requested = BLOCKING_CALLS_PER_RUN * DEFAULT_CONCURRENT_RUNS + STREAM_POOL_HEADROOM
        return max(1, requested)

    def _on_call_done(self, _future: "Future[Any]") -> None:
        with self._state_lock:
            self._in_flight -= 1

    def _log_saturation(self, in_flight: int, max_workers: int) -> None:
        now = time.monotonic()
        with self._state_lock:
            if now - self._last_saturation_log < SATURATION_LOG_INTERVAL_SECONDS:
                return
            self._last_saturation_log = now
        logger.warning(
            "Thread-Pool '%s' ist ausgelastet: %d laufende Calls bei %d Workern. "
            "Weitere Calls warten in der Queue — bei anhaltender Sättigung "
            "MAX_CONCURRENT_RUNS prüfen.",
            self._name, in_flight, max_workers,
        )


def _configured_concurrent_runs() -> int:
    """``MAX_CONCURRENT_RUNS`` als positive Zahl; 0/None/ungültig → Default."""
    try:
        configured = int(getattr(config, "MAX_CONCURRENT_RUNS", None))
    except (TypeError, ValueError):
        return DEFAULT_CONCURRENT_RUNS
    return configured if configured > 0 else DEFAULT_CONCURRENT_RUNS


def _stream_pool_capacity() -> int:
    return BLOCKING_CALLS_PER_RUN * _configured_concurrent_runs() + STREAM_POOL_HEADROOM


def _control_pool_capacity() -> int:
    return max(CONTROL_POOL_MIN_WORKERS, _configured_concurrent_runs() + CONTROL_POOL_HEADROOM)


#: Pool für Calls, die über die Laufzeit eines Runs blockieren (Streams, ``wait()``).
stream_pool = BlockingCallPool("stream", _stream_pool_capacity)

#: Pool für kurze Docker-Control-Calls. Muss auch dann noch Worker haben, wenn
#: alle Runs laufen — sonst lässt sich nichts mehr abbrechen oder aufräumen.
control_pool = BlockingCallPool("control", _control_pool_capacity)

_ALL_POOLS = (stream_pool, control_pool)


def shutdown_thread_pools() -> None:
    """Fährt beide Pools herunter (App-Shutdown)."""
    for pool in _ALL_POOLS:
        pool.shutdown()


def thread_pool_stats() -> Dict[str, Dict[str, int]]:
    """Auslastung beider Pools, z. B. für Health-/Diagnose-Ausgaben."""
    return {pool.name: pool.stats() for pool in _ALL_POOLS}
