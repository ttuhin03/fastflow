"""
Notebook Runner for Fast-Flow.

Läuft im Pipeline-Container und führt main.ipynb mit nbclient aus.
- Cell-Level-Retry: pipeline.json "cells"[code_cell_index] mit retries, delay_seconds.
  Zellen-Metadaten (fastflow in der Zelle) überschreiben die Werte für diese Zelle.
- Emittiert strukturierte Log-Zeilen (FASTFLOW_CELL_*) für den Orchestrator.
- Erfordert: nbclient, nbformat, ipykernel in der Pipeline-requirements.txt.
"""

import json
import sys
import time
import base64
from pathlib import Path

# Protokoll-Präfixe für Orchestrator-Parsing
PREFIX_CELL_START = "FASTFLOW_CELL_START\t"
PREFIX_CELL_END = "FASTFLOW_CELL_END\t"
PREFIX_CELL_OUTPUT = "FASTFLOW_CELL_OUTPUT\t"
SETUP_READY_MARKER = "FASTFLOW_SETUP_READY"


def emit(line: str) -> None:
    """Eine Zeile auf stdout ausgeben (wird vom Orchestrator gelesen)."""
    print(line, flush=True)


def _load_pipeline_cells(pipeline_json_path: Path) -> list:
    """Liest pipeline.json und gibt die 'cells'-Liste zurück (leer wenn fehlt)."""
    if not pipeline_json_path.exists() or not pipeline_json_path.is_file():
        return []
    try:
        with open(pipeline_json_path, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("cells") if isinstance(data.get("cells"), list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _cell_retry_config(
    code_cell_index: int,
    pipeline_cells: list,
    cell_fastflow: dict,
) -> tuple[int, float]:
    """
    Kombiniert pipeline.json-Zellen-Config mit Zellen-Metadaten.
    Zellen-Metadaten (fastflow) überschreiben die pipeline.json für diese Zelle.
    Returns: (max_retries, delay_seconds)
    """
    base = (
        pipeline_cells[code_cell_index]
        if code_cell_index < len(pipeline_cells) and isinstance(pipeline_cells[code_cell_index], dict)
        else {}
    )
    cell = cell_fastflow or {}
    max_retries = (
        int(cell["retries"])
        if "retries" in cell
        else int(base.get("retries", 0))
    )
    delay_seconds = (
        float(cell["delay_seconds"])
        if "delay_seconds" in cell
        else float(base.get("delay_seconds", 1))
    )
    return max_retries, delay_seconds


def run_notebook(notebook_path: str) -> int:
    """
    Führt das Notebook aus. Gibt 0 bei Erfolg zurück, sonst 1.
    """
    import nbformat
    from nbclient import NotebookClient

    path = Path(notebook_path)
    if not path.exists() or not path.is_file():
        print(f"Notebook nicht gefunden: {notebook_path}", file=sys.stderr)
        return 1

    nb = nbformat.read(path, as_version=4)
    client = NotebookClient(nb)
    pipeline_cells = _load_pipeline_cells(path.parent / "pipeline.json")

    with client.setup_kernel():
        emit(SETUP_READY_MARKER)
        execution_count = 0
        code_cell_index = -1

        for cell_index, cell in enumerate(nb.cells):
            if cell.cell_type != "code":
                continue
            code_cell_index += 1
            ff_config = cell.metadata.get("fastflow", {}) or {}
            max_retries, delay_seconds = _cell_retry_config(
                code_cell_index, pipeline_cells, ff_config
            )

            emit(PREFIX_CELL_START + str(code_cell_index))
            attempt = 0
            last_error = None

            while attempt <= max_retries:
                try:
                    execution_count += 1
                    client.execute_cell(cell, cell_index, execution_count=execution_count)
                    break
                except Exception as e:
                    # CellExecutionError, CellTimeoutError, DeadKernelError, etc.
                    last_error = e
                    attempt += 1
                    emit(
                        PREFIX_CELL_END
                        + str(code_cell_index)
                        + "\tRETRYING\t"
                        + str(attempt)
                        + "\t"
                        + (str(e)[:500].replace("\t", " "))
                    )
                    if attempt > max_retries:
                        emit(PREFIX_CELL_END + str(code_cell_index) + "\tFAILED")
                        if last_error:
                            print(last_error, file=sys.stderr)
                        return 1
                    if delay_seconds > 0:
                        time.sleep(delay_seconds)

            emit(PREFIX_CELL_END + str(code_cell_index) + "\tSUCCESS")

            # Zellen-Ausgaben emittieren (stdout, stderr, Bilder)
            for out in getattr(cell, "outputs", []) or []:
                ot = out.get("output_type")
                if ot == "stream":
                    name = out.get("name", "stdout")
                    text = out.get("text", "")
                    if isinstance(text, list):
                        text = "".join(text)
                    for line in (text or "").splitlines():
                        # Tabs in Payload escapen oder als Base64 senden
                        payload = line.replace("\t", "\\t")
                        if "\n" in payload or len(payload) > 1000:
                            payload = base64.b64encode(line.encode("utf-8")).decode("ascii")
                            emit(
                                PREFIX_CELL_OUTPUT
                                + str(code_cell_index)
                                + "\t"
                                + name
                                + "\tbase64\t"
                                + payload
                            )
                        else:
                            emit(
                                PREFIX_CELL_OUTPUT
                                + str(code_cell_index)
                                + "\t"
                                + name
                                + "\ttext\t"
                                + payload
                            )
                elif ot == "display_data" and "data" in out:
                    for mime, content in out["data"].items():
                        if mime.startswith("image/"):
                            if isinstance(content, list):
                                content = "".join(content)
                            if isinstance(content, bytes):
                                b64 = base64.b64encode(content).decode("ascii")
                            else:
                                b64 = content  # already base64 string in notebook
                            emit(
                                PREFIX_CELL_OUTPUT
                                + str(code_cell_index)
                                + "\timage\t"
                                + mime
                                + "\t"
                                + b64
                            )
                            break

    return 0


def main() -> int:
    notebook_path = "/app/main.ipynb"
    if len(sys.argv) > 1:
        notebook_path = sys.argv[1]
    return run_notebook(notebook_path)


if __name__ == "__main__":
    sys.exit(main())
