#!/usr/bin/env python3
"""Run the Unravel door: Brightspace rubric evidence to workbook, JSON, and DOCX.

This orchestrator sequences the pinned Workbench extraction scripts over one
source (a course export zip, an unpacked export folder, or a bare
``rubrics_d2l.xml``) and validates the emitted ``coursecraft.rubrics/1``
document against the vendored schema. It composes pinned behavior; it does not
parse D2L XML itself beyond detecting that rubric evidence is present.

Exit codes: 0 success, 1 step failure, 2 usage or environment error,
3 no rubric evidence found in the source.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import zipfile


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
RUBRICS_SCHEMA_PATH = REPO_ROOT / "workspace/reference/schemas/rubrics/rubrics_schema.json"
PROGRESS_SCHEMA = "coursecraft.progress/1"
RUBRIC_XML_NAME = "rubrics_d2l.xml"

STEP_LOCATE = "Locate rubric evidence"
STEP_EXTRACT = "Extract rubric grids"
STEP_VALIDATE = "Validate rubric contract"
STEP_DOCX = "Render rubric review DOCX"


class StepFailure(RuntimeError):
    def __init__(self, message: str, exit_code: int = 1) -> None:
        super().__init__(message)
        self.exit_code = exit_code


class Reporter:
    """Emit either human step banners or coursecraft.progress/1 NDJSON."""

    def __init__(self, events: bool, label: str, steps: list[str]) -> None:
        self.events = events
        self.label = label
        self.steps = steps
        self.total = len(steps)
        self._started = time.monotonic()

    def _emit(self, payload: dict) -> None:
        print(json.dumps(payload), flush=True)

    def run_start(self) -> None:
        if self.events:
            self._emit(
                {
                    "event": "run_start",
                    "schema": PROGRESS_SCHEMA,
                    "label": self.label,
                    "total": self.total,
                    "steps": self.steps,
                }
            )
        else:
            print(f"Rubric Loom — Unravel: {self.label} ({self.total} steps)")

    def step_start(self, index: int) -> float:
        label = self.steps[index - 1]
        if self.events:
            self._emit({"event": "step_start", "index": index, "total": self.total, "label": label})
        else:
            print(f"[{index}/{self.total}] {label}")
        return time.monotonic()

    def step_end(self, index: int, started: float, status: str, message: str | None = None) -> None:
        seconds = round(time.monotonic() - started, 3)
        if self.events:
            payload: dict = {"event": "step_end", "index": index, "status": status, "seconds": seconds}
            if message:
                payload["message"] = message
            self._emit(payload)
        elif status != "ok":
            print(f"    step failed: {message}")

    def child_output(self, text: str) -> None:
        if not self.events:
            for line in text.splitlines():
                if line.strip():
                    print(f"    | {line}")

    def run_end_ok(self, bundle_dir: Path, outputs: dict, summary: dict, empty: bool) -> None:
        if self.events:
            self._emit(
                {
                    "event": "run_end",
                    "status": "ok",
                    "message": f"unraveled {summary['rubrics']} rubric(s)",
                    "bundle_dir": str(bundle_dir),
                    "outputs": outputs,
                    "summary": summary,
                    "delivery": {"usable": True, "empty": empty, "core_failures": []},
                }
            )
        else:
            print(f"Done: {summary['rubrics']} rubric(s) in {bundle_dir}")

    def run_end_error(self, step: str, message: str) -> None:
        if self.events:
            self._emit(
                {
                    "event": "run_end",
                    "status": "error",
                    "message": message,
                    "issues": [{"step": step, "status": "failed", "message": message}],
                }
            )
        else:
            print(f"ERROR: {message}", file=sys.stderr)


def sanitize_label(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._") or "rubrics"
    return cleaned


def default_label(source: Path) -> str:
    stem = source.stem if source.suffix else source.name
    if stem == RUBRIC_XML_NAME.rsplit(".", 1)[0]:
        stem = source.resolve().parent.name or stem
    return sanitize_label(stem)


def source_has_rubric_evidence(source: Path) -> bool:
    if source.is_file() and source.name == RUBRIC_XML_NAME:
        return True
    if source.is_file() and source.suffix.lower() == ".zip":
        try:
            with zipfile.ZipFile(source) as archive:
                return any(Path(name).name == RUBRIC_XML_NAME for name in archive.namelist())
        except zipfile.BadZipFile as exc:
            raise StepFailure(f"source is not a readable zip archive: {source} ({exc})")
    if source.is_dir():
        return any(source.rglob(RUBRIC_XML_NAME))
    raise StepFailure(f"source is not an export zip, folder, or {RUBRIC_XML_NAME}: {source}")


def run_pinned(script: str, args: list[str], timeout: float) -> str:
    command = [sys.executable, str(SCRIPTS / script), *args]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise StepFailure(f"{script} exceeded the step timeout of {timeout:.0f}s") from exc
    if result.returncode:
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        tail = "; ".join(detail[-3:]) if detail else f"exit {result.returncode}"
        raise StepFailure(f"{script} failed: {tail}")
    return result.stdout


def load_rubrics_document(path: Path) -> dict:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StepFailure(f"rubrics JSON is unreadable: {path} ({exc})")
    if not isinstance(document, dict) or not isinstance(document.get("rubrics"), list):
        raise StepFailure(f"rubrics JSON lacks a top-level rubrics list: {path}")
    return document


def validate_contract(document: dict) -> None:
    try:
        import jsonschema
    except ImportError as exc:
        raise StepFailure(
            "the jsonschema package is required; install requirements.txt", exit_code=2
        ) from exc
    schema = json.loads(RUBRICS_SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = jsonschema.Draft7Validator(schema)
    errors = sorted(validator.iter_errors(document), key=lambda err: list(err.absolute_path))
    if errors:
        first = errors[0]
        location = "/".join(str(part) for part in first.absolute_path) or "<root>"
        raise StepFailure(
            f"rubrics JSON violates coursecraft.rubrics/1 at {location}: {first.message}"
        )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "source",
        type=Path,
        help=f"course export zip, unpacked export folder, or {RUBRIC_XML_NAME}",
    )
    parser.add_argument("--output-dir", type=Path, help="destination folder (default: output/<label>__rubric_bundle)")
    parser.add_argument("--label", help="output stem for emitted artifacts (default: derived from the source name)")
    parser.add_argument("--no-docx", action="store_true", help="skip the reviewer DOCX render")
    parser.add_argument(
        "--progress-events",
        action="store_true",
        help="emit coursecraft.progress/1 NDJSON on stdout instead of human banners",
    )
    parser.add_argument("--step-timeout", type=float, default=900.0, help="per-step timeout in seconds")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    source: Path = args.source
    label = sanitize_label(args.label) if args.label else default_label(source)
    bundle_dir = args.output_dir if args.output_dir else Path("output") / f"{label}__rubric_bundle"

    steps = [STEP_LOCATE, STEP_EXTRACT, STEP_VALIDATE]
    if not args.no_docx:
        steps.append(STEP_DOCX)
    reporter = Reporter(args.progress_events, label, steps)
    reporter.run_start()

    workbook_path = bundle_dir / f"{label}__rubrics.xlsx"
    json_path = bundle_dir / f"{label}__rubrics.json"
    docx_path = bundle_dir / f"{label}__rubrics.docx"

    index = 0
    current_step = steps[0]
    try:
        index = 1
        current_step = STEP_LOCATE
        started = reporter.step_start(index)
        if not source.exists():
            raise StepFailure(f"source not found: {source}", exit_code=2)
        if not source_has_rubric_evidence(source):
            raise StepFailure(
                f"no {RUBRIC_XML_NAME} found in the source; nothing to unravel", exit_code=3
            )
        reporter.step_end(index, started, "ok")

        index = 2
        current_step = STEP_EXTRACT
        started = reporter.step_start(index)
        bundle_dir.mkdir(parents=True, exist_ok=True)
        stdout = run_pinned(
            "extract_rubrics_to_workbook.py",
            [
                str(source),
                "--output",
                str(workbook_path),
                "--json",
                "--json-output",
                str(json_path),
            ],
            args.step_timeout,
        )
        reporter.child_output(stdout)
        if not json_path.is_file() or not workbook_path.is_file():
            raise StepFailure("extraction completed without emitting the expected artifacts")
        reporter.step_end(index, started, "ok")

        index = 3
        current_step = STEP_VALIDATE
        started = reporter.step_start(index)
        document = load_rubrics_document(json_path)
        validate_contract(document)
        rubric_count = len(document["rubrics"])
        diagnostics_count = len(document.get("diagnostics", []))
        reporter.step_end(index, started, "ok")

        if not args.no_docx:
            index = 4
            current_step = STEP_DOCX
            started = reporter.step_start(index)
            stdout = run_pinned(
                "rubrics_to_docx.py",
                [str(json_path), "--output", str(docx_path), "--title", f"{label} Rubrics"],
                args.step_timeout,
            )
            reporter.child_output(stdout)
            if not docx_path.is_file():
                raise StepFailure("DOCX render completed without emitting the document")
            reporter.step_end(index, started, "ok")
    except StepFailure as failure:
        if index:
            reporter.step_end(index, started, "error", str(failure))
        reporter.run_end_error(current_step, str(failure))
        return failure.exit_code

    outputs = {
        "rubrics_json": str(json_path),
        "rubrics_workbook": str(workbook_path),
        "rubrics_docx": None if args.no_docx else str(docx_path),
    }
    summary = {"rubrics": rubric_count, "diagnostics": diagnostics_count}
    reporter.run_end_ok(bundle_dir, outputs, summary, empty=(rubric_count == 0))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
