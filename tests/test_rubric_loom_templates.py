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
        36204,
        "349a2c3d1f68b01476bc271be7e1e3f7c303edbc98739eac3d1eee8aafce104c",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ),
    "rubric-weave-intake-template.md": (
        2410,
        "564ba8ebcee07281cbbe98045c8d56cc1f55e7694d7e453c49033c75db1e6830",
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
    assert catalog.source_commit == "ad08b1ca1ebd0889bba3353cd87ca71b88f26514"
    assert (
        catalog.accepted_producer_commit
        == "7c5140545548c89a254ac4502cfdd7ee6fb44255"
    )
    assert [asset.name for asset in catalog.assets] == list(EXPECTED)
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
def test_interactive_template_copy_stops_for_editing_before_weave(
    tmp_path: Path,
) -> None:
    from test_rubric_loom_wizard import PtyWizard

    destination = tmp_path / "editable.md"
    session = PtyWizard(
        ["--brisk", "--door", "weave"],
        state=tmp_path / "state.json",
    )
    session.wait_for(b"Which authored rubric should the loom weave?")
    session.send(b"template\r")
    session.wait_for(b"Release-pinned Weave templates")
    session.wait_for(b"Which editable template should the loom show?")
    session.send(b"rubric-weave-intake-template.md\r")
    session.wait_for(b"Pinned template details")
    session.wait_for(b"Copy these exact bytes")
    session.send(b"y\r")
    session.wait_for(b"Destination file")
    session.send(str(destination).encode() + b"\r")
    session.wait_for(b"Template copy ready")
    assert session.finish() == 0
    assert hashlib.sha256(destination.read_bytes()).hexdigest() == EXPECTED[
        "rubric-weave-intake-template.md"
    ][1]
    assert b"no package was built" in session.stream


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
    source_prompt = b"Which authored rubric should the loom weave?"
    session.wait_for(source_prompt)
    session.send(b"template\r")
    session.wait_for(b"Which editable template should the loom show?")
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
    exit_modes = ("template_back", "decline_copy", "destination_back")
    repetitions = 1_050
    source_defaults: list[str] = []
    source_option_keys: list[tuple[str, ...]] = []
    current_mode = ""
    source_selections = 0

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
        nonlocal current_mode, source_selections
        del term
        if prompt == "Which authored rubric should the loom weave?":
            source_defaults.append(default)
            source_option_keys.append(tuple(key for key, _ in options))
            if source_selections == repetitions:
                return loom_ui.BACK if final_choice == "back" else "q"
            current_mode = exit_modes[source_selections % len(exit_modes)]
            source_selections += 1
            assert allow_back is True
            return "template"
        assert prompt == "Which editable template should the loom show?"
        assert allow_back is True
        if current_mode == "template_back":
            return loom_ui.BACK
        return "rubric-weave-intake-template.md"

    def confirm(
        term,
        prompt: str,
        *,
        default: bool = False,
        assume_yes: bool = False,
        allow_back: bool = False,
    ):
        del term, default, assume_yes
        assert prompt == "Copy these exact bytes to a destination you choose?"
        assert allow_back is True
        return current_mode == "destination_back"

    def prompt_text(
        term,
        prompt: str,
        *,
        default: str = "",
        allow_back: bool = False,
    ):
        del term, default
        assert current_mode == "destination_back"
        assert prompt == "Destination file"
        assert allow_back is True
        return loom_ui.BACK

    def reject_copy(*args, **kwargs):
        raise AssertionError("a template exit must not copy bytes")

    monkeypatch.setattr(loom_ui, "choose", choose)
    monkeypatch.setattr(loom_ui, "confirm", confirm)
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
