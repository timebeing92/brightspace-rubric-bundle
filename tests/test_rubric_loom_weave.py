"""Two-door Rubric Loom coverage for the bounded Weave journey."""
from __future__ import annotations

import io
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
WIZARD = SCRIPTS / "rubric_loom_wizard.py"
WEAVE = SCRIPTS / "run_weave_bundle.py"
EXPLICIT = (
    REPO_ROOT
    / "tests"
    / "fixtures"
    / "rubric_authoring"
    / "three_level_explicit.md"
)
AMBIGUOUS = (
    REPO_ROOT
    / "tests"
    / "fixtures"
    / "rubric_authoring"
    / "missing_scoring_and_weights.md"
)
UNRAVEL = REPO_ROOT / "tests" / "fixtures" / "tiny_rubrics_export"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def run_wizard(
    *args: str,
    state: Path | None = None,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[bytes]:
    env = dict(os.environ)
    env["RUBRIC_LOOM_STATE"] = str(state) if state else os.devnull
    if state is not None:
        env["RUBRIC_LOOM_LOG_DIR"] = str(state.parent / "logs")
    env.pop("NO_COLOR", None)
    env.update(extra_env or {})
    return subprocess.run(
        [sys.executable, str(WIZARD), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
        env=env,
        stdin=subprocess.DEVNULL,
    )


def run_cli(*args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, str(WEAVE), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
    )


def weave_args(source: Path, output: Path) -> list[str]:
    return [
        "--door",
        "weave",
        "--source",
        str(source),
        "--yes",
        "--approve-weave",
        "--plain",
        "--output-dir",
        str(output),
    ]


def test_headless_weave_matches_cli_artifacts_and_receipts(tmp_path: Path) -> None:
    tui_dir = tmp_path / "tui"
    cli_dir = tmp_path / "cli"
    tui = run_wizard(*weave_args(EXPLICIT, tui_dir), state=tmp_path / "state.json")
    assert tui.returncode == 0, tui.stdout + tui.stderr
    cli = run_cli(str(EXPLICIT), "--output-dir", str(cli_dir))
    assert cli.returncode == 0, cli.stdout + cli.stderr

    expected = {
        "rubric_package.zip",
        "rubrics_d2l.xml",
        "normalized_rubric_authoring.json",
        "rubric_mapping.md",
        "diagnostics.json",
        "producer_run_receipt.json",
        "run_receipt.json",
    }
    assert {path.name for path in tui_dir.iterdir() if path.is_file()} == expected
    assert {path.name for path in cli_dir.iterdir() if path.is_file()} == expected
    for name in expected:
        assert (tui_dir / name).read_bytes() == (cli_dir / name).read_bytes(), name

    text = tui.stdout.decode()
    assert "numeric_level_header" in text
    assert "start here" in text
    assert "rubric_package.zip" in text
    assert "Nothing was imported. Activity attachment remains manual." in text
    assert len(list((tmp_path / "logs").glob("*__weave_wizard.log"))) == 1


def test_snapshot_preserves_explicit_source_label_and_cli_receipt_semantics(
    tmp_path: Path,
) -> None:
    source_label = "Operator Chosen Rubric Source"
    tui_dir = tmp_path / "tui"
    cli_dir = tmp_path / "cli"
    tui = run_wizard(
        *weave_args(EXPLICIT, tui_dir),
        "--source-label",
        source_label,
        state=tmp_path / "state.json",
    )
    cli = run_cli(
        str(EXPLICIT),
        "--output-dir",
        str(cli_dir),
        "--source-label",
        source_label,
    )
    assert tui.returncode == cli.returncode == 0
    for name in (
        "rubric_package.zip",
        "rubrics_d2l.xml",
        "normalized_rubric_authoring.json",
        "rubric_mapping.md",
        "diagnostics.json",
        "producer_run_receipt.json",
        "run_receipt.json",
    ):
        assert (tui_dir / name).read_bytes() == (cli_dir / name).read_bytes()
    receipt = json.loads((tui_dir / "run_receipt.json").read_text(encoding="utf-8"))
    assert receipt["source"]["observed_identity"]["source_label_sha256"] == (
        hashlib.sha256(source_label.encode("utf-8")).hexdigest()
    )
    serialized = json.dumps(receipt, sort_keys=True)
    assert "approved-source" not in serialized
    assert "rubric-loom-weave-source" not in serialized


def test_headless_weave_requires_named_final_approval(tmp_path: Path) -> None:
    output = tmp_path / "refused"
    result = run_wizard(
        "--door",
        "weave",
        "--source",
        str(EXPLICIT),
        "--yes",
        "--plain",
        "--output-dir",
        str(output),
    )
    assert result.returncode == 2
    assert b"Producer preflight" in result.stdout
    assert b"--approve-weave" in result.stderr
    assert not output.exists()


def test_ambiguous_source_refuses_without_fallback_and_writes_nothing(
    tmp_path: Path,
) -> None:
    output = tmp_path / "refused"
    result = run_wizard(*weave_args(AMBIGUOUS, output))
    assert result.returncode == 2
    text = result.stdout.decode()
    assert "SCORING_METADATA_REQUIRED" in text
    assert "CRITERION_WEIGHT_REQUIRED" in text
    assert any(
        "written" in line and "nothing" in line
        for line in text.splitlines()
    )
    assert not output.exists()


def test_explicit_fallback_approvals_are_visible_and_receipted(
    tmp_path: Path,
) -> None:
    output = tmp_path / "approved"
    result = run_wizard(
        *weave_args(AMBIGUOUS, output),
        "--allow-even-spacing",
        "--allow-equal-weights",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    text = result.stdout.decode()
    assert "approved_even_spacing" in text
    assert "approved_equal_weights" in text
    assert "EVEN_SPACING_APPROVED" in text
    assert "EQUAL_WEIGHTS_APPROVED" in text
    producer_receipt = json.loads(
        (output / "producer_run_receipt.json").read_text(encoding="utf-8")
    )
    assert producer_receipt["parameters"]["allow_even_spacing"] is True
    assert producer_receipt["parameters"]["allow_equal_weights"] is True


@pytest.mark.parametrize(
    "extra_env",
    [
        {"NO_COLOR": "1"},
        {"TERM": "dumb"},
    ],
)
def test_weave_degrades_cleanly_without_color(
    tmp_path: Path,
    extra_env: dict[str, str],
) -> None:
    args = weave_args(EXPLICIT, tmp_path / "out")
    args.remove("--plain")
    result = run_wizard(
        *args,
        extra_env=extra_env,
    )
    assert result.returncode == 0
    assert b"\x1b" not in result.stdout
    assert b"\x1b" not in result.stderr


def test_invalid_weave_extension_refuses_before_preflight(tmp_path: Path) -> None:
    source = tmp_path / "rubric.txt"
    source.write_text("unsupported", encoding="utf-8")
    output = tmp_path / "out"
    result = run_wizard(*weave_args(source, output))
    assert result.returncode == 2
    assert b"DOCX, Markdown, or JSON" in result.stdout
    assert not output.exists()


def test_failed_run_never_claims_stale_artifacts(tmp_path: Path) -> None:
    output = tmp_path / "occupied"
    output.mkdir()
    (output / "rubric_package.zip").write_bytes(b"stale")
    result = run_wizard(*weave_args(EXPLICIT, output))
    assert result.returncode == 2
    text = result.stdout.decode()
    assert "no artifact is claimed from an incomplete Weave run" in text
    assert "start here" not in text
    assert (output / "rubric_package.zip").read_bytes() == b"stale"


def test_tui_preserves_producer_symlink_output_refusal(
    tmp_path: Path,
) -> None:
    target = tmp_path / "target"
    target.mkdir()
    sentinel = target / "SENTINEL"
    sentinel.write_text("keep", encoding="utf-8")
    alias = tmp_path / "alias"
    alias.symlink_to(target, target_is_directory=True)

    tui = run_wizard(
        *weave_args(EXPLICIT, alias),
        "--force",
    )
    assert tui.returncode == 2
    assert sentinel.read_text(encoding="utf-8") == "keep"
    assert b"start here" not in tui.stdout

    direct_target = tmp_path / "direct-target"
    direct_target.mkdir()
    direct_sentinel = direct_target / "SENTINEL"
    direct_sentinel.write_text("keep", encoding="utf-8")
    direct_alias = tmp_path / "direct-alias"
    direct_alias.symlink_to(direct_target, target_is_directory=True)
    cli = run_cli(
        str(EXPLICIT),
        "--output-dir",
        str(direct_alias),
        "--force",
    )
    assert cli.returncode == tui.returncode == 2
    assert direct_sentinel.read_text(encoding="utf-8") == "keep"


def test_progress_log_refuses_a_symlink_without_touching_its_target(
    tmp_path: Path,
) -> None:
    import loom_progress
    import loom_ui

    sentinel = tmp_path / "SENTINEL"
    sentinel.write_text("keep", encoding="utf-8")
    log_alias = tmp_path / "run.log"
    log_alias.symlink_to(sentinel)
    result = loom_progress.consume(
        loom_ui.Term(plain=True),
        [sys.executable, "-c", "raise SystemExit(99)"],
        log_alias,
        log_title="must not run",
        exclusive_log=True,
    )
    assert result.return_code == 2
    assert "safe local run log" in result.failed_message
    assert sentinel.read_text(encoding="utf-8") == "keep"


def test_delivery_claims_fail_closed_when_receipted_bytes_change(
    tmp_path: Path,
) -> None:
    import rubric_loom_weave as journey

    output = tmp_path / "out"
    result = run_cli(str(EXPLICIT), "--output-dir", str(output), "--progress-events")
    assert result.returncode == 0, result.stdout + result.stderr
    events = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    run_end = events[-1]
    assert journey.grounded_outputs(run_end)["import_zip"].is_file()
    (output / "rubric_package.zip").write_bytes(b"tampered")
    grounded = journey.grounded_outputs(run_end)
    assert "import_zip" not in grounded

    import loom_ui

    buffer = io.StringIO()
    from contextlib import redirect_stdout

    with redirect_stdout(buffer):
        assert journey.results_card(
            loom_ui.Term(plain=True),
            run_end,
            tmp_path / "log",
        ) is False
    assert "start here" not in buffer.getvalue()


def test_delivery_claims_require_the_receipted_artifact_role(
    tmp_path: Path,
) -> None:
    import rubric_loom_weave as journey

    output = tmp_path / "out"
    result = run_cli(str(EXPLICIT), "--output-dir", str(output), "--progress-events")
    assert result.returncode == 0, result.stdout + result.stderr
    run_end = [
        json.loads(line) for line in result.stdout.splitlines() if line.strip()
    ][-1]
    receipt_path = output / "run_receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    package = next(
        item
        for item in receipt["emitted_files"]
        if item["path"] == "rubric_package.zip"
    )
    package["extensions"]["role"] = "normalized_authoring_contract"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    assert "import_zip" not in journey.grounded_outputs(run_end)


@pytest.mark.parametrize("emitted_files", [None, {}, "not-a-list"])
def test_delivery_claims_fail_closed_for_malformed_emitted_files(
    tmp_path: Path,
    emitted_files: object,
) -> None:
    import rubric_loom_weave as journey

    output = tmp_path / "out"
    result = run_cli(str(EXPLICIT), "--output-dir", str(output), "--progress-events")
    assert result.returncode == 0, result.stdout + result.stderr
    run_end = [
        json.loads(line) for line in result.stdout.splitlines() if line.strip()
    ][-1]
    receipt_path = output / "run_receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["emitted_files"] = emitted_files
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    assert journey.grounded_outputs(run_end) == {}


@pytest.mark.parametrize(
    "receipt_envelope",
    [None, [], ["not", "an", "object"], "not-an-object", 7, 2.5, True],
)
def test_delivery_claims_fail_closed_for_non_object_receipt_envelopes(
    tmp_path: Path,
    receipt_envelope: object,
) -> None:
    import rubric_loom_weave as journey

    output = tmp_path / "out"
    result = run_cli(str(EXPLICIT), "--output-dir", str(output), "--progress-events")
    assert result.returncode == 0, result.stdout + result.stderr
    run_end = [
        json.loads(line) for line in result.stdout.splitlines() if line.strip()
    ][-1]
    receipt_path = output / "run_receipt.json"
    receipt_path.write_text(json.dumps(receipt_envelope), encoding="utf-8")
    assert journey.grounded_outputs(run_end) == {}


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_run_id",
        "null_emitted_member",
        "emitted_member_missing_sha256",
        "emitted_member_wrong_bytes_type",
        "parameters_wrong_type",
    ],
)
def test_delivery_claims_require_the_complete_run_receipt_schema(
    tmp_path: Path,
    mutation: str,
) -> None:
    import rubric_loom_weave as journey

    output = tmp_path / "out"
    result = run_cli(str(EXPLICIT), "--output-dir", str(output), "--progress-events")
    assert result.returncode == 0, result.stdout + result.stderr
    run_end = [
        json.loads(line) for line in result.stdout.splitlines() if line.strip()
    ][-1]
    assert "import_zip" in journey.grounded_outputs(run_end)

    receipt_path = output / "run_receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if mutation == "missing_run_id":
        receipt.pop("run_id")
    elif mutation == "null_emitted_member":
        receipt["emitted_files"].append(None)
    elif mutation == "emitted_member_missing_sha256":
        invalid = dict(receipt["emitted_files"][0])
        invalid.pop("sha256")
        receipt["emitted_files"].append(invalid)
    elif mutation == "emitted_member_wrong_bytes_type":
        invalid = dict(receipt["emitted_files"][0])
        invalid["bytes"] = str(invalid["bytes"])
        receipt["emitted_files"].append(invalid)
    else:
        receipt["parameters"] = []
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    assert journey.grounded_outputs(run_end) == {}


@pytest.mark.parametrize(
    "schema_failure",
    ["missing", "malformed_json", "invalid_schema", "wrong_contract"],
)
def test_delivery_claims_fail_closed_when_run_schema_cannot_validate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    schema_failure: str,
) -> None:
    import rubric_loom_weave as journey

    output = tmp_path / "out"
    result = run_cli(str(EXPLICIT), "--output-dir", str(output), "--progress-events")
    assert result.returncode == 0, result.stdout + result.stderr
    run_end = [
        json.loads(line) for line in result.stdout.splitlines() if line.strip()
    ][-1]
    assert "import_zip" in journey.grounded_outputs(run_end)

    schema_path = tmp_path / "run_identity_schema.json"
    if schema_failure == "malformed_json":
        schema_path.write_text("{", encoding="utf-8")
    elif schema_failure == "invalid_schema":
        schema_path.write_text(
            json.dumps({"$id": "coursecraft.run/1", "type": 7}),
            encoding="utf-8",
        )
    elif schema_failure == "wrong_contract":
        schema_path.write_text(
            json.dumps({"$id": "another.contract/1", "type": "object"}),
            encoding="utf-8",
        )
    monkeypatch.setattr(journey, "RUN_SCHEMA_PATH", schema_path)
    assert journey.grounded_outputs(run_end) == {}


def test_headless_regular_file_bundle_target_is_refused_without_change(
    tmp_path: Path,
) -> None:
    target = tmp_path / "bundle-target"
    target.write_text("sentinel", encoding="utf-8")
    result = run_wizard(*weave_args(EXPLICIT, target))
    assert result.returncode == 2
    assert b"save location is an existing file, not a folder" in result.stdout
    assert target.read_text(encoding="utf-8") == "sentinel"


def test_headless_source_replacement_after_preflight_refuses_without_build(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import loom_ui
    import rubric_loom_weave as journey
    import rubric_loom_wizard as wizard

    source = tmp_path / "mutable.md"
    source.write_bytes(EXPLICIT.read_bytes())
    output = tmp_path / "must-not-exist"
    args = wizard.parse_args(
        [
            "--door",
            "weave",
            "--source",
            str(source),
            "--yes",
            "--approve-weave",
            "--plain",
            "--output-dir",
            str(output),
        ]
    )
    original_preflight = journey.invoke_preflight

    def replace_after_preflight(namespace):
        result = original_preflight(namespace)
        source.write_bytes(AMBIGUOUS.read_bytes())
        return result

    monkeypatch.setattr(journey, "invoke_preflight", replace_after_preflight)
    result = journey.run_headless(loom_ui.Term(plain=True), args, lambda _: None)
    assert result == 2
    assert "source changed after the displayed preflight" in capsys.readouterr().out
    assert not output.exists()


def test_remembered_state_is_isolated_by_door(tmp_path: Path) -> None:
    state = tmp_path / "state.json"
    unravel_out = tmp_path / "unravel"
    unravel = run_wizard(
        "--source",
        str(UNRAVEL),
        "--yes",
        "--no-docx",
        "--output-dir",
        str(unravel_out),
        state=state,
    )
    assert unravel.returncode == 0
    unravel_state = json.loads(state.read_text(encoding="utf-8"))
    assert unravel_state["last_door"] == "unravel"
    weave_out = tmp_path / "weave"
    weave = run_wizard(
        *weave_args(EXPLICIT, weave_out),
        "--allow-even-spacing",
        state=state,
    )
    assert weave.returncode == 0
    payload = json.loads(state.read_text(encoding="utf-8"))
    assert payload["schema"] == "rubric_loom.state/2"
    assert payload["last_door"] == "weave"
    assert payload["doors"]["unravel"]["source"] == str(UNRAVEL)
    assert payload["doors"]["unravel"]["docx"] is False
    assert payload["doors"]["weave"]["source"] == str(EXPLICIT.resolve())
    assert payload["doors"]["weave"]["allow_even_spacing"] is True
    assert "docx" not in payload["doors"]["weave"]


def test_legacy_headless_invocation_still_routes_to_unravel(tmp_path: Path) -> None:
    output = tmp_path / "legacy"
    result = run_wizard(
        "--source",
        str(UNRAVEL),
        "--yes",
        "--no-docx",
        "--output-dir",
        str(output),
    )
    assert result.returncode == 0
    assert (output / "tiny_rubrics_export__rubrics.json").is_file()
    assert b"The unravelling" in result.stdout
    assert b"The weaving" not in result.stdout


def test_weave_only_flags_require_the_weave_door(tmp_path: Path) -> None:
    output = tmp_path / "misroute"
    result = run_wizard(
        "--source",
        str(UNRAVEL),
        "--yes",
        "--no-docx",
        "--approve-weave",
        "--output-dir",
        str(output),
    )
    assert result.returncode == 2
    assert b"Weave-only options require --door weave" in result.stderr
    assert not output.exists()


def test_launcher_opens_the_one_art_led_tui_and_is_valid_shell() -> None:
    launcher = REPO_ROOT / "launch_rubric_loom.command"
    source = launcher.read_text(encoding="utf-8")
    assert source.count("scripts/rubric_loom_wizard.py") == 1
    assert "scripts/bootstrap_env.py\" --locked" in source
    assert "Workshop doctor" not in source
    assert "Selection [1]" not in source
    result = subprocess.run(
        ["bash", "-n", str(launcher)],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_launcher_fresh_environment_can_decline_setup_cleanly(
    tmp_path: Path,
) -> None:
    import shutil

    launcher = tmp_path / "launch_rubric_loom.command"
    shutil.copyfile(REPO_ROOT / "launch_rubric_loom.command", launcher)
    result = subprocess.run(
        ["bash", str(launcher)],
        cwd=tmp_path,
        input=b"n\n",
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert b".venv missing" in result.stdout
    assert b"Setup skipped; the loom stays idle." in result.stdout


@pytest.mark.skipif(os.name != "posix", reason="PTY is POSIX-only")
def test_interactive_weave_named_approval_and_back_behavior(tmp_path: Path) -> None:
    from test_rubric_loom_wizard import PtyWizard

    declined_out = tmp_path / "declined"
    declined = PtyWizard(
        [
            "--brisk",
            "--door",
            "weave",
            "--source",
            str(EXPLICIT),
            "--output-dir",
            str(declined_out),
        ],
        state=tmp_path / "declined-state.json",
    )
    review = b"Continue to final approval?"
    declined.wait_for_count(review, 1)
    declined.send(b"3\r")
    declined.wait_for(b"Save folder")
    declined.send(b"b\r")
    declined.wait_for_count(review, 2)
    declined.send(b"2\r")
    declined.wait_for(b"Output name (used in the run record and default folder)")
    declined.send(b"b\r")
    declined.wait_for_count(review, 3)
    declined.send(b"\r")
    declined.wait_for(b"Type WEAVE")
    declined.send(b"b\r")
    declined.wait_for_count(review, 4)
    declined.send(b"\r")
    declined.wait_for_count(b"Type WEAVE", 2)
    declined.send(b"NO\r")
    assert declined.finish() == 0
    assert b"nothing was written" in declined.stream
    assert not declined_out.exists()

    output = tmp_path / "approved"
    approved = PtyWizard(
        [
            "--brisk",
            "--door",
            "weave",
            "--source",
            str(EXPLICIT),
            "--output-dir",
            str(output),
        ],
        state=tmp_path / "approved-state.json",
    )
    approved.wait_for(b"Continue to final approval?")
    approved.send(b"\r")
    approved.wait_for(b"Type WEAVE")
    approved.send(b"WEAVE\r")
    approved.wait_for("The cloth is bound ✦".encode(), timeout=30)
    assert approved.finish() == 0
    assert (output / "rubric_package.zip").is_file()


@pytest.mark.skipif(os.name != "posix", reason="PTY is POSIX-only")
def test_interactive_source_replacement_restarts_review_without_build(
    tmp_path: Path,
) -> None:
    from test_rubric_loom_wizard import PtyWizard

    source = tmp_path / "mutable.md"
    source.write_bytes(EXPLICIT.read_bytes())
    output = tmp_path / "must-not-exist"
    session = PtyWizard(
        [
            "--brisk",
            "--door",
            "weave",
            "--source",
            str(source),
            "--output-dir",
            str(output),
        ],
        state=tmp_path / "state.json",
    )
    session.wait_for(b"Continue to final approval?")
    session.send(b"\r")
    session.wait_for(b"Type WEAVE")
    source.write_bytes(
        (
            REPO_ROOT
            / "workspace/reference/templates/rubric-weave/v1/"
            / "rubric-weave-intake-template.md"
        ).read_bytes()
    )
    session.send(b"WEAVE\r")
    session.wait_for(b"source changed after the displayed preflight", timeout=20)
    session.wait_for_count(b"Continue to final approval?", 2, timeout=20)
    assert not output.exists()
    session.proc.send_signal(signal.SIGINT)
    assert session.finish() == 130
    assert not output.exists()


@pytest.mark.skipif(os.name != "posix", reason="PTY is POSIX-only")
def test_interactive_regular_file_bundle_target_reprompts(
    tmp_path: Path,
) -> None:
    from test_rubric_loom_wizard import PtyWizard

    target = tmp_path / "existing-file"
    target.write_text("sentinel", encoding="utf-8")
    alternate = tmp_path / "alternate"
    session = PtyWizard(
        [
            "--brisk",
            "--door",
            "weave",
            "--source",
            str(EXPLICIT),
            "--output-dir",
            str(target),
        ],
        state=tmp_path / "state.json",
    )
    review = b"Continue to final approval?"
    session.wait_for_count(review, 1)
    session.send(b"\r")
    session.wait_for(b"save location is an existing file, not a folder")
    session.wait_for_count(review, 2)
    session.send(b"3\r")
    session.wait_for(b"Save folder")
    session.send(str(alternate).encode() + b"\r")
    session.wait_for_count(review, 3)
    session.send(b"\r")
    session.wait_for(b"Type WEAVE")
    session.send(b"NO\r")
    assert session.finish() == 0
    assert target.read_text(encoding="utf-8") == "sentinel"
    assert not alternate.exists()


@pytest.mark.skipif(os.name != "posix", reason="PTY is POSIX-only")
def test_back_at_both_fallback_prompts_navigates_without_writing(
    tmp_path: Path,
) -> None:
    from test_rubric_loom_wizard import PtyWizard

    output = tmp_path / "must-not-exist"
    session = PtyWizard(
        [
            "--brisk",
            "--door",
            "weave",
            "--source",
            str(AMBIGUOUS),
            "--output-dir",
            str(output),
        ],
        state=tmp_path / "state.json",
    )
    even = b"Use evenly spaced scores across its levels"
    equal = b"Give each criterion equal weight"
    session.wait_for(even)
    session.send(b"b\r")
    session.wait_for_count(even, 2)
    session.send(b"y\r")
    session.wait_for(equal)
    session.send(b"b\r")
    session.wait_for_count(even, 3)
    session.send(b"n\r")
    assert session.finish() == 0
    assert b"Producer preflight refused" in session.stream
    assert not output.exists()


@pytest.mark.skipif(os.name != "posix", reason="PTY is POSIX-only")
def test_interactive_door_router_can_quit(tmp_path: Path) -> None:
    from test_rubric_loom_wizard import PtyWizard

    session = PtyWizard(["--brisk"], state=tmp_path / "state.json")
    session.wait_for(b"What do you want to do?")
    session.send(b"q\r")
    assert session.finish() == 0
    assert b"nothing was run." in session.stream


@pytest.mark.skipif(os.name != "posix", reason="PTY is POSIX-only")
def test_interrupted_weave_claims_no_delivery(tmp_path: Path) -> None:
    from test_rubric_loom_wizard import PtyWizard

    for attempt in range(4):
        output = tmp_path / f"out-{attempt}"
        session = PtyWizard(
            weave_args(EXPLICIT, output) + ["--brisk"],
            state=tmp_path / "state.json",
        )
        session.wait_for(b"The weaving")
        time.sleep(0.03)
        session.proc.send_signal(signal.SIGINT)
        code = session.finish()
        if code == 0:
            continue
        assert code == 130
        assert b"The shuttle rests" in session.stream
        assert b"no artifact is claimed" in session.stream
        return
    pytest.skip("the fast synthetic run finished before SIGINT landed")
