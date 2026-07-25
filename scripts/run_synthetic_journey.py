#!/usr/bin/env python3
"""Prove both Rubric Loom doors on synthetic fixtures, with a written receipt.

The journey weaves a rubric-only import package from the pinned flat-markdown
fixture, validates the package, then unravels the same package back through
extraction and asserts that the rubric names survive the loop. Everything runs
on synthetic fixture content; no course export or institutional data is
touched.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
JOURNEY_SCHEMA = "brightspace-rubric-bundle.synthetic-journey/1"
WEAVE_INPUT = REPO_ROOT / "tests/fixtures/rubric_authoring/three_level_explicit.md"


class JourneyError(RuntimeError):
    pass


def run_step(command: list[str]) -> str:
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode:
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        tail = "; ".join(detail[-3:]) if detail else f"exit {result.returncode}"
        raise JourneyError(f"{Path(command[1]).name} failed: {tail}")
    return result.stdout


def progress_events(stdout: str) -> list[dict]:
    events = []
    for line in stdout.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and value.get("event"):
            events.append(value)
    return events


def rubric_names_from_contract(path: Path) -> list[str]:
    document = json.loads(path.read_text(encoding="utf-8"))
    rubrics = document.get("rubrics", []) if isinstance(document, dict) else []
    return sorted(
        entry["name"] for entry in rubrics if isinstance(entry, dict) and entry.get("name")
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output") / "synthetic_journey",
        help="destination folder for journey artifacts and the receipt",
    )
    args = parser.parse_args()

    journey_dir: Path = args.output_dir
    weave_dir = journey_dir / "weave"
    unravel_dir = journey_dir / "unravel"
    receipt_path = journey_dir / "journey_receipt.json"
    steps: list[dict] = []

    def record(name: str, **detail: object) -> None:
        steps.append({"name": name, "status": "ok", **detail})
        print(f"ok: {name}")

    try:
        journey_dir.mkdir(parents=True, exist_ok=True)

        stdout = run_step(
            [
                sys.executable,
                str(SCRIPTS / "run_weave_bundle.py"),
                str(WEAVE_INPUT),
                "--output-dir",
                str(weave_dir),
                "--force",
                "--progress-events",
            ]
        )
        weave_events = progress_events(stdout)
        if not weave_events or weave_events[-1].get("status") != "ok":
            raise JourneyError("Weave orchestrator did not report a successful run")
        weave_outputs = weave_events[-1].get("outputs", {})
        package_zip = Path(weave_outputs.get("import_zip", ""))
        normalized_json = Path(weave_outputs.get("normalized_authoring_json", ""))
        weave_receipt = Path(weave_outputs.get("run_identity", ""))
        if not package_zip.is_file() or not normalized_json.is_file() or not weave_receipt.is_file():
            raise JourneyError("weave completed without the expected package artifacts")
        record(
            "weave: build rubric-only import package",
            package_zip=str(package_zip),
            run_receipt=str(weave_receipt),
            progress_steps=weave_events[0].get("steps", []),
        )

        stdout = run_step(
            [sys.executable, str(SCRIPTS / "validate_rubric_package.py"), str(package_zip)]
        )
        if "VALID" not in stdout:
            raise JourneyError("package validator did not report VALID")
        record("weave: validate package structure")

        run_step(
            [
                sys.executable,
                str(SCRIPTS / "run_rubric_bundle.py"),
                str(package_zip),
                "--output-dir",
                str(unravel_dir),
                "--label",
                "loom_proof",
            ]
        )
        extracted_json = unravel_dir / "loom_proof__rubrics.json"
        if not extracted_json.is_file():
            raise JourneyError("unravel completed without the rubrics JSON")
        record("unravel: extract, validate, and render from the woven package")

        woven_names = rubric_names_from_contract(normalized_json)
        unraveled_names = rubric_names_from_contract(extracted_json)
        if not woven_names or woven_names != unraveled_names:
            raise JourneyError(
                f"rubric names did not survive the loop: wove {woven_names}, unraveled {unraveled_names}"
            )
        record("loop: rubric names survive weave -> unravel", rubric_names=woven_names)
    except JourneyError as failure:
        steps.append({"name": "journey", "status": "error", "message": str(failure)})
        receipt = {
            "schema": JOURNEY_SCHEMA,
            "status": "error",
            "completed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "steps": steps,
        }
        journey_dir.mkdir(parents=True, exist_ok=True)
        receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        print(f"ERROR: {failure}", file=sys.stderr)
        return 1

    receipt = {
        "schema": JOURNEY_SCHEMA,
        "status": "ok",
        "completed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "weave_input": str(WEAVE_INPUT.relative_to(REPO_ROOT)),
        "steps": steps,
        "artifacts": {
            "import_zip": str(package_zip),
            "normalized_json": str(normalized_json),
            "weave_run_identity": str(weave_receipt),
            "rubrics_json": str(extracted_json),
            "rubrics_workbook": str(unravel_dir / "loom_proof__rubrics.xlsx"),
            "rubrics_docx": str(unravel_dir / "loom_proof__rubrics.docx"),
        },
    }
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(f"journey receipt: {receipt_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
