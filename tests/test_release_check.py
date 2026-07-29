from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import release_check  # noqa: E402


UTC = dt.timezone.utc


def test_new_release_is_cached_and_reused_without_a_second_request(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "release_check.json"
    now = dt.datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
    calls: list[str] = []

    def fetcher(etag: str):
        calls.append(etag)
        return (
            {
                "tag_name": "v1.3.0",
                "name": "Rubric Loom v1.3.0",
                "html_url": (
                    "https://github.com/timebeing92/"
                    "brightspace-rubric-bundle/releases/tag/v1.3.0"
                ),
            },
            '"fixture-etag"',
            False,
        )

    first = release_check.check_latest_release(
        current_version="1.2.1",
        cache_path=cache_path,
        now=now,
        fetcher=fetcher,
    )
    second = release_check.check_latest_release(
        current_version="1.2.1",
        cache_path=cache_path,
        now=now + dt.timedelta(hours=1),
        fetcher=lambda etag: (_ for _ in ()).throw(AssertionError(etag)),
    )

    assert first.update_available
    assert first.latest_version == "1.3.0"
    assert first.from_cache is False
    assert second.update_available
    assert second.from_cache is True
    assert calls == [""]
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    assert payload["schema"] == release_check.SCHEMA
    assert payload["etag"] == '"fixture-etag"'


def test_network_failure_never_blocks_the_installed_loom(tmp_path: Path) -> None:
    def unavailable(etag: str):
        raise TimeoutError(f"offline {etag}")

    status = release_check.check_latest_release(
        current_version="1.2.1",
        cache_path=tmp_path / "release_check.json",
        force=True,
        fetcher=unavailable,
    )

    assert status.state == "unavailable"
    assert "offline" in status.error


def test_release_notice_is_limited_to_once_per_day(tmp_path: Path) -> None:
    cache_path = tmp_path / "release_check.json"
    now = dt.datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
    release_check.save_cache(
        cache_path,
        {
            "schema": release_check.SCHEMA,
            "checked_at_utc": release_check.utc_text(now),
            "latest_version": "1.3.0",
            "latest_tag": "v1.3.0",
        },
    )

    assert release_check.notice_is_due(
        cache_path,
        latest_version="1.3.0",
        now=now,
    )
    release_check.mark_notified(
        cache_path,
        latest_version="1.3.0",
        now=now,
    )
    assert not release_check.notice_is_due(
        cache_path,
        latest_version="1.3.0",
        now=now + dt.timedelta(hours=23),
    )
    assert release_check.notice_is_due(
        cache_path,
        latest_version="1.3.0",
        now=now + dt.timedelta(days=1),
    )


def test_version_and_release_url_validation() -> None:
    assert release_check.version_tuple("v1.2.1") == (1, 2, 1)
    assert release_check.version_tuple("1.10.3") == (1, 10, 3)
    assert release_check.version_tuple("main") is None
    assert (
        release_check.safe_release_url("https://malicious.example/update.zip")
        == release_check.RELEASES_URL
    )
    expected = (
        "https://github.com/timebeing92/"
        "brightspace-rubric-bundle/releases/tag/v1.3.0"
    )
    assert release_check.safe_release_url(expected) == expected


def test_runner_release_repository_override_is_allowlisted() -> None:
    probe = (
        "import json, release_check; "
        "print(json.dumps({"
        "'repository': release_check.RELEASE_REPOSITORY, "
        "'api_url': release_check.API_URL, "
        "'releases_url': release_check.RELEASES_URL"
        "}))"
    )
    env = dict(os.environ)
    env["RUBRIC_LOOM_RELEASE_REPOSITORY"] = (
        "timebeing92/brightspace-rubric-loom-runner"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=ROOT / "scripts",
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)

    assert payload == {
        "repository": "timebeing92/brightspace-rubric-loom-runner",
        "api_url": (
            "https://api.github.com/repos/timebeing92/"
            "brightspace-rubric-loom-runner/releases/latest"
        ),
        "releases_url": (
            "https://github.com/timebeing92/"
            "brightspace-rubric-loom-runner/releases"
        ),
    }


def test_unknown_release_repository_override_falls_back_to_bundle() -> None:
    probe = "import release_check; print(release_check.RELEASE_REPOSITORY)"
    env = dict(os.environ)
    env["RUBRIC_LOOM_RELEASE_REPOSITORY"] = "someone/unknown-repository"
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=ROOT / "scripts",
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip() == release_check.DEFAULT_RELEASE_REPOSITORY


def test_runner_can_supply_the_installed_release_version() -> None:
    probe = "import rubric_loom_wizard; print(rubric_loom_wizard.installed_version())"
    env = dict(os.environ)
    env["RUBRIC_LOOM_INSTALLED_VERSION"] = "1.0.0"
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=ROOT / "scripts",
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip() == "1.0.0"
