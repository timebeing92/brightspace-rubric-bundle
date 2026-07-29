"""Rubric Loom wizard (R3): the wizard is a guided surface over the
Unravel orchestrator's CLI and progress events — same artifacts as the
CLI (the R3 exit condition), honest peeking, plain-pipe discipline,
family voice verbatim, and graceful failure/interruption."""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import pty
import re
import select
import signal
import struct
import subprocess
import sys
import time

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
WIZARD = SCRIPTS / "rubric_loom_wizard.py"
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "tiny_rubrics_export"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def run_wizard(
    *args: str, state: Path | None = None, cwd: Path | None = None
) -> subprocess.CompletedProcess[bytes]:
    env = dict(os.environ)
    env["RUBRIC_LOOM_STATE"] = str(state) if state else os.devnull
    env.pop("NO_COLOR", None)
    return subprocess.run(
        [sys.executable, str(WIZARD), *args],
        cwd=cwd or REPO_ROOT,
        capture_output=True,
        check=False,
        env=env,
        stdin=subprocess.DEVNULL,
    )


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "run_rubric_bundle.py"), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_runner_roots_keep_mutable_state_outside_the_bundle(
    tmp_path: Path,
) -> None:
    user_data = tmp_path / "user-data"
    private_venv = user_data / "runtime" / ".venv"
    env = dict(os.environ)
    env["RUBRIC_LOOM_USER_DATA"] = str(user_data)
    env["RUBRIC_LOOM_VENV"] = str(private_venv)
    probe = """
import json
import rubric_loom_wizard as wizard
import rubric_loom_weave as weave
print(json.dumps({
    "wizard_user_data": str(wizard.USER_DATA_ROOT),
    "wizard_input": str(wizard.INPUT_LANE),
    "wizard_output": str(wizard.OUTPUT_LANE),
    "wizard_state": str(wizard.STATE_PATH),
    "wizard_cache": str(wizard.RELEASE_CACHE_PATH),
    "wizard_venv": str(wizard.VENV_ROOT),
    "wizard_single": str(wizard.default_bundle_dir("one")),
    "wizard_bulk": str(wizard.default_bulk_dir(wizard.USER_DATA_ROOT / "batch")),
    "weave_user_data": str(weave.USER_DATA_ROOT),
    "weave_input": str(weave.INPUT_LANE),
    "weave_output": str(weave.OUTPUT_LANE),
    "weave_log": str(weave.LOG_LANE),
    "weave_result": str(weave.default_bundle_dir("one")),
}))
"""
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=SCRIPTS,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    paths = json.loads(result.stdout)
    assert paths == {
        "wizard_user_data": str(user_data),
        "wizard_input": str(user_data / "input"),
        "wizard_output": str(user_data / "output"),
        "wizard_state": str(user_data / "output" / ".rubric_loom_wizard_state.json"),
        "wizard_cache": str(
            user_data / "output" / "update-cache" / "release_check.json"
        ),
        "wizard_venv": str(private_venv),
        "wizard_single": str(user_data / "output" / "one__rubric_bundle"),
        "wizard_bulk": str(user_data / "output" / "batch__bulk_unravel"),
        "weave_user_data": str(user_data),
        "weave_input": str(user_data / "input"),
        "weave_output": str(user_data / "output"),
        "weave_log": str(user_data / "output" / "logs"),
        "weave_result": str(user_data / "output" / "one__weave_bundle"),
    }
    source = WIZARD.read_text(encoding="utf-8")
    assert '"--venv"' in source
    assert "str(VENV_ROOT)" in source


def test_runner_user_data_root_receives_default_outputs(
    tmp_path: Path,
) -> None:
    user_data = tmp_path / "user-data"
    env = dict(os.environ)
    env["RUBRIC_LOOM_USER_DATA"] = str(user_data)
    env["RUBRIC_LOOM_STATE"] = str(user_data / "output" / "state.json")
    result = subprocess.run(
        [
            sys.executable,
            str(WIZARD),
            "--source",
            str(FIXTURE),
            "--yes",
            "--plain",
            "--no-docx",
            "--no-update-check",
        ],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    output = user_data / "output" / "tiny_rubrics_export__rubric_bundle"
    assert (output / "tiny_rubrics_export__rubrics.xlsx").is_file()
    assert (output / "tiny_rubrics_export__rubrics.json").is_file()
    assert (output / "unravel_wizard.log").is_file()
    assert (user_data / "output" / "state.json").is_file()


# ---------------------------------------------------------------------------
# R3 exit condition: the wizard drives the full Unravel journey on the
# synthetic fixture with the same receipts as the CLI.
# ---------------------------------------------------------------------------
def test_wizard_matches_cli_artifacts_on_the_synthetic_fixture(
    tmp_path: Path,
) -> None:
    wizard_dir = tmp_path / "wizard-run"
    cli_dir = tmp_path / "cli-run"
    started = time.monotonic()
    result = run_wizard(
        "--source",
        str(FIXTURE),
        "--yes",
        "--output-dir",
        str(wizard_dir),
        "--plain",
    )
    elapsed = time.monotonic() - started
    assert result.returncode == 0, result.stdout + result.stderr
    # Plain/piped runs are unpaced: the display-only step pacing belongs
    # to the live TTY board alone.
    assert elapsed < 3.0, f"plain run took {elapsed:.1f}s; pacing leaked in"
    cli = run_cli(str(FIXTURE), "--output-dir", str(cli_dir))
    assert cli.returncode == 0, cli.stdout + cli.stderr

    wizard_files = {p.name for p in wizard_dir.iterdir()}
    cli_files = {p.name for p in cli_dir.iterdir()}
    # The wizard adds exactly one file of its own: the run log.
    assert wizard_files - {"unravel_wizard.log"} == cli_files

    # The rubrics JSON is byte-deterministic across runs (verified
    # empirically: two direct CLI runs produce identical bytes), so the
    # strongest honest assertion is full-document equality.
    wizard_doc = json.loads(
        (wizard_dir / "tiny_rubrics_export__rubrics.json").read_text(encoding="utf-8")
    )
    cli_doc = json.loads(
        (cli_dir / "tiny_rubrics_export__rubrics.json").read_text(encoding="utf-8")
    )
    assert wizard_doc == cli_doc
    assert len(wizard_doc["rubrics"]) == 2

    stdout = result.stdout.decode()
    # The approved line keeps its glyph in every mode.
    assert "The cloth is bound ✦" in stdout
    assert "Unravel finished successfully" in stdout
    assert re.search(r"Rubrics pulled\s+2", stdout)
    assert "Sample Rubric One" in stdout
    assert "Second Rubric / Two" in stdout
    assert re.search(r"Diagnostics\s+0", stdout)
    assert "start here" in stdout
    assert (wizard_dir / "unravel_wizard.log").is_file()


def _fixture_zip(tmp_path: Path, *, nested: bool = False, name: str = "export.zip") -> Path:
    """A zip built from the pinned fixture, with the rubric file at the
    top level or nested one folder down."""
    import zipfile

    archive = tmp_path / name
    xml_bytes = (FIXTURE / "rubrics_d2l.xml").read_bytes()
    with zipfile.ZipFile(archive, "w") as handle:
        member = "course/rubrics_d2l.xml" if nested else "rubrics_d2l.xml"
        handle.writestr(member, xml_bytes)
    return archive


def test_zip_sources_match_folder_parity(tmp_path: Path) -> None:
    """Wizard-level zip coverage: top-level and nested members both
    unravel to the same rubrics as the folder fixture."""
    for nested in (False, True):
        run_dir = tmp_path / ("nested" if nested else "top")
        archive = _fixture_zip(
            tmp_path, nested=nested, name=f"export-{'n' if nested else 't'}.zip"
        )
        result = run_wizard(
            "--source",
            str(archive),
            "--yes",
            "--no-docx",
            "--output-dir",
            str(run_dir),
        )
        assert result.returncode == 0, result.stdout + result.stderr
        stdout = result.stdout.decode()
        assert "rubrics sighted  2" in stdout.replace("   ", "  ")
        assert re.search(r"Rubrics pulled\s+2", stdout)
        assert re.search(r"Diagnostics\s+0", stdout)


def test_multi_member_zip_peek_matches_the_file_the_run_uses(
    tmp_path: Path,
) -> None:
    """When a zip carries several rubrics_d2l.xml members, the peek reads
    the shallowest one — the same preference the pinned extractor applies
    — so 'rubrics sighted' can never contradict the extraction."""
    import zipfile

    one_rubric = (
        b'<rubrics schemaversion="v2011"><rubric id="9" name="Nested" '
        b'type="1" scoring_method="3" uses_overall_score="True">'
        b'<description text_type="text"><text /></description>'
        b"<criteria_groups></criteria_groups></rubric></rubrics>"
    )
    archive = tmp_path / "multi.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        # Deliberately add the nested (decoy) member FIRST.
        handle.writestr("course/rubrics_d2l.xml", one_rubric)
        handle.writestr(
            "rubrics_d2l.xml", (FIXTURE / "rubrics_d2l.xml").read_bytes()
        )
    run_dir = tmp_path / "run"
    result = run_wizard(
        "--source",
        str(archive),
        "--yes",
        "--no-docx",
        "--output-dir",
        str(run_dir),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    stdout = result.stdout.decode()
    assert "rubrics sighted  2" in stdout.replace("   ", "  ")
    assert re.search(r"Rubrics pulled\s+2", stdout)
    assert re.search(r"Diagnostics\s+0", stdout)


def test_peek_sighted_count_matches_extraction(tmp_path: Path) -> None:
    import rubric_loom_wizard as wizard

    seen = wizard.peek(FIXTURE)
    assert seen["kind"] == "unpacked export folder"
    assert seen["evidence"] is True
    assert seen["title"] == ""  # the fixture ships no manifest
    cli_dir = tmp_path / "cli"
    cli = run_cli(str(FIXTURE), "--output-dir", str(cli_dir), "--no-docx")
    assert cli.returncode == 0
    document = json.loads(
        (cli_dir / "tiny_rubrics_export__rubrics.json").read_text(encoding="utf-8")
    )
    assert seen["sighted"] == len(document["rubrics"])


# ---------------------------------------------------------------------------
# Plain-pipe discipline
# ---------------------------------------------------------------------------
def test_piped_run_emits_no_escape_bytes(tmp_path: Path) -> None:
    result = run_wizard(
        "--source",
        str(FIXTURE),
        "--yes",
        "--output-dir",
        str(tmp_path / "run"),
    )
    assert result.returncode == 0
    assert b"\x1b" not in result.stdout
    assert b"\x1b" not in result.stderr


def test_piped_run_without_source_refuses_without_hanging() -> None:
    result = run_wizard()
    assert result.returncode == 2
    assert b"--source" in result.stderr
    assert b"\x1b" not in result.stderr


def test_yes_without_source_refuses_everywhere() -> None:
    """--yes promises no prompts; without a source it must refuse, never
    open the source menu (the family's --yes rule)."""
    result = run_wizard("--yes")
    assert result.returncode == 2
    assert b"--yes needs --source" in result.stderr


# ---------------------------------------------------------------------------
# Source-prompt UX
# ---------------------------------------------------------------------------
def test_pick_source_accepts_a_dragged_path_without_an_intermediate_menu(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import loom_ui
    import rubric_loom_wizard as wizard

    source = tmp_path / "Course Export"
    source.mkdir()
    prompts: list[str] = []

    monkeypatch.setattr(wizard, "input_lane_candidates", lambda: [])
    monkeypatch.setattr(
        loom_ui,
        "choose",
        lambda *args, **kwargs: pytest.fail(
            "source entry should not open a routing menu"
        ),
    )

    def answer(prompt: str) -> str:
        prompts.append(prompt)
        return f"'{source}'"

    monkeypatch.setattr("builtins.input", answer)

    assert wizard.pick_source(loom_ui.Term(plain=True), "") == source
    output = capsys.readouterr().out
    assert len(prompts) == 1
    assert "Course export path" in prompts[0]
    assert "Where is the course export you want to read?" not in output
    assert "Enter or drag a different file or folder path" not in output


def test_pick_source_keeps_demo_and_navigation_out_of_the_prompt(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import loom_ui
    import rubric_loom_wizard as wizard

    prompts: list[str] = []
    replies = iter(("d", "e"))
    monkeypatch.setattr(wizard, "input_lane_candidates", lambda: [])

    def answer(prompt: str) -> str:
        prompts.append(prompt)
        return next(replies)

    monkeypatch.setattr("builtins.input", answer)

    assert wizard.pick_source(loom_ui.Term(plain=True), "") is None
    output = capsys.readouterr().out
    assert len(prompts) == 2
    assert all(prompt.strip().endswith("Course export path:") for prompt in prompts)
    assert all("demonstration" not in prompt for prompt in prompts)
    assert all("Return =" not in prompt for prompt in prompts)
    assert "built-in demonstration" not in output
    assert "b = back" in output
    assert "e = exit" in output
    assert "I could not find that file or folder: d" in output


def test_pick_source_explains_a_real_last_used_path_above_the_plain_prompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import loom_ui
    import rubric_loom_wizard as wizard

    source = tmp_path / "last export"
    source.mkdir()
    prompts: list[str] = []
    monkeypatch.setattr(wizard, "input_lane_candidates", lambda: [])

    def answer(prompt: str) -> str:
        prompts.append(prompt)
        return ""

    monkeypatch.setattr("builtins.input", answer)

    assert wizard.pick_source(loom_ui.Term(plain=True), str(source)) == source
    output = capsys.readouterr().out
    compact = " ".join(output.split())
    assert f"Last used: {source}" in compact
    assert "Press Return to use it again." in compact
    assert len(prompts) == 1
    assert prompts[0].strip().endswith("Course export path:")
    assert "[" not in prompts[0]


def test_pick_source_back_returns_to_the_unravel_menu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import loom_ui
    import rubric_loom_wizard as wizard

    monkeypatch.setattr(wizard, "input_lane_candidates", lambda: [])
    monkeypatch.setattr("builtins.input", lambda _prompt: "b")

    assert (
        wizard.pick_source(loom_ui.Term(plain=True), "")
        is wizard.UNRAVEL_MENU
    )


def test_pick_source_reprompts_after_a_missing_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import loom_ui
    import rubric_loom_wizard as wizard

    source = tmp_path / "real export"
    source.mkdir()
    replies = iter((str(tmp_path / "missing.zip"), str(source)))
    monkeypatch.setattr(wizard, "input_lane_candidates", lambda: [])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(replies))

    assert wizard.pick_source(loom_ui.Term(plain=True), "") == source
    assert "I could not find that file or folder" in capsys.readouterr().out


def test_pick_source_keeps_input_lane_choices_in_the_same_prompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import loom_ui
    import rubric_loom_wizard as wizard

    first = tmp_path / "A.zip"
    second = tmp_path / "B.zip"
    first.touch()
    second.touch()
    monkeypatch.setattr(
        wizard, "input_lane_candidates", lambda: [first, second]
    )
    monkeypatch.setattr("builtins.input", lambda _prompt: "2")

    assert wizard.pick_source(loom_ui.Term(plain=True), "") == second
    output = capsys.readouterr().out
    assert "Ready in the input folder" in output
    assert "Enter 1-2" in output


def test_yes_ignores_remembered_answers(tmp_path: Path) -> None:
    """Headless runs mirror the CLI exactly: a remembered no-DOCX choice
    must not silently strip the DOCX from a plain --yes run."""
    state = tmp_path / "state.json"
    state.write_text(
        json.dumps({"source": str(FIXTURE), "docx": False}), encoding="utf-8"
    )
    run_dir = tmp_path / "run"
    result = run_wizard(
        "--source",
        str(FIXTURE),
        "--yes",
        "--output-dir",
        str(run_dir),
        state=state,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (run_dir / "tiny_rubrics_export__rubrics.docx").is_file()
    assert b"review DOCX  yes" in result.stdout.replace(b"   ", b"  ")


def test_default_bundle_dir_is_repo_anchored(tmp_path: Path) -> None:
    """The doctor vouches for the repo's output lane, so that is where an
    un-flagged run must write — from any cwd (AGENTS.md lane posture)."""
    import shutil

    label = f"wiztest_{os.getpid()}"
    expected = REPO_ROOT / "output" / f"{label}__rubric_bundle"
    if expected.exists():
        shutil.rmtree(expected)
    try:
        result = subprocess.run(
            [
                sys.executable,
                str(WIZARD),
                "--source",
                str(FIXTURE),
                "--yes",
                "--no-docx",
                "--label",
                label,
            ],
            cwd=tmp_path,  # a foreign cwd
            capture_output=True,
            check=False,
            env={**os.environ, "RUBRIC_LOOM_STATE": os.devnull},
            stdin=subprocess.DEVNULL,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert expected.is_dir()
        assert (expected / f"{label}__rubrics.json").is_file()
        assert not (tmp_path / "output").exists()
    finally:
        if expected.exists():
            shutil.rmtree(expected)


def test_doctor_flag_runs_standalone() -> None:
    result = run_wizard("--doctor")
    assert result.returncode == 0
    stdout = result.stdout.decode()
    assert "Rubric Loom doctor" in stdout
    assert "The loom is threaded." in stdout
    assert b"\x1b" not in result.stdout


def test_ordinary_environment_check_is_quiet_when_ready(capsys) -> None:
    import loom_ui
    import rubric_loom_wizard as wizard

    core_ok, docx_ok = wizard.ensure_environment(
        loom_ui.Term(plain=True),
        assume_yes=False,
    )
    assert core_ok is True
    assert docx_ok is True
    assert capsys.readouterr().out == ""


def test_missing_dependencies_offer_one_locked_local_repair(
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    from types import SimpleNamespace

    import loom_ui
    import rubric_loom_wizard as wizard

    available = {"jsonschema": False, "openpyxl": False, "docx": False}
    confirmations: list[str] = []

    monkeypatch.setattr(
        wizard,
        "module_present",
        lambda name: available.get(name, True),
    )
    monkeypatch.setattr(wizard, "running_in_local_venv", lambda: True)

    def confirm(term, prompt, **kwargs):
        del term, kwargs
        confirmations.append(prompt)
        return True

    def install(command, *, cwd, check):
        assert command[:4] == [
            sys.executable,
            "-m",
            "pip",
            "install",
        ]
        assert command[-2:] == ["-r", str(wizard.RUNTIME_REQUIREMENTS)]
        assert cwd == wizard.REPO_ROOT
        assert check is False
        available.update({name: True for name in available})
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(loom_ui, "confirm", confirm)
    monkeypatch.setattr(wizard.subprocess, "run", install)

    core_ok, docx_ok = wizard.ensure_environment(
        loom_ui.Term(plain=True),
        assume_yes=False,
    )
    output = capsys.readouterr().out
    assert core_ok is True
    assert docx_ok is True
    assert confirmations == ["Install the required Python packages now?"]
    assert "One-time setup needed" in output
    assert "jsonschema, openpyxl, python-docx" in output
    assert "requirements-lock.txt" in output
    assert "Environment ready" in output


def test_new_release_notice_is_informative_and_never_installs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    import loom_ui
    import release_check
    import rubric_loom_wizard as wizard

    cache = tmp_path / "release_check.json"
    marked: list[str] = []
    monkeypatch.setattr(wizard, "RELEASE_CACHE_PATH", cache)
    monkeypatch.setattr(wizard, "installed_version", lambda: "1.2.1")
    monkeypatch.setattr(
        release_check,
        "check_latest_release",
        lambda **kwargs: release_check.ReleaseStatus(
            state="update_available",
            current_version="1.2.1",
            latest_version="1.3.0",
            latest_tag="v1.3.0",
            release_name="Rubric Loom v1.3.0",
            release_url=(
                "https://github.com/timebeing92/"
                "brightspace-rubric-bundle/releases/tag/v1.3.0"
            ),
        ),
    )
    monkeypatch.setattr(release_check, "notice_is_due", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        release_check,
        "mark_notified",
        lambda path, *, latest_version: marked.append(latest_version),
    )

    wizard.report_release_check(
        loom_ui.Term(plain=True),
        force=False,
        offer_open=False,
    )
    output = capsys.readouterr().out
    assert "A newer Rubric Loom release is available" in output
    assert "v1.2.1" in output
    assert "v1.3.0" in output
    assert "Nothing was installed" in output
    assert marked == ["1.3.0"]


# ---------------------------------------------------------------------------
# Failure paths
# ---------------------------------------------------------------------------
def test_missing_source_exits_2(tmp_path: Path) -> None:
    result = run_wizard(
        "--source",
        str(tmp_path / "absent"),
        "--yes",
        "--output-dir",
        str(tmp_path / "run"),
    )
    assert result.returncode == 2
    assert b"source not found" in result.stdout


def test_source_without_evidence_exits_3_with_honest_copy(
    tmp_path: Path,
) -> None:
    empty = tmp_path / "no-rubrics-here"
    empty.mkdir()
    (empty / "readme.txt").write_text("nothing woven", encoding="utf-8")
    result = run_wizard(
        "--source",
        str(empty),
        "--yes",
        "--output-dir",
        str(tmp_path / "run"),
    )
    assert result.returncode == 3
    stdout = result.stdout.decode()
    assert "no rubric evidence sighted" in stdout
    assert "A thread snapped — the scroll below tells why." in stdout
    assert "nothing to unravel" in stdout  # the orchestrator's own words
    assert "Bring a Brightspace course-export ZIP" in stdout


def test_failure_into_occupied_dir_claims_no_stale_delivery(
    tmp_path: Path,
) -> None:
    """A failing run into a folder holding a previous run's artifacts must
    not present those stale files as this run's delivery: delivery claims
    are grounded in this run's completed steps."""
    run_dir = tmp_path / "bundle"
    first = run_wizard(
        "--source", str(FIXTURE), "--yes", "--output-dir", str(run_dir)
    )
    assert first.returncode == 0, first.stdout + first.stderr
    assert (run_dir / "tiny_rubrics_export__rubrics.docx").is_file()

    empty = tmp_path / "no-rubrics-here"
    empty.mkdir()
    (empty / "readme.txt").write_text("nothing woven", encoding="utf-8")
    second = run_wizard(
        "--source",
        str(empty),
        "--yes",
        "--label",
        "tiny_rubrics_export",  # same label: stale artifact names match
        "--output-dir",
        str(run_dir),
    )
    assert second.returncode == 3
    stdout = second.stdout.decode()
    assert "A thread snapped — the scroll below tells why." in stdout
    assert "delivered before the snap" not in stdout
    assert "tiny_rubrics_export__rubrics" not in stdout.split("failed step")[-1]


def test_corrupt_zip_peek_says_unreadable_and_run_fails_cleanly(
    tmp_path: Path,
) -> None:
    bad = tmp_path / "corrupt.zip"
    bad.write_bytes(b"PK\x03\x04 this is not really a zip")
    result = run_wizard(
        "--source", str(bad), "--yes", "--output-dir", str(tmp_path / "run")
    )
    assert result.returncode == 1
    stdout = result.stdout.decode()
    assert "not a readable zip archive" in stdout  # peek tells the truth
    assert "A thread snapped — the scroll below tells why." in stdout


def test_zero_sighted_evidence_warns_before_running(tmp_path: Path) -> None:
    hollow = tmp_path / "hollow-export"
    hollow.mkdir()
    (hollow / "rubrics_d2l.xml").write_text(
        '<rubrics schemaversion="v2011"></rubrics>', encoding="utf-8"
    )
    result = run_wizard(
        "--source", str(hollow), "--yes", "--output-dir", str(tmp_path / "run")
    )
    stdout = result.stdout.decode()
    assert "rubrics sighted  0" in stdout.replace("   ", "  ")
    assert "no rubric entries were sighted" in stdout
    # The pinned extractor refuses zero-rubric sources; the wizard shows
    # that refusal honestly rather than inventing an empty success.
    assert result.returncode == 1
    assert "A thread snapped — the scroll below tells why." in stdout


def test_failure_card_partial_delivery_and_no_docx_hint(tmp_path: Path) -> None:
    """Unit-level: a DOCX-step failure names delivered artifacts and the
    --no-docx retry (the frame's Partial obligation)."""
    import contextlib

    import loom_ui
    import run_rubric_bundle as unravel
    import rubric_loom_wizard as wizard

    out_dir = tmp_path / "bundle"
    out_dir.mkdir()
    (out_dir / "demo__rubrics.xlsx").write_bytes(b"wb")
    (out_dir / "demo__rubrics.json").write_text("{}", encoding="utf-8")
    log_path = out_dir / "unravel_wizard.log"
    log_path.write_text("log\n", encoding="utf-8")

    term = loom_ui.Term(plain=True)
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        wizard.failure_card(
            term,
            1,
            {
                "event": "run_end",
                "status": "error",
                "message": "rubrics_to_docx.py failed: boom",
                "issues": [
                    {
                        "step": unravel.STEP_DOCX,
                        "status": "failed",
                        "message": "rubrics_to_docx.py failed: boom",
                    }
                ],
            },
            unravel.STEP_DOCX,
            "rubrics_to_docx.py failed: boom",
            [unravel.STEP_LOCATE, unravel.STEP_EXTRACT, unravel.STEP_VALIDATE],
            out_dir,
            "demo",
            True,
            log_path,
        )
    text = buffer.getvalue()
    assert "A thread snapped — the scroll below tells why." in text
    assert "delivered before the snap" in text
    assert "demo__rubrics.xlsx" in text
    assert "demo__rubrics.json" in text
    assert "demo__rubrics.docx" not in text.split("delivered")[-1]
    assert "--no-docx" in text
    assert "--doctor" in text
    assert "\x1b" not in text


def test_rubric_names_from_contract_fails_closed_on_damaged_delivery(
    tmp_path: Path,
) -> None:
    import rubric_loom_wizard as wizard

    contract = tmp_path / "rubrics.json"
    contract.write_text("{not-json", encoding="utf-8")
    assert wizard.rubric_names_from_contract(contract) == ()

    contract.write_text('{"rubrics": "not-a-list"}', encoding="utf-8")
    assert wizard.rubric_names_from_contract(contract) == ()

    contract.write_text(
        '{"rubrics": [{"name": " Named "}, {"name": ""}]}',
        encoding="utf-8",
    )
    assert wizard.rubric_names_from_contract(contract) == (
        "Named",
        "(unnamed rubric)",
    )


def test_open_folder_offer_is_explicit_and_uses_the_output_folder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import loom_ui
    import rubric_loom_wizard as wizard

    opened: list[list[str]] = []
    term = loom_ui.Term(plain=True)
    term.plain = False
    monkeypatch.setattr(
        loom_ui,
        "confirm",
        lambda _term, prompt, *, default=False: (
            prompt == "Open the folder containing these files?"
            and default is True
        ),
    )
    monkeypatch.setattr(
        wizard,
        "folder_open_command",
        lambda path: ["folder-opener", str(path)],
    )
    monkeypatch.setattr(
        wizard.subprocess,
        "run",
        lambda command, *, check=False: (
            opened.append(command)
            or wizard.subprocess.CompletedProcess(command, 0)
        ),
    )

    wizard.offer_open_folder(term, tmp_path)

    assert opened == [["folder-opener", str(tmp_path)]]


def test_open_folder_offer_never_runs_in_plain_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import loom_ui
    import rubric_loom_wizard as wizard

    monkeypatch.setattr(
        loom_ui,
        "confirm",
        lambda *args, **kwargs: pytest.fail("plain runs must never prompt"),
    )
    monkeypatch.setattr(
        wizard.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("plain runs must never open a GUI"),
    )

    wizard.offer_open_folder(loom_ui.Term(plain=True), tmp_path)


def test_typed_path_accepts_dragged_and_quoted_forms(tmp_path: Path) -> None:
    """macOS drag-and-drop produces backslash-escaped paths; quoting is
    the other common paste form. Both must resolve."""
    import rubric_loom_wizard as wizard

    spaced = tmp_path / "space dir" / "my export"
    spaced.mkdir(parents=True)
    escaped = str(spaced).replace(" ", "\\ ")
    assert wizard.parse_typed_path(escaped) == spaced
    assert wizard.parse_typed_path(f"'{spaced}'") == spaced
    assert wizard.parse_typed_path(f'"{spaced}"') == spaced
    assert wizard.parse_typed_path(str(spaced)) == spaced
    assert wizard.parse_typed_path("  ") is None


def test_accent_is_confined_to_the_prompt_components() -> None:
    """The frame's rule: accent color for prompts only. The wizard and the
    art never call the accent; only loom_ui's prompt functions do, and no
    art pixel maps to the accent index."""
    import loom_art
    import loom_ui

    wizard_src = (SCRIPTS / "rubric_loom_wizard.py").read_text(encoding="utf-8")
    art_src = (SCRIPTS / "loom_art.py").read_text(encoding="utf-8")
    assert ".accent(" not in wizard_src
    assert ".accent(" not in art_src
    assert loom_ui.ACCENT not in loom_art.PALETTE.values()


# ---------------------------------------------------------------------------
# Remembered answers
# ---------------------------------------------------------------------------
def test_state_is_remembered_and_corruption_tolerated(tmp_path: Path) -> None:
    state = tmp_path / "state.json"
    result = run_wizard(
        "--source",
        str(FIXTURE),
        "--yes",
        "--no-docx",
        "--output-dir",
        str(tmp_path / "run-a"),
        state=state,
    )
    assert result.returncode == 0
    payload = json.loads(state.read_text(encoding="utf-8"))
    assert payload["schema"] == "rubric_loom.state/2"
    assert payload["doors"]["unravel"]["source"] == str(FIXTURE)
    assert payload["doors"]["unravel"]["docx"] is False

    state.write_text("{not-json", encoding="utf-8")
    result = run_wizard(
        "--source",
        str(FIXTURE),
        "--yes",
        "--output-dir",
        str(tmp_path / "run-b"),
        state=state,
    )
    assert result.returncode == 0  # corruption never blocks a run


# ---------------------------------------------------------------------------
# Interactive PTY journey
# ---------------------------------------------------------------------------
pytestmark_pty = pytest.mark.skipif(os.name != "posix", reason="PTY is POSIX-only")


class PtyWizard:
    def __init__(
        self,
        args: list[str],
        state: Path,
        *,
        wizard: Path = WIZARD,
        cwd: Path = REPO_ROOT,
        env_overrides: dict[str, str] | None = None,
    ) -> None:
        import fcntl
        import termios

        self.master, slave = pty.openpty()
        fcntl.ioctl(self.master, termios.TIOCSWINSZ, struct.pack("HHHH", 32, 100, 0, 0))
        env = dict(os.environ)
        env["TERM"] = "xterm-256color"
        env["RUBRIC_LOOM_STATE"] = str(state)
        env["RUBRIC_LOOM_NO_RELEASE_CHECK"] = "1"
        env.pop("NO_COLOR", None)
        if env_overrides:
            env.update(env_overrides)
        self.proc = subprocess.Popen(
            [sys.executable, str(wizard), *args],
            cwd=cwd,
            stdin=slave,
            stdout=slave,
            stderr=slave,
            env=env,
            close_fds=True,
        )
        os.close(slave)
        self.stream = b""

    def drain(self, timeout: float = 0.1) -> None:
        while True:
            ready, _, _ = select.select([self.master], [], [], timeout)
            if not ready:
                return
            try:
                chunk = os.read(self.master, 65536)
            except OSError:
                return
            if not chunk:
                return
            self.stream += chunk
            timeout = 0.02

    def wait_for(self, token: bytes, timeout: float = 15.0) -> None:
        self.wait_for_count(token, 1, timeout)

    def wait_for_count(self, token: bytes, count: int, timeout: float = 15.0) -> None:
        """Wait until the cumulative stream holds `count` occurrences —
        the honest way to await a REPEATED screen (a bare substring check
        succeeds instantly on the previous rendering)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.stream.count(token) >= count:
                return
            self.drain(0.1)
        raise AssertionError(
            f"saw {token!r} x{self.stream.count(token)}, wanted {count}; "
            f"tail: {self.stream[-600:]!r}"
        )

    def send(self, data: bytes) -> None:
        os.write(self.master, data)

    def finish(self, timeout: float = 20.0) -> int:
        deadline = time.monotonic() + timeout
        while self.proc.poll() is None and time.monotonic() < deadline:
            self.drain(0.1)
        try:
            os.close(self.master)
        except OSError:
            pass
        return self.proc.wait(timeout=5)


@pytestmark_pty
def test_pty_guided_journey_reaches_the_bound_cloth(tmp_path: Path) -> None:
    """The full journey keeps art, checks setup quietly, and proceeds
    directly into the source/review/run flow."""
    out_dir = tmp_path / "run"
    session = PtyWizard(
        ["--source", str(FIXTURE), "--output-dir", str(out_dir)],
        state=tmp_path / "state.json",
    )
    session.wait_for(b"R U B R I C")
    session.wait_for(b"L O O M")
    session.wait_for(b"Ready to unravel")
    session.wait_for(b"tiny_rubrics_export__rubrics.docx")
    session.wait_for(b"Start Unravel?")
    board_started = time.monotonic()
    session.send(b"\r")
    session.wait_for("The cloth is bound ✦".encode("utf-8"), timeout=30.0)
    session.wait_for(b"Rubrics pulled")
    session.wait_for(b"Sample Rubric One")
    session.wait_for(b"Second Rubric / Two")
    session.wait_for(b"Open the folder containing these files?")
    session.send(b"n\r")
    paced_elapsed = time.monotonic() - board_started
    code = session.finish()
    assert code == 0
    assert (out_dir / "tiny_rubrics_export__rubrics.docx").is_file()
    stream = session.stream.decode("utf-8", "replace")
    assert "Python interpreter" not in stream
    assert "Rubric Loom doctor" not in stream
    assert "Review the output" in stream
    assert "The unravelling" in stream
    assert "Reading the weave" in stream  # flavor from the approved sample
    # Display-only pacing: four steps held >= MIN_STEP_SECONDS each, so a
    # human can actually read the flavor lines (the frame's obligation).
    assert paced_elapsed >= 3.0, f"board played out in {paced_elapsed:.1f}s"


@pytestmark_pty
def test_pty_landing_q_leaves_without_running(tmp_path: Path) -> None:
    session = PtyWizard([], state=tmp_path / "state.json")
    session.wait_for(b"R U B R I C")
    session.wait_for(b"L O O M")
    session.wait_for(b"Choose what you want to do")
    session.wait_for(b"UNRAVEL")
    session.wait_for(b"WEAVE")
    session.wait_for(b"What do you want to do?")
    session.send(b"q\r")
    code = session.finish()
    assert code == 0
    assert b"nothing was run." in session.stream
    assert b"Python interpreter" not in session.stream
    assert b"\x1b[38;5;97m" in session.stream  # violet frame in the Loom art
    assert session.stream.index(b"R U B R I C") < session.stream.index(
        b"Choose what you want to do"
    )


@pytestmark_pty
def test_pty_back_navigation_walks_every_edge(tmp_path: Path) -> None:
    """The review card changes one item at a time; b exits an edit without
    changing it and returns from the card to the read-only source check."""
    out_dir = tmp_path / "run"
    session = PtyWizard(
        ["--brisk", "--source", str(FIXTURE), "--output-dir", str(out_dir)],
        state=tmp_path / "state.json",
    )
    review = b"Start Unravel?"
    source_check = b"Course export check"

    session.wait_for_count(review, 1)
    session.send(b"2\r")
    session.wait_for(b"Output name (used at the start of each filename)")
    session.send(b"b\r")
    session.wait_for_count(review, 2)
    session.send(b"3\r")
    session.wait_for(b"Save folder")
    session.send(b"b\r")
    session.wait_for_count(review, 3)
    session.send(b"4\r")
    session.wait_for(b"Create the reviewer DOCX?")
    session.send(b"b\r")
    session.wait_for_count(review, 4)
    session.send(b"b\r")
    session.wait_for_count(source_check, 2)
    session.wait_for_count(review, 5)
    session.send(b"q\r")
    code = session.finish()
    assert code == 0
    assert b"nothing was run." in session.stream
    assert not (out_dir / "tiny_rubrics_export__rubrics.json").exists()


@pytestmark_pty
def test_pty_interrupt_rests_the_shuttle(tmp_path: Path) -> None:
    for attempt in range(3):
        out_dir = tmp_path / f"run-{attempt}"
        session = PtyWizard(
            [
                "--brisk",
                "--yes",
                "--source",
                str(FIXTURE),
                "--output-dir",
                str(out_dir),
            ],
            state=tmp_path / "state.json",
        )
        session.wait_for(b"The unravelling")
        time.sleep(0.05)
        session.proc.send_signal(signal.SIGINT)
        code = session.finish()
        if code == 0:
            time.sleep(0.1)
            continue  # the fast run won the race; try again
        assert code == 130
        assert b"The shuttle rests" in session.stream
        return
    pytest.skip("the run finished before SIGINT landed on three attempts")
