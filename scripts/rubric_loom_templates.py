#!/usr/bin/env python3
"""Integrity-gated discovery and explicit delivery of Weave intake templates.

The editable assets and their manifest are mechanically vendored from the
Workbench.  This bundle-owned module only verifies and copies those exact
bytes; it does not parse or reinterpret rubric authoring semantics.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import secrets
import stat
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
PIN_PATH = REPO_ROOT / "upstream" / "workbench_pin.json"
MANIFEST_RELATIVE = (
    "workspace/reference/templates/rubric-weave/v1/manifest.json"
)
MANIFEST_PATH = REPO_ROOT / MANIFEST_RELATIVE
MANIFEST_SCHEMA = "coursecraft.rubric_weave_template_manifest/1"
CATALOG_SCHEMA = "coursecraft.rubric_weave_template_catalog/1"
EXPECTED_TEMPLATE_SET = "rubric-weave-intake"
EXPECTED_VERSION = "v1"
EXPECTED_MEDIA_TYPES = {
    "rubric-weave-intake-template.docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ),
    "rubric-weave-intake-template.md": "text/markdown",
}


class TemplateIntegrityError(RuntimeError):
    """The release-pinned template convenience path cannot be trusted."""


class TemplateCopyError(RuntimeError):
    """An explicit template copy destination is unsafe or unavailable."""


@dataclass(frozen=True)
class TemplateAsset:
    name: str
    version: str
    media_type: str
    bytes: int
    sha256: str
    upstream_path: str
    release_path: str
    boundaries: dict[str, str]
    path: Path

    def release_record(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "upstream_path": self.upstream_path,
            "release_path": self.release_path,
            "version": self.version,
            "media_type": self.media_type,
            "bytes": self.bytes,
            "sha256": self.sha256,
            "boundaries": dict(self.boundaries),
        }


@dataclass(frozen=True)
class TemplateCatalog:
    source_commit: str
    accepted_producer_commit: str
    template_set: str
    version: str
    manifest_path: str
    assets: tuple[TemplateAsset, ...]

    def release_record(self) -> dict[str, Any]:
        return {
            "schema": CATALOG_SCHEMA,
            "status": "available",
            "source_commit": self.source_commit,
            "accepted_producer_commit": self.accepted_producer_commit,
            "template_set": self.template_set,
            "version": self.version,
            "manifest_path": self.manifest_path,
            "templates": [asset.release_record() for asset in self.assets],
        }


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TemplateIntegrityError(f"{label} is missing or unreadable") from exc
    if not isinstance(value, dict):
        raise TemplateIntegrityError(f"{label} is not a JSON object")
    return value


def _safe_relative(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise TemplateIntegrityError(f"{label} is not a path string")
    pure = PurePosixPath(value)
    if (
        pure.is_absolute()
        or not pure.parts
        or ".." in pure.parts
        or "." in pure.parts
        or "\\" in value
    ):
        raise TemplateIntegrityError(f"{label} is not a safe release path")
    return pure.as_posix()


def _regular_file_without_symlinks(root: Path, relative: str, label: str) -> Path:
    current = root
    for part in PurePosixPath(relative).parts:
        current = current / part
        try:
            mode = current.lstat().st_mode
        except OSError as exc:
            raise TemplateIntegrityError(f"{label} is missing") from exc
        if stat.S_ISLNK(mode):
            raise TemplateIntegrityError(f"{label} uses a symlink")
    try:
        mode = current.lstat().st_mode
    except OSError as exc:
        raise TemplateIntegrityError(f"{label} is missing") from exc
    if not stat.S_ISREG(mode):
        raise TemplateIntegrityError(f"{label} is not a regular file")
    return current


def load_catalog(root: Path = REPO_ROOT) -> TemplateCatalog:
    """Return the exact manifest-backed assets or fail closed."""

    pin_path = root / "upstream" / "workbench_pin.json"
    manifest_path = root / MANIFEST_RELATIVE
    pin = _load_object(pin_path, "Workbench vendor pin")
    if pin.get("schema") != "coursecraft.workbench_vendor_pin/1":
        raise TemplateIntegrityError("Workbench vendor pin schema is unsupported")
    source_commit = pin.get("source_commit")
    accepted_commit = pin.get("accepted_producer_commit")
    if not isinstance(source_commit, str) or len(source_commit) != 40:
        raise TemplateIntegrityError("Workbench vendor pin lacks an immutable source commit")
    if not isinstance(accepted_commit, str) or len(accepted_commit) != 40:
        raise TemplateIntegrityError(
            "Workbench vendor pin lacks the accepted producer commit"
        )
    entries: dict[str, dict[str, Any]] = {}
    for item in pin.get("files", []):
        if not isinstance(item, dict):
            continue
        target = item.get("target")
        if isinstance(target, str):
            if target in entries:
                raise TemplateIntegrityError(
                    f"Workbench vendor pin repeats target {target}"
                )
            entries[target] = item

    manifest_entry = entries.get(MANIFEST_RELATIVE)
    if not isinstance(manifest_entry, dict):
        raise TemplateIntegrityError("template manifest is absent from the vendor pin")
    pinned_manifest = _regular_file_without_symlinks(
        root, MANIFEST_RELATIVE, "template manifest"
    )
    manifest_bytes = pinned_manifest.read_bytes()
    if (
        manifest_entry.get("source") != MANIFEST_RELATIVE
        or manifest_entry.get("sha256") != _sha256(manifest_bytes)
    ):
        raise TemplateIntegrityError("template manifest does not match the vendor pin")
    manifest = _load_object(manifest_path, "template manifest")
    if (
        manifest.get("schema") != MANIFEST_SCHEMA
        or manifest.get("template_set") != EXPECTED_TEMPLATE_SET
        or manifest.get("version") != EXPECTED_VERSION
        or manifest.get("path_base") != "manifest_directory"
    ):
        raise TemplateIntegrityError("template manifest identity is unsupported")

    producer = manifest.get("accepted_producer")
    if (
        not isinstance(producer, dict)
        or producer.get("repository") != "coursecraft_workbench"
        or producer.get("commit") != accepted_commit
        or producer.get("authoring_contract") != "coursecraft.rubric_authoring/1"
    ):
        raise TemplateIntegrityError(
            "template manifest does not retain the accepted producer semantics"
        )
    boundaries = manifest.get("boundaries")
    required_boundaries = {"scoring", "brightspace_import", "activity_attachment"}
    if (
        not isinstance(boundaries, dict)
        or set(boundaries) != required_boundaries
        or any(not isinstance(boundaries[key], str) or not boundaries[key] for key in boundaries)
    ):
        raise TemplateIntegrityError("template manifest boundaries are incomplete")

    raw_templates = manifest.get("templates")
    if not isinstance(raw_templates, list):
        raise TemplateIntegrityError("template manifest entries are not a list")
    by_name: dict[str, dict[str, Any]] = {}
    for item in raw_templates:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise TemplateIntegrityError("template manifest contains an invalid entry")
        if item["path"] in by_name:
            raise TemplateIntegrityError("template manifest repeats an asset path")
        by_name[item["path"]] = item
    if set(by_name) != set(EXPECTED_MEDIA_TYPES):
        raise TemplateIntegrityError("template manifest asset inventory is unsupported")

    assets: list[TemplateAsset] = []
    manifest_dir = PurePosixPath(MANIFEST_RELATIVE).parent
    for name, expected_media_type in EXPECTED_MEDIA_TYPES.items():
        item = by_name[name]
        safe_name = _safe_relative(item.get("path"), "template asset path")
        if len(PurePosixPath(safe_name).parts) != 1:
            raise TemplateIntegrityError("template assets must stay beside their manifest")
        release_path = (manifest_dir / safe_name).as_posix()
        entry = entries.get(release_path)
        if not isinstance(entry, dict):
            raise TemplateIntegrityError(f"{name} is absent from the vendor pin")
        upstream_path = _safe_relative(entry.get("source"), "upstream template path")
        pinned_release_path = _safe_relative(entry.get("target"), "release template path")
        if pinned_release_path != release_path:
            raise TemplateIntegrityError(f"{name} has an unexpected release path")
        path = _regular_file_without_symlinks(root, release_path, name)
        data = path.read_bytes()
        expected_bytes = item.get("bytes")
        expected_sha = item.get("sha256")
        if (
            item.get("version") != EXPECTED_VERSION
            or item.get("media_type") != expected_media_type
            or not isinstance(expected_bytes, int)
            or isinstance(expected_bytes, bool)
            or expected_bytes < 0
            or not isinstance(expected_sha, str)
            or len(expected_sha) != 64
            or len(data) != expected_bytes
            or _sha256(data) != expected_sha
            or entry.get("sha256") != expected_sha
        ):
            raise TemplateIntegrityError(f"{name} failed its pinned integrity checks")
        assets.append(
            TemplateAsset(
                name=name,
                version=EXPECTED_VERSION,
                media_type=expected_media_type,
                bytes=expected_bytes,
                sha256=expected_sha,
                upstream_path=upstream_path,
                release_path=release_path,
                boundaries=dict(boundaries),
                path=path,
            )
        )
    return TemplateCatalog(
        source_commit=source_commit,
        accepted_producer_commit=accepted_commit,
        template_set=EXPECTED_TEMPLATE_SET,
        version=EXPECTED_VERSION,
        manifest_path=MANIFEST_RELATIVE,
        assets=tuple(assets),
    )


def catalog_or_error(root: Path = REPO_ROOT) -> tuple[TemplateCatalog | None, str | None]:
    try:
        return load_catalog(root), None
    except TemplateIntegrityError as exc:
        return None, str(exc)


def _destination_parent(destination: Path) -> Path:
    parent = destination.parent
    current = parent
    while True:
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError as exc:
            if current == parent:
                raise TemplateCopyError(
                    f"destination folder does not exist: {parent}"
                ) from exc
            raise TemplateCopyError(
                f"destination folder is unreadable: {current}"
            ) from exc
        except OSError as exc:
            raise TemplateCopyError(
                f"destination folder is unreadable: {current}"
            ) from exc
        if stat.S_ISLNK(mode):
            raise TemplateCopyError(
                f"destination folder uses a symlink: {current}"
            )
        if current == parent and not stat.S_ISDIR(mode):
            raise TemplateCopyError(
                f"destination folder is not a directory: {parent}"
            )
        if current == current.parent:
            break
        current = current.parent
    return parent


def _verified_destination(asset: TemplateAsset, destination: Path) -> bool:
    """Verify published bytes through a no-follow descriptor when available."""

    before = destination.lstat()
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        return False
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(destination, flags)
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_dev != before.st_dev
            or opened.st_ino != before.st_ino
        ):
            return False
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = None
            data = handle.read()
    finally:
        if descriptor is not None:
            os.close(descriptor)
    after = destination.lstat()
    return (
        stat.S_ISREG(after.st_mode)
        and not stat.S_ISLNK(after.st_mode)
        and after.st_dev == opened.st_dev
        and after.st_ino == opened.st_ino
        and len(data) == asset.bytes
        and hashlib.sha256(data).hexdigest() == asset.sha256
    )


def copy_template(
    name: str,
    destination: Path,
    *,
    replace: bool = False,
    root: Path = REPO_ROOT,
) -> tuple[TemplateAsset, Path]:
    """Copy one verified template only after an explicit destination is supplied."""

    catalog = load_catalog(root)
    asset = next((item for item in catalog.assets if item.name == name), None)
    if asset is None:
        raise TemplateCopyError(f"unknown template: {name}")
    try:
        destination = destination.expanduser().absolute()
    except OSError as exc:
        raise TemplateCopyError("destination path is unavailable") from exc
    _destination_parent(destination)

    existing_stat = None
    try:
        existing_stat = destination.lstat()
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise TemplateCopyError(f"destination is unreadable: {destination}") from exc
    if existing_stat is not None:
        if stat.S_ISLNK(existing_stat.st_mode):
            raise TemplateCopyError(f"refusing symlink destination: {destination}")
        if not stat.S_ISREG(existing_stat.st_mode):
            raise TemplateCopyError(
                f"refusing non-regular destination: {destination}"
            )
        if not replace:
            raise TemplateCopyError(
                f"destination already exists; explicit replacement is required: {destination}"
            )

    try:
        data = asset.path.read_bytes()
    except OSError as exc:
        raise TemplateCopyError(
            f"template bytes are unreadable: {asset.name}"
        ) from exc
    if len(data) != asset.bytes or _sha256(data) != asset.sha256:
        raise TemplateIntegrityError(f"{asset.name} changed before delivery")

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    temporary = destination.with_name(
        f".{destination.name}.rubric-loom-{secrets.token_hex(8)}.tmp"
    )
    descriptor = None
    operation_error: TemplateCopyError | None = None
    try:
        descriptor = os.open(temporary, flags, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = None
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if existing_stat is None:
            try:
                os.link(temporary, destination, follow_symlinks=False)
            except FileExistsError as exc:
                raise TemplateCopyError(
                    f"destination appeared during copy: {destination}"
                ) from exc
        else:
            current = destination.lstat()
            if (
                not stat.S_ISREG(current.st_mode)
                or current.st_dev != existing_stat.st_dev
                or current.st_ino != existing_stat.st_ino
            ):
                raise TemplateCopyError(
                    f"destination changed before replacement: {destination}"
                )
            os.replace(temporary, destination)
    except TemplateCopyError as exc:
        operation_error = exc
    except OSError as exc:
        operation_error = TemplateCopyError(
            f"could not copy template to destination: {destination}"
        )
        operation_error.__cause__ = exc
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError as exc:
                if operation_error is None:
                    operation_error = TemplateCopyError(
                        f"could not close template staging file: {temporary}"
                    )
                    operation_error.__cause__ = exc
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            if operation_error is None:
                operation_error = TemplateCopyError(
                    f"could not clean template staging file: {temporary}"
                )
                operation_error.__cause__ = exc
    if operation_error is not None:
        raise operation_error
    try:
        verified = _verified_destination(asset, destination)
    except OSError as exc:
        raise TemplateCopyError(
            f"copied template could not be verified: {destination}"
        ) from exc
    if not verified:
        raise TemplateCopyError("copied template failed final integrity verification")
    return asset, destination
