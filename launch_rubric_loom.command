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
  C_ROSE=$'\033[38;5;168m'
else
  C_RESET=""
  C_DIM=""
  C_BOLD=""
  C_ROSE=""
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
  printf "%b%s%b\n" "$C_DIM" "$BOOTSTRAP_PY scripts/bootstrap_env.py --dev" "$C_RESET"
  if ! "$BOOTSTRAP_PY" "$REPO_DIR/scripts/bootstrap_env.py" --dev; then
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

printf "  %b%s%b\n" "$C_ROSE$C_BOLD" "RUBRIC LOOM" "$C_RESET"
printf "  %b%s%b\n" "$C_DIM" "Brightspace rubrics -> readable cloth" "$C_RESET"
echo
printf "%b%s%b\n" "$C_BOLD" "Choose:" "$C_RESET"
printf "  %b1.%b Open the loom %b(guided wizard; pick or drag a source inside)%b\n" "$C_BOLD" "$C_RESET" "$C_DIM" "$C_RESET"
printf "  %b2.%b Demonstration unravel %b(the pinned synthetic fixture)%b\n" "$C_BOLD" "$C_RESET" "$C_DIM" "$C_RESET"
printf "  %b3.%b Workshop doctor %b(environment checks only)%b\n" "$C_BOLD" "$C_RESET" "$C_DIM" "$C_RESET"
echo
read -r -p "Selection [1]: " CHOICE || CHOICE=""
CHOICE="${CHOICE:-1}"

case "$CHOICE" in
  1) ARGS=() ;;
  2) ARGS=("--source" "$REPO_DIR/tests/fixtures/tiny_rubrics_export") ;;
  3) ARGS=("--doctor") ;;
  q|Q) echo "The loom stays idle."; hold_open; exit 0 ;;
  *)
    echo "Unknown selection: $CHOICE"
    hold_open
    exit 2
    ;;
esac

echo
"$PYTHON" "$REPO_DIR/scripts/rubric_loom_wizard.py" "${ARGS[@]+"${ARGS[@]}"}"
STATUS=$?
echo
if [ "$STATUS" -eq 0 ]; then
  printf "%b%s%b\n" "$C_ROSE" "The loom rests." "$C_RESET"
else
  echo "The loom exited with status $STATUS."
fi
hold_open
exit "$STATUS"
