from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
WIZARD = SCRIPTS / "rubric_loom_wizard.py"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import rubric_loom_templates as templates  # noqa: E402


EXPECTED = {
    "rubric-weave-intake-template.docx": (
        36087,
        "033c985041e9b1ebf082b28c29a4a4aafa314e92d583a98d668138d76e7046a7",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ),
    "rubric-weave-intake-template.md": (
        2230,
        "1bd8b37f5fa15d089d34b7a6feb9df01005e14f9eff5f4f7cfff076d5dc7b07c",
        "text/markdown",
    ),
}


def run_wizard(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(WIZARD), *args],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
        stdin=subprocess.DEVNULL,
    )


def template_root(tmp_path: Path) -> Path:
    root = tmp_path / "release"
    pin = json.loads(templates.PIN_PATH.read_text(encoding="utf-8"))
    for entry in pin["files"]:
        if (
            entry["target"] == templates.MANIFEST_RELATIVE
            or entry["target"].startswith(
                "workspace/reference/templates/rubric-weave/v1/"
            )
        ):
            target = root / entry["target"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPO_ROOT / entry["target"], target)
    pin_target = root / "upstream" / "workbench_pin.json"
    pin_target.parent.mkdir(parents=True, exist_ok=True)
    pin_target.write_text(json.dumps(pin), encoding="utf-8")
    return root


def test_catalog_reports_only_exact_release_pinned_assets() -> None:
    catalog = templates.load_catalog()
    assert catalog.source_commit == "a00fc4eca1834070f5208e03f4405dea9f87ad7f"
    assert (
        catalog.accepted_producer_commit
        == "71552e912b79d73a00b4d70fd97bd32386fbe2a4"
    )
    assert [asset.name for asset in catalog.assets] == list(EXPECTED)
    assert catalog.completion_sentinel == (
        "SYNTHETIC PRACTICE RUBRIC - REPLACE BEFORE USE"
    )
    for asset in catalog.assets:
        expected_bytes, expected_sha, expected_media = EXPECTED[asset.name]
        assert asset.version == "v1"
        assert asset.media_type == expected_media
        assert asset.bytes == expected_bytes
        assert asset.sha256 == expected_sha
        assert asset.release_path == asset.upstream_path
        assert hashlib.sha256(asset.path.read_bytes()).hexdigest() == expected_sha
        assert set(asset.boundaries) == {
            "scoring",
            "brightspace_import",
            "activity_attachment",
        }


def test_headless_listing_is_read_only_and_complete(tmp_path: Path) -> None:
    destination = tmp_path / "must-not-appear"
    result = run_wizard(
        "--door",
        "weave",
        "--list-templates",
        "--plain",
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "available"
    assert [item["name"] for item in payload["templates"]] == list(EXPECTED)
    assert all("release_path" in item and "upstream_path" in item for item in payload["templates"])
    assert not destination.exists()


@pytest.mark.parametrize("name", list(EXPECTED))
def test_headless_copy_delivers_exact_bytes_only_to_explicit_destination(
    tmp_path: Path,
    name: str,
) -> None:
    destination = tmp_path / f"copy-{name}"
    result = run_wizard(
        "--door",
        "weave",
        "--copy-template",
        name,
        "--template-destination",
        str(destination),
        "--plain",
    )
    assert result.returncode == 0, result.stderr
    expected_bytes, expected_sha, _ = EXPECTED[name]
    assert destination.stat().st_size == expected_bytes
    assert hashlib.sha256(destination.read_bytes()).hexdigest() == expected_sha
    assert "Nothing was imported" in result.stdout
    assert "attachment remains manual" in result.stdout
    assert "never silently invented" in result.stdout


def test_copy_requires_destination_and_separate_replacement_action(
    tmp_path: Path,
) -> None:
    name = "rubric-weave-intake-template.md"
    missing = run_wizard("--door", "weave", "--copy-template", name, "--plain")
    assert missing.returncode == 2
    assert "--template-destination" in missing.stderr

    destination = tmp_path / "existing.md"
    destination.write_text("sentinel", encoding="utf-8")
    collision = run_wizard(
        "--door",
        "weave",
        "--copy-template",
        name,
        "--template-destination",
        str(destination),
        "--plain",
    )
    assert collision.returncode == 2
    assert "explicit replacement is required" in collision.stderr
    assert destination.read_text(encoding="utf-8") == "sentinel"

    replaced = run_wizard(
        "--door",
        "weave",
        "--copy-template",
        name,
        "--template-destination",
        str(destination),
        "--replace-template",
        "--plain",
    )
    assert replaced.returncode == 0, replaced.stderr
    assert hashlib.sha256(destination.read_bytes()).hexdigest() == EXPECTED[name][1]


def test_copy_refuses_symlink_and_non_regular_destinations(
    tmp_path: Path,
) -> None:
    name = "rubric-weave-intake-template.md"
    sentinel = tmp_path / "sentinel"
    sentinel.write_text("keep", encoding="utf-8")
    alias = tmp_path / "alias.md"
    alias.symlink_to(sentinel)
    symlinked = run_wizard(
        "--door",
        "weave",
        "--copy-template",
        name,
        "--template-destination",
        str(alias),
        "--replace-template",
        "--plain",
    )
    assert symlinked.returncode == 2
    assert sentinel.read_text(encoding="utf-8") == "keep"

    directory = tmp_path / "directory.md"
    directory.mkdir()
    non_regular = run_wizard(
        "--door",
        "weave",
        "--copy-template",
        name,
        "--template-destination",
        str(directory),
        "--replace-template",
        "--plain",
    )
    assert non_regular.returncode == 2
    assert directory.is_dir()


@pytest.mark.skipif(os.name != "posix", reason="permission mode test is POSIX-only")
def test_headless_copy_non_writable_destination_fails_cleanly_without_change(
    tmp_path: Path,
) -> None:
    name = "rubric-weave-intake-template.md"
    locked = tmp_path / "locked"
    locked.mkdir()
    destination = locked / "sentinel.md"
    destination.write_text("keep", encoding="utf-8")
    original_mode = stat.S_IMODE(destination.stat().st_mode)
    locked.chmod(0o500)
    if os.access(locked, os.W_OK):
        locked.chmod(0o700)
        pytest.skip("runtime identity can still write a mode-0500 directory")
    try:
        result = run_wizard(
            "--door",
            "weave",
            "--copy-template",
            name,
            "--template-destination",
            str(destination),
            "--replace-template",
            "--plain",
        )
    finally:
        locked.chmod(0o700)
    assert result.returncode == 2
    assert "Traceback" not in result.stderr
    assert destination.read_text(encoding="utf-8") == "keep"
    assert stat.S_IMODE(destination.stat().st_mode) == original_mode
    assert not list(locked.glob(".*.rubric-loom-*.tmp"))


@pytest.mark.parametrize("failed_operation", ["open", "link", "replace"])
def test_copy_filesystem_errors_are_translated_and_staging_is_cleaned(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failed_operation: str,
) -> None:
    destination = tmp_path / "copy.md"
    replace = failed_operation == "replace"
    if replace:
        destination.write_text("sentinel", encoding="utf-8")

    def fail(*args, **kwargs):
        raise PermissionError(f"simulated {failed_operation} refusal")

    monkeypatch.setattr(os, failed_operation, fail)
    with pytest.raises(templates.TemplateCopyError) as caught:
        templates.copy_template(
            "rubric-weave-intake-template.md",
            destination,
            replace=replace,
        )
    assert isinstance(caught.value.__cause__, PermissionError)
    if replace:
        assert destination.read_text(encoding="utf-8") == "sentinel"
    else:
        assert not destination.exists()
    assert not list(tmp_path.glob(".*.rubric-loom-*.tmp"))


def test_copy_symlink_race_never_changes_victim_bytes_or_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    victim = tmp_path / "victim"
    victim.write_bytes(b"untouched")
    victim.chmod(0o640)
    original_mode = stat.S_IMODE(victim.stat().st_mode)
    destination = tmp_path / "copy.md"
    real_link = os.link

    def race_after_publication(
        source: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        target: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        *,
        follow_symlinks: bool = True,
    ) -> None:
        real_link(source, target, follow_symlinks=follow_symlinks)
        published = Path(target)
        published.unlink()
        published.symlink_to(victim)

    monkeypatch.setattr(os, "link", race_after_publication)
    with pytest.raises(
        templates.TemplateCopyError,
        match="verified|verification",
    ):
        templates.copy_template(
            "rubric-weave-intake-template.md",
            destination,
        )
    assert victim.read_bytes() == b"untouched"
    assert stat.S_IMODE(victim.stat().st_mode) == original_mode
    assert destination.is_symlink()
    assert not list(tmp_path.glob(".*.rubric-loom-*.tmp"))


@pytest.mark.skipif(os.name != "posix", reason="PTY is POSIX-only")
def test_interactive_template_copy_remembers_destination_and_can_finish(
    tmp_path: Path,
) -> None:
    from test_rubric_loom_wizard import PtyWizard

    destination = tmp_path / "editable.md"
    session = PtyWizard(
        ["--brisk", "--door", "weave"],
        state=tmp_path / "state.json",
    )
    session.wait_for(b"How would you like to begin?")
    session.send(b"template\r")
    session.wait_for(b"Create a new rubric from a template")
    session.wait_for(b"Which type of editable template would you like?")
    session.send(b"rubric-weave-intake-template.md\r")
    session.wait_for(b"About this template")
    destination_card = b"Where should the editable copy go?"
    session.wait_for(destination_card)
    session.send(b"1\r")
    session.wait_for(b"Folder for the editable copy")
    session.send(str(tmp_path).encode() + b"\r")
    session.wait_for_count(destination_card, 2)
    session.send(b"2\r")
    session.wait_for(b"File name")
    session.send(destination.name.encode() + b"\r")
    session.wait_for_count(destination_card, 3)
    session.send(b"\r")
    session.wait_for(b"Your editable template is ready")
    session.wait_for(b"What would you like to do next?")
    session.send(b"done\r")
    assert session.finish() == 0
    assert hashlib.sha256(destination.read_bytes()).hexdigest() == EXPECTED[
        "rubric-weave-intake-template.md"
    ][1]
    assert b"no package was built" in session.stream
    assert b"release-pinned" not in session.stream.lower()
    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert state["doors"]["weave"]["template_folder"] == str(tmp_path)
    assert state["doors"]["weave"]["template_filename"] == destination.name


def test_post_copy_can_open_edit_and_continue_without_relaunch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import loom_ui
    import rubric_loom_weave as journey

    destination = tmp_path / "editable.md"
    destination.write_bytes(b"original template")
    original_binding = journey.file_source_binding(destination)
    term = loom_ui.Term(plain=True)
    term.is_tty = True

    monkeypatch.setattr(loom_ui, "choose", lambda *args, **kwargs: "continue")

    def open_and_edit(_term, path: Path) -> bool:
        path.write_bytes(b"completed rubric")
        return True

    monkeypatch.setattr(journey, "open_template_file", open_and_edit)
    monkeypatch.setattr(loom_ui, "prompt_text", lambda *args, **kwargs: "")

    assert journey._post_copy_handoff(
        term,
        destination,
        original_binding,
    ) == destination
    assert "continuing to Weave preflight" in capsys.readouterr().out


def test_post_copy_refuses_unchanged_template_before_continuing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import loom_ui
    import rubric_loom_weave as journey

    destination = tmp_path / "editable.md"
    destination.write_bytes(b"unchanged template")
    original_binding = journey.file_source_binding(destination)
    term = loom_ui.Term(plain=True)
    term.is_tty = True
    replies = iter(("", "q"))

    monkeypatch.setattr(loom_ui, "choose", lambda *args, **kwargs: "continue")
    monkeypatch.setattr(journey, "open_template_file", lambda *args: True)
    monkeypatch.setattr(
        loom_ui,
        "prompt_text",
        lambda *args, **kwargs: next(replies),
    )

    assert (
        journey._post_copy_handoff(term, destination, original_binding)
        is journey.TEMPLATE_HANDOFF
    )
    assert "template has not changed yet" in capsys.readouterr().out


def test_remembered_template_destination_reuses_folder_and_avoids_collision(
    tmp_path: Path,
) -> None:
    import rubric_loom_weave as journey

    catalog = templates.load_catalog()
    word = next(asset for asset in catalog.assets if asset.name.endswith(".docx"))
    (tmp_path / "colleague-rubric.docx").write_bytes(b"existing rubric")

    assert journey._default_template_folder(str(tmp_path)) == tmp_path
    assert journey._default_template_name(word, "colleague-rubric.md") == (
        "colleague-rubric.docx"
    )
    assert journey._available_template_name(
        tmp_path,
        "colleague-rubric.docx",
    ) == "colleague-rubric-2.docx"


def test_open_template_folder_runs_selected_platform_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import loom_ui
    import rubric_loom_weave as journey

    command = ["test-folder-opener", str(tmp_path)]
    calls: list[list[str]] = []
    monkeypatch.setattr(journey, "folder_open_command", lambda _path: command)

    def run(selected: list[str], *, check: bool):
        assert check is False
        calls.append(selected)
        return subprocess.CompletedProcess(selected, 0)

    monkeypatch.setattr(journey.subprocess, "run", run)
    term = loom_ui.Term(plain=True)
    assert journey.open_template_folder(term, tmp_path) is True
    assert calls == [command]


def test_open_template_file_runs_selected_platform_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import loom_ui
    import rubric_loom_weave as journey

    destination = tmp_path / "editable.md"
    destination.write_bytes(b"rubric")
    command = ["test-file-opener", str(destination)]
    calls: list[list[str]] = []
    monkeypatch.setattr(journey, "file_open_command", lambda _path: command)

    def run(selected: list[str], *, check: bool):
        assert check is False
        calls.append(selected)
        return subprocess.CompletedProcess(selected, 0)

    monkeypatch.setattr(journey.subprocess, "run", run)
    assert journey.open_template_file(loom_ui.Term(plain=True), destination) is True
    assert calls == [command]


@pytest.mark.skipif(os.name != "posix", reason="PTY is POSIX-only")
def test_template_browse_back_then_quit_is_filesystem_read_only(
    tmp_path: Path,
) -> None:
    from test_rubric_loom_wizard import PtyWizard

    isolated_repo = tmp_path / "fresh-repo"
    shutil.copytree(
        REPO_ROOT,
        isolated_repo,
        ignore=shutil.ignore_patterns(
            ".git",
            ".pytest_cache",
            ".venv",
            "__pycache__",
            "dist",
            "output",
            "*.pyc",
        ),
    )
    isolated_output = isolated_repo / "output"
    state = tmp_path / "fresh-state" / "state.json"
    assert not isolated_output.exists()
    assert not state.parent.exists()

    def workspace_fingerprint() -> dict[str, tuple[str, int, str]]:
        fingerprint: dict[str, tuple[str, int, str]] = {}
        for path in sorted(isolated_repo.rglob("*")):
            relative = path.relative_to(isolated_repo).as_posix()
            mode = stat.S_IMODE(path.lstat().st_mode)
            if path.is_symlink():
                fingerprint[relative] = ("symlink", mode, os.readlink(path))
            elif path.is_file():
                fingerprint[relative] = (
                    "file",
                    mode,
                    hashlib.sha256(path.read_bytes()).hexdigest(),
                )
            else:
                fingerprint[relative] = ("directory", mode, "")
        return fingerprint

    before = workspace_fingerprint()
    session = PtyWizard(
        ["--brisk", "--door", "weave"],
        state=state,
        wizard=isolated_repo / "scripts" / "rubric_loom_wizard.py",
        cwd=isolated_repo,
        env_overrides={"PYTHONDONTWRITEBYTECODE": "1"},
    )
    source_prompt = b"How would you like to begin?"
    session.wait_for(source_prompt)
    session.send(b"template\r")
    session.wait_for(b"Which type of editable template would you like?")
    session.send(b"b\r")
    session.wait_for_count(source_prompt, 2)
    session.send(b"q\r")
    assert session.finish() == 0

    assert b"nothing was run." in session.stream
    assert not state.exists()
    assert not state.parent.exists()
    assert not isolated_output.exists()
    assert workspace_fingerprint() == before


@pytest.mark.parametrize("final_choice", ["q", "back"])
def test_repeated_template_exits_keep_source_selection_constant_stack_and_read_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    final_choice: str,
) -> None:
    import loom_ui
    import rubric_loom_weave as journey

    catalog = templates.load_catalog()
    remembered = tmp_path / "remembered.md"
    state = {"source": str(remembered), "marker": ["unchanged"]}
    original_state = {"source": state["source"], "marker": list(state["marker"])}
    exit_modes = ("template_back", "review_back", "folder_back")
    repetitions = 1_050
    source_defaults: list[str] = []
    source_option_keys: list[tuple[str, ...]] = []
    current_mode = ""
    source_selections = 0
    review_calls = 0

    monkeypatch.setattr(templates, "catalog_or_error", lambda: (catalog, None))
    monkeypatch.setattr(journey, "input_lane_candidates", lambda: [remembered])

    def choose(
        term,
        prompt: str,
        options: list[tuple[str, str]],
        *,
        default: str,
        allow_back: bool = False,
    ):
        nonlocal current_mode, source_selections, review_calls
        del term
        if prompt == "How would you like to begin?":
            source_defaults.append(default)
            source_option_keys.append(tuple(key for key, _ in options))
            if source_selections == repetitions:
                return loom_ui.BACK if final_choice == "back" else "q"
            current_mode = exit_modes[source_selections % len(exit_modes)]
            review_calls = 0
            source_selections += 1
            assert allow_back is True
            return "template"
        assert prompt == "Which type of editable template would you like?"
        assert allow_back is True
        if current_mode == "template_back":
            return loom_ui.BACK
        return "rubric-weave-intake-template.md"

    def review_choice(
        term,
        prompt: str,
        *,
        choices: tuple[str, ...],
        allow_back: bool = False,
        allow_quit: bool = True,
    ):
        nonlocal review_calls
        del term
        assert prompt == "Save this editable template?"
        assert choices == ("1", "2")
        assert allow_back is True
        assert allow_quit is False
        review_calls += 1
        if current_mode == "folder_back" and review_calls == 1:
            return "1"
        return loom_ui.BACK

    def prompt_text(
        term,
        prompt: str,
        *,
        default: str = "",
        allow_back: bool = False,
    ):
        del term, default
        assert current_mode == "folder_back"
        assert prompt == "Folder for the editable copy"
        assert allow_back is True
        return loom_ui.BACK

    def reject_copy(*args, **kwargs):
        raise AssertionError("a template exit must not copy bytes")

    monkeypatch.setattr(loom_ui, "choose", choose)
    monkeypatch.setattr(loom_ui, "review_choice", review_choice)
    monkeypatch.setattr(loom_ui, "prompt_text", prompt_text)
    monkeypatch.setattr(templates, "copy_template", reject_copy)

    assert journey.pick_source(
        loom_ui.Term(plain=True),
        state["source"],
    ) is None
    assert source_selections == repetitions
    assert source_defaults == ["1"] * (repetitions + 1)
    assert set(source_option_keys) == {
        ("template", "1", "path", "demo", "q")
    }
    assert state == original_state
    assert not any(tmp_path.iterdir())


@pytest.mark.parametrize("failure", ["missing", "bytes", "sha", "traversal", "symlink"])
def test_catalog_fails_closed_on_missing_or_mismatched_assets(
    tmp_path: Path,
    failure: str,
) -> None:
    root = template_root(tmp_path)
    manifest_path = root / templates.MANIFEST_RELATIVE
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    asset_path = manifest_path.parent / manifest["templates"][0]["path"]
    if failure == "missing":
        asset_path.unlink()
    elif failure == "bytes":
        asset_path.write_bytes(asset_path.read_bytes() + b"x")
    elif failure == "sha":
        manifest["templates"][0]["sha256"] = "0" * 64
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        pin = json.loads((root / "upstream/workbench_pin.json").read_text())
        for entry in pin["files"]:
            if entry["target"] == templates.MANIFEST_RELATIVE:
                entry["sha256"] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        (root / "upstream/workbench_pin.json").write_text(json.dumps(pin))
    elif failure == "traversal":
        manifest["templates"][0]["path"] = "../outside.docx"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        pin = json.loads((root / "upstream/workbench_pin.json").read_text())
        for entry in pin["files"]:
            if entry["target"] == templates.MANIFEST_RELATIVE:
                entry["sha256"] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        (root / "upstream/workbench_pin.json").write_text(json.dumps(pin))
    else:
        replacement = tmp_path / "replacement"
        shutil.copyfile(asset_path, replacement)
        asset_path.unlink()
        asset_path.symlink_to(replacement)
    with pytest.raises(templates.TemplateIntegrityError):
        templates.load_catalog(root)
