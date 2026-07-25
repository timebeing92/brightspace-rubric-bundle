from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]


def run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_vendor_pin_has_unique_byte_identical_targets() -> None:
    pin = json.loads((REPO_ROOT / "upstream" / "workbench_pin.json").read_text())
    assert pin["schema"] == "coursecraft.workbench_vendor_pin/1"
    assert len(pin["source_commit"]) == 40
    targets = [entry["target"] for entry in pin["files"]]
    assert len(targets) == len(set(targets))

    result = run_script("scripts/vendor_from_workbench.py", "--check")
    assert result.returncode == 0, result.stderr


def test_pin_covers_both_doors_and_the_contracts() -> None:
    pin = json.loads((REPO_ROOT / "upstream" / "workbench_pin.json").read_text())
    targets = {entry["target"] for entry in pin["files"]}
    expected = {
        "scripts/extract_rubrics_to_workbook.py",
        "scripts/rubrics_to_docx.py",
        "scripts/common_xml.py",
        "scripts/build_rubric_package.py",
        "scripts/make_rubric_package.py",
        "scripts/rubric_authoring.py",
        "scripts/validate_rubric_package.py",
        "scripts/rubric_package_lib.py",
        "workspace/reference/schemas/course/run_identity_schema.json",
        "workspace/reference/schemas/rubrics/rubric_authoring_schema.json",
        "workspace/reference/schemas/rubrics/rubrics_schema.json",
    }
    assert expected <= targets


def test_only_canonical_workbench_sources_are_promoted() -> None:
    """The old staged prototype remains excluded after canonical promotion."""
    pin = json.loads((REPO_ROOT / "upstream" / "workbench_pin.json").read_text())
    sources = {entry["source"] for entry in pin["files"]}
    assert not any(
        source.startswith("workspace/generated/")
        for source in sources
    )
    assert "scripts/docx_to_rubric_contract.py" not in sources
    assert "scripts/make_rubric_package.py" in sources
