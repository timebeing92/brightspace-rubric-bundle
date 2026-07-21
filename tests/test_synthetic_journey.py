from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_journey_weaves_validates_and_unravels(tmp_path: Path) -> None:
    journey_dir = tmp_path / "journey"
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "run_synthetic_journey.py"),
            "--output-dir",
            str(journey_dir),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    receipt = json.loads((journey_dir / "journey_receipt.json").read_text())
    assert receipt["schema"] == "brightspace-rubric-bundle.synthetic-journey/1"
    assert receipt["status"] == "ok"
    step_names = [step["name"] for step in receipt["steps"]]
    assert all(step["status"] == "ok" for step in receipt["steps"])
    assert any(name.startswith("weave:") for name in step_names)
    assert any(name.startswith("unravel:") for name in step_names)
    loop_step = next(step for step in receipt["steps"] if step["name"].startswith("loop:"))
    assert loop_step["rubric_names"]

    for key in ("rubrics_json", "rubrics_workbook", "rubrics_docx"):
        assert Path(receipt["artifacts"][key]).is_file(), key
