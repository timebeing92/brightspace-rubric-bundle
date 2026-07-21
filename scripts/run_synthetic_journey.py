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
import re
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
JOURNEY_SCHEMA = "brightspace-rubric-bundle.synthetic-journey/1"
WEAVE_INPUT = REPO_ROOT / "tests/fixtures/rubric_package/input/rubrics_flat.example.md"
WEAVE_CONTEXT = REPO_ROOT / "tests/fixtures/rubric_package/context/reference_course_shell"


class JourneyError(RuntimeError):
    pass


def run_step(command: list[str]) -> str:
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode:
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        tail = "; ".join(detail[-3:]) if detail else f"exit {result.returncode}"
        raise JourneyError(f"{Path(command[1]).name} failed: {tail}")
    return result.stdout


def parse_key_values(stdout: str) -> dict[str, str]:
    pairs = {}
    for line in stdout.splitlines():
        match = re.match(r"^([a-z_]+)=(.+)$", line.strip())
        if match:
            pairs[match.group(1)] = match.group(2)
    return pairs


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
                str(SCRIPTS / "build_rubric_package.py"),
                "--input",
                str(WEAVE_INPUT),
                "--output-dir",
                str(weave_dir),
                "--context-dir",
                str(WEAVE_CONTEXT),
                "--force",
            ]
        )
        built = parse_key_values(stdout)
        package_dir = Path(built.get("package_dir", weave_dir / "package"))
        normalized_json = Path(built.get("normalized_json_path", weave_dir / "normalized_rubrics.json"))
        if not package_dir.is_dir() or not normalized_json.is_file():
            raise JourneyError("weave completed without the expected package artifacts")
        record("weave: build rubric-only import package", package_dir=str(package_dir))

        stdout = run_step(
            [sys.executable, str(SCRIPTS / "validate_rubric_package.py"), str(package_dir)]
        )
        if "VALID" not in stdout:
            raise JourneyError("package validator did not report VALID")
        record("weave: validate package structure")

        run_step(
            [
                sys.executable,
                str(SCRIPTS / "run_rubric_bundle.py"),
                str(package_dir),
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
            "package_dir": str(package_dir),
            "normalized_json": str(normalized_json),
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
