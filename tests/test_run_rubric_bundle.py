from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

import jsonschema


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_EXPORT = REPO_ROOT / "tests" / "fixtures" / "tiny_rubrics_export"
PROGRESS_SCHEMA = json.loads(
    (REPO_ROOT / "workspace/reference/schemas/progress/progress_events_schema.json").read_text()
)
RUBRICS_SCHEMA = json.loads(
    (REPO_ROOT / "workspace/reference/schemas/rubrics/rubrics_schema.json").read_text()
)


def run_bundle(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "run_rubric_bundle.py"), *args],
        cwd=cwd or REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_unravels_an_export_folder(tmp_path: Path) -> None:
    out_dir = tmp_path / "bundle"
    result = run_bundle(str(FIXTURE_EXPORT), "--output-dir", str(out_dir), "--label", "tiny")
    assert result.returncode == 0, result.stderr

    document = json.loads((out_dir / "tiny__rubrics.json").read_text())
    jsonschema.Draft7Validator(RUBRICS_SCHEMA).validate(document)
    assert document["schema"] == "coursecraft.rubrics/1"
    assert len(document["rubrics"]) >= 1
    assert (out_dir / "tiny__rubrics.xlsx").is_file()
    assert (out_dir / "tiny__rubrics.docx").is_file()


def test_unravels_a_zip_export(tmp_path: Path) -> None:
    archive = tmp_path / "tiny_export.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for path in FIXTURE_EXPORT.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(FIXTURE_EXPORT))
    out_dir = tmp_path / "bundle"
    result = run_bundle(str(archive), "--output-dir", str(out_dir), "--label", "tiny_zip")
    assert result.returncode == 0, result.stderr
    assert (out_dir / "tiny_zip__rubrics.json").is_file()


def test_no_docx_skips_the_render(tmp_path: Path) -> None:
    out_dir = tmp_path / "bundle"
    result = run_bundle(
        str(FIXTURE_EXPORT), "--output-dir", str(out_dir), "--label", "tiny", "--no-docx"
    )
    assert result.returncode == 0, result.stderr
    assert (out_dir / "tiny__rubrics.json").is_file()
    assert not (out_dir / "tiny__rubrics.docx").exists()


def test_source_without_rubric_evidence_exits_3(tmp_path: Path) -> None:
    bare = tmp_path / "no_rubrics_here"
    bare.mkdir()
    (bare / "imsmanifest.xml").write_text("<manifest />", encoding="utf-8")
    result = run_bundle(str(bare), "--output-dir", str(tmp_path / "bundle"))
    assert result.returncode == 3
    assert "nothing to unravel" in (result.stderr + result.stdout)


def test_missing_source_exits_2(tmp_path: Path) -> None:
    result = run_bundle(str(tmp_path / "absent.zip"), "--output-dir", str(tmp_path / "bundle"))
    assert result.returncode == 2


def test_progress_events_conform_to_the_contract(tmp_path: Path) -> None:
    out_dir = tmp_path / "bundle"
    result = run_bundle(
        str(FIXTURE_EXPORT),
        "--output-dir",
        str(out_dir),
        "--label",
        "tiny",
        "--progress-events",
    )
    assert result.returncode == 0, result.stderr

    validator = jsonschema.Draft7Validator(PROGRESS_SCHEMA)
    events = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    for event in events:
        validator.validate(event)

    kinds = [event["event"] for event in events]
    assert kinds[0] == "run_start"
    assert kinds[-1] == "run_end"
    run_start = events[0]
    assert run_start["steps"][0] == "Locate rubric evidence"
    run_end = events[-1]
    assert run_end["status"] == "ok"
    assert run_end["summary"]["rubrics"] >= 1
    assert run_end["delivery"] == {"usable": True, "empty": False, "core_failures": []}
    for key in ("rubrics_json", "rubrics_workbook", "rubrics_docx"):
        assert Path(run_end["outputs"][key]).is_file()


def test_failure_emits_error_events(tmp_path: Path) -> None:
    bare = tmp_path / "no_rubrics_here"
    bare.mkdir()
    (bare / "imsmanifest.xml").write_text("<manifest />", encoding="utf-8")
    result = run_bundle(
        str(bare), "--output-dir", str(tmp_path / "bundle"), "--progress-events"
    )
    assert result.returncode == 3
    validator = jsonschema.Draft7Validator(PROGRESS_SCHEMA)
    events = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    for event in events:
        validator.validate(event)
    run_end = events[-1]
    assert run_end["event"] == "run_end"
    assert run_end["status"] == "error"
    assert run_end["issues"][0]["step"] == "Locate rubric evidence"


def test_default_output_dir_is_cwd_relative(tmp_path: Path) -> None:
    workdir = tmp_path / "elsewhere"
    workdir.mkdir()
    fixture_copy = tmp_path / "tiny_rubrics_export"
    shutil.copytree(FIXTURE_EXPORT, fixture_copy)
    result = run_bundle(str(fixture_copy), cwd=workdir)
    assert result.returncode == 0, result.stderr
    produced = workdir / "output" / "tiny_rubrics_export__rubric_bundle"
    assert (produced / "tiny_rubrics_export__rubrics.json").is_file()
