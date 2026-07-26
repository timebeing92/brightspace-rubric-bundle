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
    assert pin["source_commit"] == "ad08b1ca1ebd0889bba3353cd87ca71b88f26514"
    assert (
        pin["accepted_producer_commit"]
        == "7c5140545548c89a254ac4502cfdd7ee6fb44255"
    )
    sources = [entry["source"] for entry in pin["files"]]
    targets = [entry["target"] for entry in pin["files"]]
    assert len(sources) == len(set(sources))
    assert len(targets) == len(set(targets))

    result = run_script("scripts/vendor_from_workbench.py", "--check")
    assert result.returncode == 0, result.stderr


def test_release_candidate_version_is_1_2_0() -> None:
    assert (REPO_ROOT / "VERSION").read_text(encoding="utf-8") == "1.2.0\n"


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
        "scripts/generate_rubric_weave_intake_templates.py",
        "tests/test_rubric_weave_templates.py",
        "workspace/reference/templates/rubric-weave/v1/README.md",
        "workspace/reference/templates/rubric-weave/v1/manifest.json",
        "workspace/reference/templates/rubric-weave/v1/rubric-weave-intake-template.docx",
        "workspace/reference/templates/rubric-weave/v1/rubric-weave-intake-template.md",
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


def test_weave_tui_owns_no_rubric_semantics() -> None:
    """The Weave journey may call the orchestrator, never semantic modules."""
    source = (REPO_ROOT / "scripts" / "rubric_loom_weave.py").read_text(
        encoding="utf-8"
    )
    forbidden = (
        "import rubric_authoring",
        "from rubric_authoring",
        "import rubric_package_lib",
        "from rubric_package_lib",
        "import docx",
        "from docx",
        "ElementTree",
        "build_rubrics_xml",
        "normalize_source",
    )
    assert not any(marker in source for marker in forbidden)
    assert "run_weave_bundle.py" in source
