"""
Tests für den Schwachstellen-Scan (pip-audit).

Zwei Eigenschaften werden abgesichert:

1. Sicherheit: pip-audit läuft im Orchestrator, die Eingabe stammt aus dem
   Pipeline-Repository. Es darf keine Dependency-Resolution stattfinden, sonst
   lädt pip-audit Pakete und führt für sdists deren Build-Backend aus. Die
   Repo-Datei selbst darf dem Werkzeug gar nicht erst übergeben werden.
2. Korrektheit: die JSON-Ausgabe von pip-audit muss verstanden werden. Wird das
   Format nicht erkannt, meldet der Scan stillschweigend null Funde — schlimmer
   als kein Scan, weil es wie Sicherheit aussieht.
"""

import json
import subprocess
from pathlib import Path

import pytest

from app.core import dependencies as deps


def _write_pipeline(tmp_path: Path, requirements: str, lock: str | None = None) -> Path:
    pipeline_dir = tmp_path / "demo"
    pipeline_dir.mkdir(exist_ok=True)
    req = pipeline_dir / "requirements.txt"
    req.write_text(requirements, encoding="utf-8")
    if lock is not None:
        (pipeline_dir / "requirements.txt.lock").write_text(lock, encoding="utf-8")
    return req


class _RecordingRun:
    """Ersetzt subprocess.run und merkt sich den Aufruf."""

    def __init__(self, stdout: str = "", returncode: int = 0):
        self.stdout = stdout
        self.returncode = returncode
        self.calls: list[dict] = []

    def __call__(self, args, **kwargs):
        self.calls.append({"args": list(args), **kwargs})
        return subprocess.CompletedProcess(args, self.returncode, self.stdout, "")


# --------------------------------------------------------------------------- #
# Eingabe-Normalisierung
# --------------------------------------------------------------------------- #


def test_lock_file_provides_transitive_coverage(tmp_path):
    req = _write_pipeline(tmp_path, "requests\n", lock="requests==2.32.3\nurllib3==2.2.2\n")

    pinned, unaudited = deps.collect_pinned_requirements(req)

    assert pinned == ["requests==2.32.3", "urllib3==2.2.2"]
    assert unaudited == []


def test_without_lock_only_exact_pins_are_audited(tmp_path):
    req = _write_pipeline(tmp_path, "requests==2.32.3\npandas>=2.0\nnumpy\n")

    pinned, unaudited = deps.collect_pinned_requirements(req)

    assert pinned == ["requests==2.32.3"]
    assert unaudited == ["pandas", "numpy"]


def test_environment_markers_and_hashes_do_not_break_the_pin(tmp_path):
    req = _write_pipeline(
        tmp_path,
        'tomli==2.0.1 ; python_version < "3.11"\n'
        "certifi==2024.7.4 --hash=sha256:deadbeef\n",
    )

    pinned, _ = deps.collect_pinned_requirements(req)

    assert pinned == ["tomli==2.0.1", "certifi==2024.7.4"]


@pytest.mark.parametrize(
    "line",
    [
        "--index-url https://attacker.example/simple",
        "--extra-index-url https://attacker.example/simple",
        "--find-links /app/pipelines/demo/wheels",
        "-e .",
        "requests @ git+https://attacker.example/repo.git",
        "./local-package",
    ],
)
def test_pip_options_and_source_references_never_reach_the_audit(tmp_path, line):
    """
    Die Eingabedatei wird selbst erzeugt. Alles, was pip-audit zu einem Download
    oder Build bewegen könnte, fällt dabei heraus.
    """
    req = _write_pipeline(tmp_path, f"{line}\nrequests==2.32.3\n")

    pinned, _ = deps.collect_pinned_requirements(req)

    assert pinned == ["requests==2.32.3"]


# --------------------------------------------------------------------------- #
# Subprozess-Aufruf
# --------------------------------------------------------------------------- #


def test_audit_runs_without_dependency_resolution(tmp_path, monkeypatch):
    req = _write_pipeline(tmp_path, "requests==2.32.3\n")
    recorder = _RecordingRun(stdout=json.dumps({"dependencies": []}))
    monkeypatch.setattr(deps.subprocess, "run", recorder)

    deps._run_pip_audit_sync(req)

    args = recorder.calls[0]["args"]
    assert "--no-deps" in args, "ohne --no-deps lädt und baut pip-audit fremde Pakete"
    assert "--disable-pip" in args


def test_audit_never_receives_the_repository_file(tmp_path, monkeypatch):
    req = _write_pipeline(tmp_path, "requests==2.32.3\n")
    recorder = _RecordingRun(stdout=json.dumps({"dependencies": []}))
    monkeypatch.setattr(deps.subprocess, "run", recorder)

    deps._run_pip_audit_sync(req)

    call = recorder.calls[0]
    passed_path = Path(call["args"][call["args"].index("-r") + 1])
    assert passed_path != req
    assert req.parent not in passed_path.parents, "Eingabe muss ausserhalb des Repos liegen"
    # Auch das Arbeitsverzeichnis darf nicht im Pipeline-Verzeichnis liegen:
    # sonst zieht pip-audit dort liegende Konfiguration heran.
    assert Path(call["cwd"]) != req.parent


def test_audit_input_contains_only_normalized_pins(tmp_path, monkeypatch):
    req = _write_pipeline(tmp_path, "--index-url https://attacker.example\nrequests==2.32.3\n")
    written: dict[str, str] = {}

    def capture(args, **kwargs):
        audit_input = Path(args[args.index("-r") + 1])
        written["content"] = audit_input.read_text(encoding="utf-8")
        return subprocess.CompletedProcess(args, 0, json.dumps({"dependencies": []}), "")

    monkeypatch.setattr(deps.subprocess, "run", capture)
    deps._run_pip_audit_sync(req)

    assert written["content"].strip() == "requests==2.32.3"


def test_no_subprocess_when_nothing_is_pinned(tmp_path, monkeypatch):
    req = _write_pipeline(tmp_path, "requests\npandas>=2.0\n")

    def fail(*args, **kwargs):  # pragma: no cover - darf nicht aufgerufen werden
        raise AssertionError("pip-audit darf ohne gepinnte Pakete nicht starten")

    monkeypatch.setattr(deps.subprocess, "run", fail)
    result = deps._run_pip_audit_sync(req)

    assert result.vulnerabilities == []
    assert result.error is None
    assert result.unaudited == ["requests", "pandas"]


def test_unaudited_packages_are_reported_alongside_findings(tmp_path, monkeypatch):
    req = _write_pipeline(tmp_path, "requests==2.32.3\nnumpy\n")
    monkeypatch.setattr(
        deps.subprocess, "run", _RecordingRun(stdout=json.dumps({"dependencies": []}))
    )

    result = deps._run_pip_audit_sync(req)

    assert result.unaudited == ["numpy"]


# --------------------------------------------------------------------------- #
# Parsing der pip-audit-Ausgabe
# --------------------------------------------------------------------------- #


def test_parses_current_pip_audit_format():
    """Format von pip-audit 2.x: {"dependencies": [{..., "vulns": [...]}]}."""
    payload = {
        "dependencies": [
            {
                "name": "jinja2",
                "version": "3.1.2",
                "vulns": [{"id": "PYSEC-2026-1473", "fix_versions": ["3.1.3"]}],
            },
            {"name": "idna", "version": "3.7", "vulns": []},
        ],
        "fixes": [],
    }

    vulns = deps._extract_vulnerabilities(payload)

    assert len(vulns) == 1
    assert vulns[0]["id"] == "PYSEC-2026-1473"
    assert vulns[0]["name"] == "jinja2"
    assert vulns[0]["version"] == "3.1.2"


def test_parses_legacy_top_level_format():
    payload = {"vulnerabilities": [{"id": "CVE-2020-1", "name": "foo"}]}

    assert deps._extract_vulnerabilities(payload) == [{"id": "CVE-2020-1", "name": "foo"}]


def test_parses_legacy_keyed_format():
    payload = {"foo==1.0": [{"id": "CVE-2020-2"}]}

    vulns = deps._extract_vulnerabilities(payload)

    assert vulns == [{"id": "CVE-2020-2", "name": "foo", "version": "1.0"}]


def test_fixes_key_is_not_mistaken_for_vulnerabilities():
    payload = {"dependencies": [], "fixes": [{"name": "foo", "version": "1.1"}]}

    assert deps._extract_vulnerabilities(payload) == []


def test_malformed_output_yields_no_findings():
    assert deps._extract_vulnerabilities(None) == []
    assert deps._extract_vulnerabilities([]) == []
    assert deps._extract_vulnerabilities({"dependencies": "nonsense"}) == []


def test_unexpected_exit_code_is_reported_as_error(tmp_path, monkeypatch):
    req = _write_pipeline(tmp_path, "requests==2.32.3\n")
    monkeypatch.setattr(deps.subprocess, "run", _RecordingRun(stdout="", returncode=2))

    result = deps._run_pip_audit_sync(req)

    assert result.error is not None
    assert "exited with 2" in result.error
