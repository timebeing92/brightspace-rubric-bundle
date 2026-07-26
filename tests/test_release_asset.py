"""Release machinery: determinism, SBOM, receipts, and independent door gates.

The end-to-end assertions run against a scratch git repository shaped like this
bundle (VERSION, the two vendored schemas, the orchestrator and its extraction
entry points) so a real asset can be built without cutting a release here.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "scripts" / "make_release_asset.py"
SPEC = importlib.util.spec_from_file_location("make_release_asset", MODULE_PATH)
assert SPEC and SPEC.loader
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)

RELEASE_SCHEMA = "coursecraft.bundle_release/1"
SCRATCH_REMOTE = "git@github.com:example/brightspace-rubric-bundle.git"
SCRATCH_VERSION = "9.9.9"
SCRATCH_RELEASE_NAME = f"brightspace-rubric-bundle-v{SCRATCH_VERSION}"
WORKSHOP_MARKER = "scripts/run_rubric_bundle.py"
WEAVE_MARKER = "scripts/run_weave_bundle.py"
PIN_TARGETS = tuple(
    entry["target"]
    for entry in json.loads(
        (REPO_ROOT / "upstream" / "workbench_pin.json").read_text(
            encoding="utf-8"
        )
    )["files"]
)


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result


def commit_all(repo: Path, message: str) -> str:
    git(repo, "add", "-A")
    git(
        repo,
        "-c",
        "user.email=synthetic@example.invalid",
        "-c",
        "user.name=Synthetic Operator",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-q",
        "-m",
        message,
    )
    return git(repo, "rev-parse", "HEAD").stdout.strip()


@pytest.fixture
def scratch_bundle(tmp_path: Path) -> Path:
    """A committed, clean scratch bundle repo carrying the release machinery."""
    repo = tmp_path / "scratch-bundle"
    repo.mkdir()
    (repo / "VERSION").write_text(f"{SCRATCH_VERSION}\n", encoding="utf-8")
    (repo / "README.md").write_text("Synthetic scratch bundle.\n", encoding="utf-8")
    files = tuple(
        dict.fromkeys(
            (MODULE_PATH.relative_to(REPO_ROOT).as_posix(),)
            + tuple(release.RUNTIME_FILES)
            + tuple(release.CONTRACT_FILES)
            + (release.REQUIREMENTS_LOCK,)
            + PIN_TARGETS
        )
    )
    for relative in files:
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO_ROOT / relative, target)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "remote", "add", "origin", SCRATCH_REMOTE)
    commit_all(repo, "scratch bundle")
    return repo


def build_asset(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(repo / "scripts" / "make_release_asset.py"), *args],
        text=True,
        capture_output=True,
        check=False,
    )


def build_ok(repo: Path, output_dir: Path, *args: str) -> dict:
    result = build_asset(repo, "--ref", "HEAD", "--output-dir", str(output_dir), *args)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def extract(asset: Path, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(asset, mode="r:gz") as archive:
        try:
            archive.extractall(destination, filter="data")
        except TypeError:  # Python 3.11 without the extraction filter
            archive.extractall(destination)
    return destination


def test_remote_normalization_removes_credentials() -> None:
    assert (
        release.normalized_remote("https://token@github.com/example/repo.git")
        == "https://github.com/example/repo.git"
    )
    assert (
        release.normalized_remote(SCRATCH_REMOTE)
        == "https://github.com/example/brightspace-rubric-bundle.git"
    )
    assert (
        release.normalized_remote("git@github.com:example/repo.git?token=SECRET")
        == "https://github.com/example/repo.git"
    )
    assert (
        release.normalized_remote(
            "https://github.com/example/repo.git?access_token=SECRET#private"
        )
        == "https://github.com/example/repo.git"
    )
    assert (
        release.normalized_remote("ssh://git@github.com/example/repo.git")
        == "https://github.com/example/repo.git"
    )
    assert (
        release.normalized_remote("file:///Users/alice/Secret/project.git")
        == "local:project.git"
    )
    assert release.normalized_remote("/Users/alice/Secret/project") == "local:project"
    assert (
        release.normalized_remote(r"C:\Users\alice\Secret\project.git")
        == "local:project.git"
    )
    assert (
        release.normalized_remote("opaque://token@secret.example/private")
        == "local:repository"
    )


def test_normalized_archive_is_reproducible(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.txt").write_text("alpha\n", encoding="utf-8")
    (source / "nested").mkdir()
    (source / "nested" / "b.txt").write_text("beta\n", encoding="utf-8")
    first = tmp_path / "first.tar.gz"
    second = tmp_path / "second.tar.gz"
    release.normalized_tar_gz(source, first, "release")
    release.normalized_tar_gz(source, second, "release")
    assert first.read_bytes() == second.read_bytes()
    with tarfile.open(first) as archive:
        assert "release/nested/b.txt" in archive.getnames()


def test_contract_receipt_records_schema_ids_and_hashes() -> None:
    rows = release.contract_receipt(REPO_ROOT)
    assert [row["schema"] for row in rows] == [
        "coursecraft.rubrics/1",
        "coursecraft.rubric_authoring/1",
        "coursecraft.progress/1",
        "coursecraft.run/1",
    ]
    assert [row["path"] for row in rows] == list(release.CONTRACT_FILES)
    for row in rows:
        expected = hashlib.sha256((REPO_ROOT / row["path"]).read_bytes()).hexdigest()
        assert row["sha256"] == expected


def test_runtime_receipt_and_unravel_capability() -> None:
    rows = release.runtime_receipt(REPO_ROOT)
    assert [row["path"] for row in rows] == list(release.RUNTIME_FILES)
    for row in rows:
        expected = hashlib.sha256((REPO_ROOT / row["path"]).read_bytes()).hexdigest()
        assert row["sha256"] == expected

    capability = release.release_capabilities(REPO_ROOT)["unravel"]
    assert capability["status"] == "enabled"
    assert capability["entry_point"] == WORKSHOP_MARKER
    assert capability["source_forms"] == [
        "course_export_zip",
        "unpacked_export_folder",
        "rubrics_d2l_xml",
    ]
    assert capability["artifact_suffixes"] == [
        "__rubrics.xlsx",
        "__rubrics.json",
        "__rubrics.docx",
    ]
    assert capability["progress_schema"] == "coursecraft.progress/1"
    assert capability["rubrics_contract"] == "coursecraft.rubrics/1"
    assert capability["exit_codes"]["3"] == "no rubric evidence found in the source"
    assert capability["steps"] == [
        "Locate rubric evidence",
        "Extract rubric grids",
        "Validate rubric contract",
        "Render rubric review DOCX",
    ]
    assert capability["runtime_files"] == list(release.UNRAVEL_RUNTIME_FILES)


def test_weave_capability_is_independent_and_exact() -> None:
    capability = release.release_capabilities(REPO_ROOT)["weave"]
    assert capability["status"] == "enabled"
    assert capability["entry_point"] == WEAVE_MARKER
    assert capability["terminal_entry_point"] == "scripts/rubric_loom_wizard.py"
    assert capability["source_forms"] == [
        "docx_rubric_table",
        "markdown_rubric_table",
        "coursecraft.rubric_authoring/1_json",
        "eligible_coursecraft.rubrics/1_json",
        "legacy_builder_json",
    ]
    assert capability["authoring_contract"] == "coursecraft.rubric_authoring/1"
    assert capability["eligible_extraction_contract"] == "coursecraft.rubrics/1"
    assert capability["run_contract"] == "coursecraft.run/1"
    assert capability["progress_schema"] == "coursecraft.progress/1"
    assert capability["steps"] == list(release.WEAVE_STEPS)
    assert capability["exit_codes"] == release.WEAVE_EXIT_CODES
    assert capability["activity_attachment"] == "manual_only"
    assert capability["producer_pin"]["source_commit"] == (
        "ad08b1ca1ebd0889bba3353cd87ca71b88f26514"
    )
    assert capability["producer_pin"]["accepted_producer_commit"] == (
        "7c5140545548c89a254ac4502cfdd7ee6fb44255"
    )
    assert capability["source_byte_binding"] == {
        "primary": "source.sha256",
        "secondary": "source.extensions.bytes",
        "build_input": "private_verified_snapshot",
        "final_check": "coursecraft.run/1 source transport fingerprint",
    }
    assert capability["template_operations"]["listing_writes"] is False
    assert capability["template_operations"]["selection_writes"] is False
    template_catalog = capability["templates"]
    assert template_catalog["status"] == "available"
    assert template_catalog["source_commit"] == (
        "ad08b1ca1ebd0889bba3353cd87ca71b88f26514"
    )
    assert template_catalog["accepted_producer_commit"] == (
        "7c5140545548c89a254ac4502cfdd7ee6fb44255"
    )
    templates = {item["name"]: item for item in template_catalog["templates"]}
    assert templates["rubric-weave-intake-template.docx"]["bytes"] == 36204
    assert templates["rubric-weave-intake-template.docx"]["sha256"] == (
        "349a2c3d1f68b01476bc271be7e1e3f7c303edbc98739eac3d1eee8aafce104c"
    )
    assert templates["rubric-weave-intake-template.md"]["bytes"] == 2410
    assert templates["rubric-weave-intake-template.md"]["media_type"] == "text/markdown"
    assert all(
        set(item["boundaries"])
        == {"scoring", "brightspace_import", "activity_attachment"}
        for item in templates.values()
    )
    assert capability["runtime_files"] == list(release.WEAVE_RUNTIME_FILES)
    assert capability["terminal_runtime_files"] == list(
        release.TERMINAL_RUNTIME_FILES + release.INSTALL_RUNTIME_FILES
    )
    assert "scripts/bootstrap_env.py" in capability["terminal_runtime_files"]
    assert "requirements-dev.txt" in capability["terminal_runtime_files"]
    outputs = {item["key"]: item for item in capability["output_artifacts"]}
    assert outputs["import_zip"] == {
        "key": "import_zip",
        "path": "rubric_package.zip",
        "role": "rubric_import_package",
        "required": True,
        "primary": True,
    }
    assert outputs["review_report"]["required"] is False
    assert outputs["run_identity"]["path"] == "run_receipt.json"


def test_unravel_capability_requires_runtime_markers(tmp_path: Path) -> None:
    for relative in release.RUNTIME_FILES:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("placeholder\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="lacks Unravel release markers"):
        release.release_capabilities(tmp_path)


def test_sbom_is_deterministic_and_lock_grounded(scratch_bundle: Path) -> None:
    first = release.sbom_document(scratch_bundle)
    second = release.sbom_document(scratch_bundle)
    assert first == second
    payload = first
    assert payload["schema"] == release.SBOM_SCHEMA
    assert payload["component_count"] == len(payload["components"]) == 10
    assert payload["source"]["sha256"] == release.sha256_file(
        REPO_ROOT / release.REQUIREMENTS_LOCK
    )
    assert payload["components"][0] == {
        "name": "attrs",
        "version": "26.1.0",
        "purl": "pkg:pypi/attrs@26.1.0",
    }
    assert payload["asset_count"] == len(payload["assets"]) == 2
    assert {
        (asset["name"], asset["bytes"], asset["sha256"])
        for asset in payload["assets"]
    } == {
        (
            "rubric-weave-intake-template.docx",
            36204,
            "349a2c3d1f68b01476bc271be7e1e3f7c303edbc98739eac3d1eee8aafce104c",
        ),
        (
            "rubric-weave-intake-template.md",
            2410,
            "564ba8ebcee07281cbbe98045c8d56cc1f55e7694d7e453c49033c75db1e6830",
        ),
    }


def test_dirty_tree_is_refused_until_allow_dirty(scratch_bundle: Path) -> None:
    (scratch_bundle / "output").mkdir()
    (scratch_bundle / "output" / "stray.txt").write_text("dirty\n", encoding="utf-8")
    output_dir = scratch_bundle.parent / "dist-dirty"

    refused = build_asset(
        scratch_bundle, "--ref", "HEAD", "--output-dir", str(output_dir)
    )
    assert refused.returncode != 0
    assert "release repo is dirty" in refused.stderr
    assert not output_dir.exists()

    summary = build_ok(scratch_bundle, output_dir, "--allow-dirty")
    assert Path(summary["asset"]).name == f"{SCRATCH_RELEASE_NAME}.tar.gz"
    assert summary["version"] == SCRATCH_VERSION


def test_asset_is_byte_identical_across_builds(scratch_bundle: Path) -> None:
    first = build_ok(scratch_bundle, scratch_bundle.parent / "dist-one")
    second = build_ok(scratch_bundle, scratch_bundle.parent / "dist-two")
    assert first["asset_sha256"] == second["asset_sha256"]
    assert (
        Path(first["asset"]).read_bytes() == Path(second["asset"]).read_bytes()
    )


def test_sidecar_records_the_checksum_and_asset_name(scratch_bundle: Path) -> None:
    summary = build_ok(scratch_bundle, scratch_bundle.parent / "dist")
    asset = Path(summary["asset"])
    sidecar = Path(summary["checksum"])
    assert sidecar.name == f"{asset.name}.sha256"
    assert sidecar.read_text(encoding="utf-8") == (
        f"{summary['asset_sha256']}  {asset.name}\n"
    )
    assert release.sha256_file(asset) == summary["asset_sha256"]


def test_release_output_symlink_is_refused_without_touching_target(
    scratch_bundle: Path,
) -> None:
    output_dir = scratch_bundle.parent / "dist-symlink"
    output_dir.mkdir()
    sentinel = scratch_bundle.parent / "SENTINEL"
    sentinel.write_text("keep", encoding="utf-8")
    asset = output_dir / f"{SCRATCH_RELEASE_NAME}.tar.gz"
    asset.symlink_to(sentinel)
    result = build_asset(
        scratch_bundle,
        "--ref",
        "HEAD",
        "--output-dir",
        str(output_dir),
    )
    assert result.returncode != 0
    assert "refusing symlinked release output" in result.stderr
    assert sentinel.read_text(encoding="utf-8") == "keep"


def test_manifest_and_layout_carry_the_release_identity(scratch_bundle: Path) -> None:
    commit = git(scratch_bundle, "rev-parse", "HEAD").stdout.strip()
    summary = build_ok(scratch_bundle, scratch_bundle.parent / "dist")
    staged = extract(Path(summary["asset"]), scratch_bundle.parent / "unpacked")

    names = set()
    with tarfile.open(summary["asset"], mode="r:gz") as archive:
        for member in archive.getmembers():
            assert member.name.startswith(f"{SCRATCH_RELEASE_NAME}/")
            assert not (member.issym() or member.islnk())
            names.add(member.name)
    assert f"{SCRATCH_RELEASE_NAME}/{WORKSHOP_MARKER}" in names
    assert f"{SCRATCH_RELEASE_NAME}/{WEAVE_MARKER}" in names
    assert f"{SCRATCH_RELEASE_NAME}/RELEASE_MANIFEST.json" in names
    assert f"{SCRATCH_RELEASE_NAME}/{release.SBOM_PATH}" in names
    for relative in (
        "workspace/reference/templates/rubric-weave/v1/manifest.json",
        "workspace/reference/templates/rubric-weave/v1/rubric-weave-intake-template.docx",
        "workspace/reference/templates/rubric-weave/v1/rubric-weave-intake-template.md",
    ):
        assert f"{SCRATCH_RELEASE_NAME}/{relative}" in names

    manifest = json.loads(
        (staged / SCRATCH_RELEASE_NAME / "RELEASE_MANIFEST.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["schema"] == RELEASE_SCHEMA
    assert manifest["version"] == SCRATCH_VERSION
    assert manifest["source"] == {
        "repository": "https://github.com/example/brightspace-rubric-bundle.git",
        "ref": "HEAD",
        "commit": commit,
    }
    assert [row["schema"] for row in manifest["contracts"]] == [
        "coursecraft.rubrics/1",
        "coursecraft.rubric_authoring/1",
        "coursecraft.progress/1",
        "coursecraft.run/1",
    ]
    assert [row["path"] for row in manifest["runtime_files"]] == list(
        release.RUNTIME_FILES
    )
    assert manifest["capabilities"]["unravel"]["status"] == "enabled"
    assert manifest["capabilities"]["weave"]["status"] == "enabled"
    assert manifest["sbom"]["schema"] == release.SBOM_SCHEMA
    sbom_path = staged / SCRATCH_RELEASE_NAME / release.SBOM_PATH
    assert manifest["sbom"]["sha256"] == release.sha256_file(sbom_path)
    assert manifest["sbom"]["component_count"] == 10
    assert manifest["sbom"]["asset_count"] == 2
    release_root = staged / SCRATCH_RELEASE_NAME
    for item in manifest["capabilities"]["weave"]["templates"]["templates"]:
        archived = release_root / item["release_path"]
        assert archived.stat().st_size == item["bytes"]
        assert release.sha256_file(archived) == item["sha256"]


def test_asset_satisfies_the_workshop_fetch_checks(scratch_bundle: Path) -> None:
    """Replicate bundle_fetch's root discovery and validate_release locally.

    The workshop is not importable from this repo, so its three release checks
    (marker file beside RELEASE_MANIFEST.json at the bundle root, schema, and
    version/commit equality with the pin) are restated here.
    """
    commit = git(scratch_bundle, "rev-parse", "HEAD").stdout.strip()
    summary = build_ok(scratch_bundle, scratch_bundle.parent / "dist")
    slot = extract(Path(summary["asset"]), scratch_bundle.parent / "slot")
    pin = {
        "schema": "coursecraft.bundle_pin/1",
        "repository": "timebeing92/brightspace-rubric-bundle",
        "release": f"v{SCRATCH_VERSION}",
        "version": SCRATCH_VERSION,
        "asset": Path(summary["asset"]).name,
        "commit": commit,
        "sha256": summary["asset_sha256"],
    }

    roots = [
        candidate
        for candidate in [slot, *sorted(p for p in slot.iterdir() if p.is_dir())]
        if (candidate / WORKSHOP_MARKER).is_file()
        and (candidate / "RELEASE_MANIFEST.json").is_file()
    ]
    assert roots, "no verified bundle root under the extracted slot"
    root = roots[0]
    assert root.name == SCRATCH_RELEASE_NAME

    manifest = json.loads(
        (root / "RELEASE_MANIFEST.json").read_text(encoding="utf-8")
    )
    assert manifest["schema"] == RELEASE_SCHEMA
    assert manifest["version"] == pin["version"]
    assert manifest["source"]["commit"] == pin["commit"]
    assert release.sha256_file(Path(summary["asset"])) == pin["sha256"]


def test_build_refuses_a_bundle_missing_an_unravel_marker(
    scratch_bundle: Path,
) -> None:
    orchestrator = scratch_bundle / WORKSHOP_MARKER
    orchestrator.write_text(
        orchestrator.read_text(encoding="utf-8").replace(
            "--progress-events", "--progress"
        ),
        encoding="utf-8",
    )
    commit_all(scratch_bundle, "strip the progress-events flag")

    output_dir = scratch_bundle.parent / "dist-stripped"
    result = build_asset(
        scratch_bundle, "--ref", "HEAD", "--output-dir", str(output_dir)
    )
    assert result.returncode != 0
    assert "lacks Unravel release markers" in result.stderr
    assert "--progress-events" in result.stderr
    assert not list(output_dir.glob("*.tar.gz"))


def test_build_refuses_a_bundle_missing_a_weave_marker(
    scratch_bundle: Path,
) -> None:
    orchestrator = scratch_bundle / WEAVE_MARKER
    orchestrator.write_text(
        orchestrator.read_text(encoding="utf-8").replace(
            "--preflight", "--inspect-only"
        ),
        encoding="utf-8",
    )
    commit_all(scratch_bundle, "strip the Weave preflight marker")

    output_dir = scratch_bundle.parent / "dist-stripped-weave"
    result = build_asset(
        scratch_bundle, "--ref", "HEAD", "--output-dir", str(output_dir)
    )
    assert result.returncode != 0
    assert "lacks Weave release markers" in result.stderr
    assert "--preflight" in result.stderr
    assert not list(output_dir.glob("*.tar.gz"))


def test_build_refuses_weave_runtime_drift_from_the_pin(
    scratch_bundle: Path,
) -> None:
    producer = scratch_bundle / "scripts" / "rubric_authoring.py"
    producer.write_text(
        producer.read_text(encoding="utf-8") + "\n# unauthorized drift\n",
        encoding="utf-8",
    )
    commit_all(scratch_bundle, "drift the pinned Weave producer")

    output_dir = scratch_bundle.parent / "dist-drifted-weave"
    result = build_asset(
        scratch_bundle, "--ref", "HEAD", "--output-dir", str(output_dir)
    )
    assert result.returncode != 0
    assert "does not match its Workbench pin" in result.stderr
    assert "scripts/rubric_authoring.py" in result.stderr
    assert not list(output_dir.glob("*.tar.gz"))


@pytest.mark.parametrize("failure", ["missing", "mismatch"])
def test_build_refuses_missing_or_mismatched_template_bytes(
    scratch_bundle: Path,
    failure: str,
) -> None:
    template = (
        scratch_bundle
        / "workspace/reference/templates/rubric-weave/v1/"
        / "rubric-weave-intake-template.md"
    )
    if failure == "missing":
        template.unlink()
    else:
        template.write_bytes(template.read_bytes() + b"tampered")
    commit_all(scratch_bundle, f"{failure} template")

    output_dir = scratch_bundle.parent / f"dist-template-{failure}"
    result = build_asset(
        scratch_bundle,
        "--ref",
        "HEAD",
        "--output-dir",
        str(output_dir),
    )
    assert result.returncode != 0
    assert (
        "does not match its Workbench pin" in result.stderr
        or "lacks valid Weave templates" in result.stderr
    )
    assert not list(output_dir.glob("*.tar.gz"))


def test_missing_version_is_reported_honestly(scratch_bundle: Path) -> None:
    (scratch_bundle / "VERSION").unlink()
    commit = commit_all(scratch_bundle, "drop VERSION")

    result = build_asset(
        scratch_bundle,
        "--ref",
        "HEAD",
        "--output-dir",
        str(scratch_bundle.parent / "dist-no-version"),
    )
    assert result.returncode != 0
    assert f"VERSION is missing at {commit}" in result.stderr
