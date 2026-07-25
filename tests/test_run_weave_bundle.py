from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import jsonschema


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "run_weave_bundle.py"
PRODUCER = REPO_ROOT / "scripts" / "make_rubric_package.py"
EXPLICIT = REPO_ROOT / "tests" / "fixtures" / "rubric_authoring" / "three_level_explicit.md"
AMBIGUOUS = (
    REPO_ROOT
    / "tests"
    / "fixtures"
    / "rubric_authoring"
    / "missing_scoring_and_weights.md"
)
PROGRESS_SCHEMA = json.loads(
    (
        REPO_ROOT
        / "workspace"
        / "reference"
        / "schemas"
        / "progress"
        / "progress_events_schema.json"
    ).read_text()
)
RUN_SCHEMA = json.loads(
    (
        REPO_ROOT
        / "workspace"
        / "reference"
        / "schemas"
        / "course"
        / "run_identity_schema.json"
    ).read_text()
)


def run_weave(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_preflight_delegates_to_the_pinned_producer() -> None:
    result = run_weave(str(EXPLICIT), "--preflight")
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["schema"] == "coursecraft.rubric_authoring_preflight/1"
    assert summary["status"] == "ok"
    assert summary["rubric_count"] == 1
    assert summary["rubrics"][0]["name"] == "Evidence Analysis"
    assert [level["name"] for level in summary["rubrics"][0]["levels"]] == [
        "Excellent",
        "Capable",
        "Beginning",
    ]
    assert {level["score_source"] for level in summary["rubrics"][0]["levels"]} == {
        "numeric_level_header"
    }


def test_build_emits_required_artifacts_and_final_receipt(tmp_path: Path) -> None:
    output = tmp_path / "weave"
    result = run_weave(str(EXPLICIT), "--output-dir", str(output))
    assert result.returncode == 0, result.stderr
    assert "Nothing was imported" in result.stdout
    for relative in (
        "rubric_package.zip",
        "rubrics_d2l.xml",
        "normalized_rubric_authoring.json",
        "rubric_mapping.md",
        "diagnostics.json",
        "producer_run_receipt.json",
        "run_receipt.json",
    ):
        assert (output / relative).is_file(), relative

    receipt = json.loads((output / "run_receipt.json").read_text())
    jsonschema.Draft7Validator(RUN_SCHEMA).validate(receipt)
    assert receipt["status"] == "ok"
    assert receipt["producer"]["component"] == "brightspace-rubric-bundle-weave"
    assert receipt["extensions"]["workbench_pin"]["source_commit"] == (
        "7c5140545548c89a254ac4502cfdd7ee6fb44255"
    )
    assert receipt["extensions"]["activity_attachment"] == "manual_only"
    assert [step["name"] for step in receipt["steps"]] == [
        "Inspect source",
        "Normalize authoring contract",
        "Validate authoring contract",
        "Build rubric-only package",
        "Validate rubric package",
        "Write final run receipt",
    ]


def test_progress_events_conform_and_name_actual_outputs(tmp_path: Path) -> None:
    output = tmp_path / "weave"
    result = run_weave(
        str(EXPLICIT),
        "--output-dir",
        str(output),
        "--progress-events",
    )
    assert result.returncode == 0, result.stderr
    events = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    validator = jsonschema.Draft7Validator(PROGRESS_SCHEMA)
    for event in events:
        validator.validate(event)
    assert events[0]["event"] == "run_start"
    assert events[0]["steps"][-1] == "Write final run receipt"
    run_end = events[-1]
    assert run_end["event"] == "run_end"
    assert run_end["status"] == "ok"
    assert run_end["message"].endswith("nothing was imported")
    assert run_end["delivery"] == {
        "usable": True,
        "empty": False,
        "core_failures": [],
    }
    for key in (
        "import_zip",
        "rubrics_xml",
        "normalized_authoring_json",
        "mapping_report",
        "diagnostics_json",
        "run_identity",
    ):
        assert Path(run_end["outputs"][key]).is_file(), key
    assert run_end["outputs"]["review_report"] is None


def test_cli_wrapper_preserves_pinned_producer_artifacts(tmp_path: Path) -> None:
    direct = tmp_path / "direct"
    wrapped = tmp_path / "wrapped"
    producer = subprocess.run(
        [
            sys.executable,
            str(PRODUCER),
            "--input",
            str(EXPLICIT),
            "--output-dir",
            str(direct),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert producer.returncode == 0, producer.stderr
    result = run_weave(str(EXPLICIT), "--output-dir", str(wrapped))
    assert result.returncode == 0, result.stderr
    for relative in (
        "rubric_package.zip",
        "rubrics_d2l.xml",
        "normalized_rubric_authoring.json",
        "rubric_mapping.md",
        "diagnostics.json",
    ):
        assert (direct / relative).read_bytes() == (wrapped / relative).read_bytes()


def test_missing_scoring_refuses_without_creating_output(tmp_path: Path) -> None:
    output = tmp_path / "refused"
    result = run_weave(
        str(AMBIGUOUS),
        "--output-dir",
        str(output),
        "--progress-events",
    )
    assert result.returncode == 2
    events = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    assert events[-1]["event"] == "run_end"
    assert events[-1]["status"] == "error"
    assert "CRITERION_WEIGHT_REQUIRED" in events[-1]["message"]
    assert "SCORING_METADATA_REQUIRED" in events[-1]["message"]
    assert not output.exists()


def test_explicit_fallback_approvals_are_visible_in_preflight() -> None:
    result = run_weave(
        str(AMBIGUOUS),
        "--preflight",
        "--allow-even-spacing",
        "--allow-equal-weights",
    )
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["approvals"] == {
        "equal_weights": True,
        "even_spacing": True,
    }
    codes = {item["code"] for item in summary["diagnostics"]}
    assert {"EVEN_SPACING_APPROVED", "EQUAL_WEIGHTS_APPROVED"} <= codes


def test_missing_and_invalid_sources_exit_two(tmp_path: Path) -> None:
    missing = run_weave(str(tmp_path / "absent.docx"))
    assert missing.returncode == 2
    invalid = tmp_path / "rubric.txt"
    invalid.write_text("not accepted", encoding="utf-8")
    result = run_weave(str(invalid))
    assert result.returncode == 2
    assert "DOCX, Markdown, or JSON" in (result.stdout + result.stderr)
