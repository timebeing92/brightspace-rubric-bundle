"""Real interpreter boundaries; dependency installers are never executed."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import venv

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def make_environment(path: Path) -> Path:
    venv.EnvBuilder(with_pip=False, symlinks=os.name != "nt").create(path)
    return path / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def probe(python: Path, target: Path, body: str) -> dict:
    source = (
        "import json, os, sys, subprocess, venv\n"
        "from pathlib import Path\n"
        f"sys.path.insert(0, {str(SCRIPTS)!r})\n"
        "import rubric_loom_wizard as wizard\n"
        "wizard.loom_ui.confirm = lambda *a, **k: True\n"
        + body
    )
    result = subprocess.run(
        [str(python), "-I", "-c", source],
        env={**os.environ, "RUBRIC_LOOM_VENV": str(target)},
        text=True, capture_output=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(next(line[7:] for line in result.stdout.splitlines() if line.startswith("RESULT=")))


@pytest.mark.parametrize("current", ["base", "sibling", "private", "base_as_target"])
def test_repair_identifies_real_environment_and_never_installs_into_other_python(
    tmp_path: Path, current: str,
) -> None:
    target = tmp_path / "private runtime"
    private_python = make_environment(target)
    python = Path(sys._base_executable)
    if current == "private":
        python = private_python
    elif current == "sibling":
        python = make_environment(tmp_path / "unrelated environment")
    elif current == "base_as_target":
        target = Path(sys.base_prefix)
    result = probe(python, target, '''
commands = []
def no_install(command, **kwargs):
    commands.append(command)
    return subprocess.CompletedProcess(command, 1)
wizard.subprocess.run = no_install
private = wizard.running_in_local_venv()
wizard.repair_runtime_dependencies(wizard.loom_ui.Term(plain=True), ["jsonschema"], assume_yes=True)
print("RESULT=" + json.dumps({"private": private, "commands": commands}))
''')
    assert result["private"] is (current == "private")
    command = result["commands"][0]
    if current == "private":
        assert command == [str(private_python), "-m", "pip", "install", "-r", str(SCRIPTS.parent / "requirements-lock.txt")]
    else:
        assert command == [str(python), str(SCRIPTS / "bootstrap_env.py"), "--locked", "--venv", str(target.resolve())]


def test_fresh_bootstrap_restarts_into_the_new_private_environment(tmp_path: Path) -> None:
    target = tmp_path / "new private environment"
    result = probe(Path(sys._base_executable), target, '''
commands = []
restarts = []
class Restarted(Exception):
    pass
def bootstrap_without_install(command, **kwargs):
    assert command[1] == str(wizard.SCRIPTS / "bootstrap_env.py"), command
    commands.append(command)
    venv.EnvBuilder(with_pip=False, symlinks=os.name != "nt").create(wizard.VENV_ROOT)
    return subprocess.CompletedProcess(command, 0)
def record_restart(executable, argv):
    restarts.append([executable, argv])
    raise Restarted()
wizard.subprocess.run = bootstrap_without_install
wizard.os.execv = record_restart
wizard.missing_runtime_packages = lambda: []
wizard.runtime_lock_mismatches = lambda: []
try:
    wizard.repair_runtime_dependencies(wizard.loom_ui.Term(plain=True), ["jsonschema"], assume_yes=True)
except Restarted:
    pass
print("RESULT=" + json.dumps({"commands": commands, "restarts": restarts}))
''')
    python = target / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    assert len(result["commands"]) == 1
    assert len(result["restarts"]) == 1
    executable, argv = result["restarts"][0]
    assert executable == str(python)
    assert argv[:2] == [str(python), str(SCRIPTS / "rubric_loom_wizard.py")]
