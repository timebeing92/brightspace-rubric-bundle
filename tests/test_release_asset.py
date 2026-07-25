"""Release-asset machinery: determinism, receipts, and the Unravel door gate.

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
    for relative in (MODULE_PATH.relative_to(REPO_ROOT).as_posix(),) + tuple(
        release.RUNTIME_FILES
    ) + tuple(release.CONTRACT_FILES):
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
        "coursecraft.progress/1",
    ]
    assert [row["path"] for row in rows] == list(release.CONTRACT_FILES)
    for row in rows:
        expected = hashlib.sha256((REPO_ROOT / row["path"]).read_bytes()).hexdigest()
        assert row["sha256"] == expected


def test_runtime_receipt_and_unravel_capability() -> None:
    rows = release.runtime_receipt(REPO_ROOT)
    assert [row["path"] for row in rows] == [
        "scripts/run_rubric_bundle.py",
        "scripts/extract_rubrics_to_workbook.py",
        "scripts/rubrics_to_docx.py",
        "scripts/common_xml.py",
    ]
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


def test_unravel_capability_requires_runtime_markers(tmp_path: Path) -> None:
    for relative in release.RUNTIME_FILES:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("placeholder\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="lacks Unravel release markers"):
        release.release_capabilities(tmp_path)


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
    assert f"{SCRATCH_RELEASE_NAME}/RELEASE_MANIFEST.json" in names

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
        "coursecraft.progress/1",
    ]
    assert [row["path"] for row in manifest["runtime_files"]] == list(
        release.RUNTIME_FILES
    )
    assert manifest["capabilities"]["unravel"]["status"] == "enabled"


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
