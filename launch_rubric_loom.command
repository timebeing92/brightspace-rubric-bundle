#!/bin/bash
# Double-clickable launcher for the Rubric Loom wizard (macOS).
# Finder opens this in Terminal; it also runs fine as
#   bash launch_rubric_loom.command
# First run offers to build the .venv via scripts/bootstrap_env.py.

set -u

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$REPO_DIR" || exit 1

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  C_RESET=$'\033[0m'
  C_DIM=$'\033[2m'
  C_BOLD=$'\033[1m'
else
  C_RESET=""
  C_DIM=""
  C_BOLD=""
fi

hold_open() {
  # Keep a Finder-opened Terminal window readable; harmless when piped.
  if [ -t 0 ]; then
    echo
    read -r -p "Press Return to close this Terminal window. " _ || true
  fi
}

PYTHON="$REPO_DIR/.venv/bin/python"

first_time_setup() {
  echo
  printf "%b%s%b\n" "$C_BOLD" "The loom is not yet threaded on this machine (.venv missing)." "$C_RESET"
  printf "%s\n" "First-time setup creates a local Python environment; nothing is"
  printf "%s\n" "installed outside this folder."
  BOOTSTRAP_PY=""
  for candidate in python3.13 python3.12 python3.11; do
    if command -v "$candidate" >/dev/null 2>&1; then
      BOOTSTRAP_PY="$(command -v "$candidate")"
      break
    fi
  done
  if [ -z "$BOOTSTRAP_PY" ]; then
    echo
    echo "No Python 3.11-3.13 was found on PATH. Install one (for example"
    echo "python3.13 from python.org), then relaunch."
    hold_open
    exit 1
  fi
  echo
  printf "%s" "Set it up now with $BOOTSTRAP_PY? [Y/n] "
  read -r REPLY || REPLY=""
  case "${REPLY:-Y}" in
    n|N|no|NO)
      echo "Setup skipped; the loom stays idle."
      hold_open
      exit 0
      ;;
  esac
  echo
  printf "%b%s%b\n" "$C_DIM" "$BOOTSTRAP_PY scripts/bootstrap_env.py --locked" "$C_RESET"
  if ! "$BOOTSTRAP_PY" "$REPO_DIR/scripts/bootstrap_env.py" --locked; then
    echo
    echo "Setup did not finish; the message above says why."
    hold_open
    exit 1
  fi
  PYTHON="$REPO_DIR/.venv/bin/python"
}

if [ ! -x "$PYTHON" ]; then
  first_time_setup
fi

if [ -t 1 ]; then
  printf '\033]0;Rubric Loom\007'
fi

echo
"$PYTHON" "$REPO_DIR/scripts/rubric_loom_wizard.py" "$@"
STATUS=$?
echo
if [ "$STATUS" -eq 0 ]; then
  printf "%b%s%b\n" "$C_ROSE" "The loom rests." "$C_RESET"
else
  echo "The loom exited with status $STATUS."
fi
hold_open
exit "$STATUS"
