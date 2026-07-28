"""Bulk Unravel: bounded discovery, collision safety, and partial outcomes."""
from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import sys
from types import SimpleNamespace
import zipfile

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "tiny_rubrics_export"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import loom_ui  # noqa: E402
import rubric_loom_wizard as wizard  # noqa: E402


def fixture_zip(folder: Path, name: str) -> Path:
    archive = folder / name
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr(
            "rubrics_d2l.xml",
            (FIXTURE / "rubrics_d2l.xml").read_bytes(),
        )
    return archive


def unpacked_export(folder: Path, name: str) -> Path:
    source = folder / name
    source.mkdir()
    shutil.copyfile(
        FIXTURE / "rubrics_d2l.xml",
        source / "rubrics_d2l.xml",
    )
    return source


def test_bulk_discovery_is_immediate_mixed_and_symlink_safe(
    tmp_path: Path,
) -> None:
    batch = tmp_path / "batch"
    batch.mkdir()
    archive = fixture_zip(batch, "Alpha.zip")
    unpacked_export(batch, "Beta")
    manifest_only = batch / "Gamma"
    manifest_only.mkdir()
    (manifest_only / "imsmanifest.xml").write_text("<manifest/>", encoding="utf-8")

    nested_container = batch / "not-an-immediate-export"
    (nested_container / "deeper-export").mkdir(parents=True)
    shutil.copyfile(
        FIXTURE / "rubrics_d2l.xml",
        nested_container / "deeper-export" / "rubrics_d2l.xml",
    )
    (batch / "notes.txt").write_text("not an export", encoding="utf-8")
    fixture_zip(batch, ".hidden.zip")
    linked = batch / "linked.zip"
    try:
        linked.symlink_to(archive)
    except OSError:
        linked = None

    discovery = wizard.discover_bulk_sources(batch)

    assert discovery.problem == ""
    assert [path.name for path in discovery.sources] == [
        "Alpha.zip",
        "Beta",
        "Gamma",
    ]
    ignored = {path.name for path in discovery.ignored}
    assert {
        ".hidden.zip",
        "not-an-immediate-export",
        "notes.txt",
    } <= ignored
    if linked is not None:
        assert linked.name in ignored


def test_bulk_discovery_refuses_a_single_unpacked_export_root(
    tmp_path: Path,
) -> None:
    source = tmp_path / "one-course"
    source.mkdir()
    (source / "imsmanifest.xml").write_text("<manifest/>", encoding="utf-8")
    fixture_zip(source, "decoy.zip")

    discovery = wizard.discover_bulk_sources(source)

    assert discovery.sources == ()
    assert "looks like one unpacked Brightspace export" in discovery.problem
    assert "Single Unravel" in discovery.problem


def test_bulk_discovery_refuses_symlink_root_and_non_folder(
    tmp_path: Path,
) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable")

    assert "symbolic link" in wizard.discover_bulk_sources(link).problem
    ordinary_file = tmp_path / "ordinary.txt"
    ordinary_file.write_text("x", encoding="utf-8")
    assert "must be a folder" in wizard.discover_bulk_sources(ordinary_file).problem


def test_bulk_discovery_detects_sanitized_output_collisions(
    tmp_path: Path,
) -> None:
    batch = tmp_path / "batch"
    batch.mkdir()
    fixture_zip(batch, "Course A.zip")
    fixture_zip(batch, "Course_A.zip")

    discovery = wizard.discover_bulk_sources(batch)

    assert len(discovery.sources) == 2
    assert discovery.collisions == (
        ("Course_A", (batch / "Course A.zip", batch / "Course_A.zip")),
    )


def test_bulk_discovery_accepts_uppercase_zip_suffix(tmp_path: Path) -> None:
    batch = tmp_path / "batch"
    batch.mkdir()
    archive = fixture_zip(batch, "COURSE.ZIP")

    discovery = wizard.discover_bulk_sources(batch)

    assert discovery.sources == (archive,)


def test_bulk_destination_refuses_source_descendants_and_replacement_traps(
    tmp_path: Path,
) -> None:
    batch = tmp_path / "batch"
    batch.mkdir()
    source = fixture_zip(batch, "Course.zip")

    assert "outside the batch source" in wizard.bulk_destination_problem(
        batch, batch / "results", (source,)
    )
    alias = tmp_path / "batch-alias"
    try:
        alias.symlink_to(batch, target_is_directory=True)
    except OSError:
        alias = None
    if alias is not None:
        assert "outside the batch source" in wizard.bulk_destination_problem(
            batch, alias / "results", (source,)
        )

    output = tmp_path / "output"
    output.mkdir()
    planned = output / "Course__rubric_bundle"
    planned.write_text("not a directory", encoding="utf-8")
    assert "existing file" in wizard.bulk_destination_problem(
        batch, output, (source,)
    )


def test_bulk_destination_refuses_symlink_course_folder(
    tmp_path: Path,
) -> None:
    batch = tmp_path / "batch"
    batch.mkdir()
    source = fixture_zip(batch, "Course.zip")
    output = tmp_path / "output"
    output.mkdir()
    target = tmp_path / "elsewhere"
    target.mkdir()
    planned = output / "Course__rubric_bundle"
    try:
        planned.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable")

    assert "symbolic link" in wizard.bulk_destination_problem(
        batch, output, (source,)
    )


def test_bulk_runner_continues_across_no_evidence_and_corrupt_zip(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    batch = tmp_path / "batch"
    batch.mkdir()
    good = fixture_zip(batch, "Good.zip")
    empty = batch / "Empty"
    empty.mkdir()
    (empty / "imsmanifest.xml").write_text("<manifest/>", encoding="utf-8")
    corrupt = batch / "Broken.zip"
    corrupt.write_bytes(b"not a zip")
    output = tmp_path / "output"
    monkeypatch.setattr(wizard, "STATE_PATH", tmp_path / "state.json")

    code = wizard.run_bulk_unravel(
        loom_ui.Term(plain=True),
        SimpleNamespace(),
        batch,
        (good, empty, corrupt),
        output,
        False,
    )

    text = capsys.readouterr().out
    assert code == 1
    assert "Bulk Unravel summary" in text
    assert re.search(r"completed\s+1", text)
    assert re.search(r"no rubric evidence\s+1", text)
    assert re.search(r"failed\s+1", text)
    assert (output / "Good__rubric_bundle" / "Good__rubrics.json").is_file()
    assert (output / "Empty__rubric_bundle" / "unravel_wizard.log").is_file()
    assert (output / "Broken__rubric_bundle" / "unravel_wizard.log").is_file()


def test_bulk_runner_stops_before_next_source_after_interrupt(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    batch = tmp_path / "batch"
    batch.mkdir()
    sources = (
        fixture_zip(batch, "First.zip"),
        fixture_zip(batch, "Second.zip"),
    )
    attempted: list[str] = []

    def interrupted(*args, **kwargs) -> int:
        attempted.append(args[1].name)
        return 130

    monkeypatch.setattr(wizard, "run_unravel", interrupted)
    monkeypatch.setattr(wizard, "STATE_PATH", tmp_path / "state.json")

    code = wizard.run_bulk_unravel(
        loom_ui.Term(plain=True),
        SimpleNamespace(),
        batch,
        sources,
        tmp_path / "output",
        False,
    )

    text = capsys.readouterr().out
    assert code == 130
    assert attempted == ["First.zip"]
    assert re.search(r"not attempted\s+1", text)


def test_bulk_return_code_distinguishes_complete_empty_partial_and_interrupt() -> None:
    path = Path("x")

    def outcome(status: str, code: int) -> wizard.BulkOutcome:
        return wizard.BulkOutcome(path, path, status, code)

    assert wizard.bulk_return_code((outcome("completed", 0),)) == 0
    assert wizard.bulk_return_code((outcome("no rubric evidence", 3),)) == 3
    assert (
        wizard.bulk_return_code(
            (outcome("completed", 0), outcome("no rubric evidence", 3))
        )
        == 1
    )
    assert wizard.bulk_return_code((outcome("failed", 2),)) == 1
    assert wizard.bulk_return_code((outcome("interrupted", 130),)) == 130


def test_bulk_refuses_one_shared_label_before_source_or_output_prompts(
    capsys,
) -> None:
    code = wizard._run_bulk_interactive(
        loom_ui.Term(plain=True),
        SimpleNamespace(label="one-name-for-everything"),
        True,
    )

    assert code == 2
    text = capsys.readouterr().out
    assert "--label belongs to Single Unravel" in text
    assert "collision-checked output name" in text


@pytest.mark.skipif(os.name != "posix", reason="PTY is POSIX-only")
def test_guided_bulk_unravel_runs_zip_and_unpacked_folder(
    tmp_path: Path,
) -> None:
    from test_rubric_loom_wizard import PtyWizard

    batch = tmp_path / "batch"
    batch.mkdir()
    fixture_zip(batch, "Course One.zip")
    unpacked_export(batch, "Course Two")
    (batch / "ignore-me.txt").write_text("not an export", encoding="utf-8")
    output = tmp_path / "bulk-output"

    session = PtyWizard(
        ["--brisk", "--no-docx"],
        state=tmp_path / "state.json",
    )
    session.wait_for(b"What do you want to do?")
    session.send(b"1\r")
    session.wait_for(b"How would you like to begin?")
    session.send(b"2\r")
    session.wait_for(b"Folder containing the course exports")
    session.send(str(batch).encode() + b"\r")
    session.wait_for(b"Bulk source check")
    session.wait_for(b"exports found")
    session.wait_for(b"ignored")
    session.wait_for_count(b"Start Bulk Unravel?", 1)
    session.send(b"2\r")
    session.wait_for(b"Save folder for all course bundles")
    session.send(str(output).encode() + b"\r")
    session.wait_for_count(b"Start Bulk Unravel?", 2)
    session.send(b"\r")
    session.wait_for(b"Bulk Unravel summary", timeout=30.0)
    session.wait_for(b"Open the folder containing these files?")
    session.send(b"n\r")
    code = session.finish(timeout=30.0)

    assert code == 0
    assert (
        output
        / "Course_One__rubric_bundle"
        / "Course_One__rubrics.json"
    ).is_file()
    assert (
        output
        / "Course_Two__rubric_bundle"
        / "Course_Two__rubrics.json"
    ).is_file()
    assert re.search(rb"completed\s+2", session.stream)


@pytest.mark.skipif(os.name != "posix", reason="PTY is POSIX-only")
def test_guided_bulk_refuses_colliding_labels_before_any_write(
    tmp_path: Path,
) -> None:
    from test_rubric_loom_wizard import PtyWizard

    batch = tmp_path / "batch"
    batch.mkdir()
    fixture_zip(batch, "Course A.zip")
    fixture_zip(batch, "Course_A.zip")
    output = tmp_path / "must-not-exist"

    session = PtyWizard(
        [
            "--brisk",
            "--door",
            "unravel",
            "--no-docx",
            "--output-dir",
            str(output),
        ],
        state=tmp_path / "state.json",
    )
    session.wait_for_count(b"How would you like to begin?", 1)
    session.send(b"2\r")
    session.wait_for(b"Folder containing the course exports")
    session.send(str(batch).encode() + b"\r")
    session.wait_for(b"Bulk output names collide")
    session.wait_for_count(b"Folder containing the course exports", 2)
    session.send(b"b\r")
    session.wait_for_count(b"How would you like to begin?", 2)
    session.send(b"e\r")
    assert session.finish() == 0
    assert not output.exists()


@pytest.mark.skipif(os.name != "posix", reason="PTY is POSIX-only")
def test_guided_single_source_back_returns_to_the_unravel_choices(
    tmp_path: Path,
) -> None:
    from test_rubric_loom_wizard import PtyWizard

    session = PtyWizard(["--brisk"], state=tmp_path / "state.json")
    session.wait_for(b"What do you want to do?")
    session.send(b"1\r")
    session.wait_for_count(b"How would you like to begin?", 1)
    session.send(b"1\r")
    session.wait_for(b"Course export path")
    session.send(b"b\r")
    session.wait_for_count(b"How would you like to begin?", 2)
    session.send(b"e\r")
    assert session.finish() == 0
    assert b"nothing was run." in session.stream
    assert b"Where is the course export you want to read?" not in session.stream
    assert b"Enter or drag a different file or folder path" not in session.stream


@pytest.mark.skipif(os.name != "posix", reason="PTY is POSIX-only")
def test_demonstration_is_an_early_choice_not_a_source_prompt_shortcut(
    tmp_path: Path,
) -> None:
    from test_rubric_loom_wizard import PtyWizard

    session = PtyWizard(["--brisk"], state=tmp_path / "state.json")
    session.wait_for(b"What do you want to do?")
    session.send(b"1\r")
    session.wait_for(b"THE DEMONSTRATION")
    session.send(b"3\r")
    session.wait_for(b"Course export check")
    session.wait_for(b"Start Unravel?")
    session.send(b"q\r")

    assert session.finish() == 0
    assert b"nothing was run." in session.stream
    assert b"Course export path" not in session.stream


@pytest.mark.skipif(os.name != "posix", reason="PTY is POSIX-only")
def test_unravel_mode_back_returns_to_the_two_door_landing(
    tmp_path: Path,
) -> None:
    from test_rubric_loom_wizard import PtyWizard

    session = PtyWizard(["--brisk"], state=tmp_path / "state.json")
    session.wait_for_count(b"What do you want to do?", 1)
    session.send(b"1\r")
    session.wait_for(b"How would you like to begin?")
    session.send(b"b\r")
    session.wait_for_count(b"What do you want to do?", 2)
    session.send(b"q\r")
    assert session.finish() == 0
    assert b"nothing was run." in session.stream
