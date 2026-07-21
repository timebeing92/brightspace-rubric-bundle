from __future__ import annotations

import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import ZipFile


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "rubric_package"


def run_script(script: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, f"scripts/{script}", *args],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def local_name(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def build_example(tmp_path: Path, input_name: str = "rubrics_flat.example.md") -> Path:
    output_dir = tmp_path / "rubric_build"
    result = run_script(
        "build_rubric_package.py",
        "--input",
        str(FIXTURES / "input" / input_name),
        "--context-dir",
        str(FIXTURES / "context" / "reference_course_shell"),
        "--output-dir",
        str(output_dir),
        "--force",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return output_dir


def test_build_from_flat_markdown_produces_valid_package(tmp_path: Path) -> None:
    output_dir = build_example(tmp_path)

    package_dir = output_dir / "package"
    for relative in ("imsmanifest.xml", "rubrics_d2l.xml", "orgunitconfig/orgunitconfig.xml"):
        assert (package_dir / relative).exists(), f"missing {relative}"
    assert (output_dir / "package.zip").exists()
    assert (output_dir / "rubric_mapping.md").exists()
    assert (output_dir / "normalized_rubrics.json").exists()

    rubrics_root = ET.parse(package_dir / "rubrics_d2l.xml").getroot()
    assert local_name(rubrics_root.tag) == "rubrics"
    assert rubrics_root.attrib.get("schemaversion") == "v2011"
    rubric_elements = [el for el in rubrics_root if local_name(el.tag) == "rubric"]
    assert rubric_elements, "no rubric elements generated"
    # Same identity surface the activity extractor and real exports rely on.
    for rubric in rubric_elements:
        assert rubric.attrib.get("id")
        assert rubric.attrib.get("name")

    with ZipFile(output_dir / "package.zip") as archive:
        names = set(archive.namelist())
    assert "imsmanifest.xml" in names and "rubrics_d2l.xml" in names

    validation = run_script("validate_rubric_package.py", str(package_dir))
    assert validation.returncode == 0, validation.stdout + validation.stderr


def test_build_from_json_input(tmp_path: Path) -> None:
    output_dir = build_example(tmp_path, input_name="rubrics.example.json")
    contract = json.loads((output_dir / "normalized_rubrics.json").read_text(encoding="utf-8"))
    assert contract["rubrics"], "normalized contract has no rubrics"


def test_generated_vocabulary_matches_real_export_evidence(tmp_path: Path) -> None:
    """Generated rubrics_d2l.xml must not invent element names absent from real
    Brightspace exports (evidence: CHEM 1020 full export)."""
    evidence = (
        REPO_ROOT
        / "workspace/exports/unpacked/20260423-091649__chem-1020-2021-tng-full-d2l-export/rubrics_d2l.xml"
    )
    if not evidence.exists():
        import pytest

        pytest.skip("CHEM 1020 evidence export not present on this machine")

    output_dir = build_example(tmp_path)
    generated_root = ET.parse(output_dir / "package" / "rubrics_d2l.xml").getroot()
    evidence_root = ET.parse(evidence).getroot()
    generated_names = {local_name(el.tag) for el in generated_root.iter()}
    evidence_names = {local_name(el.tag) for el in evidence_root.iter()}
    invented = generated_names - evidence_names
    assert not invented, f"generated element names not found in real export evidence: {sorted(invented)}"


def test_flat_markdown_to_json_converter(tmp_path: Path) -> None:
    out_path = tmp_path / "converted.json"
    result = run_script(
        "flat_markdown_to_json.py",
        "--input",
        str(FIXTURES / "input" / "rubrics_flat.example.md"),
        "--output",
        str(out_path),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert data.get("rubrics")


def test_extract_course_context_from_reference_shell(tmp_path: Path) -> None:
    context_dir = tmp_path / "context"
    result = run_script(
        "extract_course_context.py",
        "--input",
        str(FIXTURES / "context" / "reference_course_shell"),
        "--output-dir",
        str(context_dir),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (context_dir / "imsmanifest.xml").exists()
    assert (context_dir / "orgunitconfig" / "orgunitconfig.xml").exists()
