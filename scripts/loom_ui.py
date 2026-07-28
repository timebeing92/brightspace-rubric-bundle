#!/usr/bin/env python3
"""Reusable pure-stdlib ANSI terminal components for the Rubric Loom wizard.

Component grammar follows brightspace-blueprint-runner/scripts/ui.py
(workbench decision record 2026-07-09: reusable for future runners);
re-authored here because cross-repo code sharing awaits the ecosystem
rule-of-three decision (see docs/RUBRIC_LOOM_EXPERIENCE_FRAME.md, R3 frame).

Family palette logic: the semantic slots (supporting/good/bad/warn) are
shared across runners; the accent is per-tool and — per the family rule the
runner documents on its step board — reserved for prompts only. This kit
enforces that harder than the runner does: headings are bold, not accent.

Rendering degrades cleanly: no TTY, ``NO_COLOR``, ``TERM=dumb``, or
``--plain`` all fall back to plain text with the same information content.
"""
from __future__ import annotations

import os
import shutil
import sys
import time


# Palette (256-color indexes; chosen to hold up on light and dark themes).
ACCENT = 168       # loom thread rose — prompts only
SUPPORTING = 110   # steel blue readable detail
GOOD = 78
BAD = 203
WARN = 214


class Term:
    """Terminal capabilities + tiny styling API. All styling no-ops in plain mode."""

    def __init__(self, plain: bool = False) -> None:
        self.is_tty = sys.stdout.isatty()
        self.plain = (
            plain
            or not self.is_tty
            or os.environ.get("NO_COLOR") is not None
            or os.environ.get("TERM", "") == "dumb"
        )
        if os.name == "nt" and not self.plain:  # enable VT processing on Windows 10+
            os.system("")

    @property
    def width(self) -> int:
        return min(shutil.get_terminal_size((80, 24)).columns, 100)

    # -- styling ------------------------------------------------------------
    def _wrap(self, code: str, text: str) -> str:
        if self.plain:
            return text
        return f"\x1b[{code}m{text}\x1b[0m"

    def bold(self, text: str) -> str:
        return self._wrap("1", text)

    def dim(self, text: str) -> str:
        return self._wrap("2", text)

    def secondary(self, text: str) -> str:
        """Readable secondary text using the terminal's normal foreground.

        ANSI faint/dim intensity is highly terminal- and theme-dependent. Use
        this for prompt affordances and active narration that are visually
        secondary but still need to be read without effort.
        """
        return self._wrap("22", text)

    def italic(self, text: str) -> str:
        return self._wrap("3", text)

    def fg(self, color256: int, text: str, *, bold: bool = False) -> str:
        prefix = "1;" if bold else ""
        return self._wrap(f"{prefix}38;5;{color256}", text)

    def accent(self, text: str, *, bold: bool = False) -> str:
        """Loom thread rose. Reserved for prompts — the wizard asking for input."""
        return self.fg(ACCENT, text, bold=bold)

    def supporting(self, text: str) -> str:
        """Steel blue for readable detail that should not compete with labels."""
        return self.fg(SUPPORTING, text)

    def good(self, text: str) -> str:
        return self.fg(GOOD, text)

    def bad(self, text: str) -> str:
        return self.fg(BAD, text)

    def warn(self, text: str) -> str:
        return self.fg(WARN, text)

    # -- cursor / screen ----------------------------------------------------
    def hide_cursor(self) -> None:
        if not self.plain:
            sys.stdout.write("\x1b[?25l")

    def show_cursor(self) -> None:
        if not self.plain:
            sys.stdout.write("\x1b[?25h")

    def lines_up(self, count: int) -> None:
        if not self.plain and count > 0:
            sys.stdout.write(f"\x1b[{count}F\x1b[0J")


def visible_len(text: str) -> int:
    """Length of a string with ANSI escape sequences removed."""
    length, in_escape = 0, False
    for char in text:
        if in_escape:
            if char.isalpha():
                in_escape = False
        elif char == "\x1b":
            in_escape = True
        else:
            length += 1
    return length


def clip(text: str, width: int) -> str:
    """Truncate to a visible width, keeping ANSI escapes intact.

    In-place redraws count lines, so a line that soft-wraps corrupts the
    display; clipped output gets an ellipsis and a style reset.
    """
    if width <= 0 or visible_len(text) <= width:
        return text
    out: list[str] = []
    length, in_escape, styled = 0, False, False
    for char in text:
        if in_escape:
            out.append(char)
            if char.isalpha():
                in_escape = False
        elif char == "\x1b":
            out.append(char)
            in_escape = True
            styled = True
        else:
            if length >= width - 1:
                break
            out.append(char)
            length += 1
    return "".join(out) + "…" + ("\x1b[0m" if styled else "")


# ---------------------------------------------------------------------------
# Static components
# ---------------------------------------------------------------------------
GLYPH = {
    "ok": ("✓", "[ ok ]"),
    "bad": ("✗", "[MISS]"),
    "warn": ("!", "[warn]"),
    "todo": ("◌", "[ -- ]"),
    "run": ("◈", "[ .. ]"),
}


def status_line(term: Term, status: str, label: str, detail: str = "") -> str:
    glyph, plain_glyph = GLYPH.get(status, GLYPH["todo"])
    mark = plain_glyph if term.plain else glyph
    if status == "ok":
        mark = term.good(mark)
    elif status == "bad":
        mark = term.bad(mark)
    elif status == "warn":
        mark = term.warn(mark)
    elif status == "run":
        mark = term.bold(mark)
    text = f"  {mark} {label}"
    if detail:
        text += "  " + term.dim(detail)
    return text


def rule(term: Term, width: int | None = None) -> str:
    return term.dim(("─" if not term.plain else "-") * (width or min(term.width, 72)))


def heading(term: Term, text: str, note: str = "") -> str:
    """Section heading; `note` renders as a dim positional marker (e.g. '2 of 4').

    Bold, not accent: the loom keeps its accent for prompts only.
    """
    suffix = "  " + term.dim(f"· {note} ·") if note else ""
    return "\n" + term.bold(text) + suffix + "\n" + rule(term)


def card(term: Term, title: str, rows: list[tuple[str, str]], *, min_width: int = 44) -> str:
    """A boxed key/value panel. Rows with an empty key render as full-width
    lines. Overlong body lines soft-wrap onto continuation rows (hanging
    indent under the value column) so borders stay intact and no character
    — a path least of all — is ever lost. Styled lines that would overflow
    fall back to an ANSI-safe clip rather than risking a torn escape."""
    label_width = max((visible_len(k) for k, _ in rows if k), default=0)
    raw_lines: list[str] = []
    for key, value in rows:
        if key:
            raw_lines.append(f"{key.ljust(label_width)}  {value}")
        else:
            raw_lines.append(value)
    inner = max(
        min_width, visible_len(title) + 2, *(visible_len(line) for line in raw_lines)
    ) + 2
    inner = min(inner, term.width - 4)

    hang = " " * (label_width + 2) if label_width else ""
    body_lines: list[str] = []
    for line in raw_lines:
        if visible_len(line) <= inner:
            body_lines.append(line)
        elif "\x1b" in line:
            body_lines.append(clip(line, inner))
        else:
            segment_width = max(8, inner)
            first_width = segment_width
            rest_width = max(8, segment_width - len(hang))
            body_lines.append(line[:first_width])
            remainder = line[first_width:]
            while remainder:
                body_lines.append(hang + remainder[:rest_width])
                remainder = remainder[rest_width:]

    if term.plain:
        out = [f"-- {title} " + "-" * max(0, inner - visible_len(title) - 2)]
        out.extend("   " + line for line in body_lines)
        out.append("-" * (inner + 3))
        return "\n".join(out)
    # Top border totals inner+4 like every other box line (the family
    # reference is one dash short here; the loom squares the frame).
    top = (
        "╭─ "
        + term.bold(title)
        + " "
        + "─" * max(0, inner - visible_len(title) - 2)
        + "─╮"
    )
    out = [top]
    for line in body_lines:
        pad = " " * max(0, inner - visible_len(line))
        out.append("│ " + line + pad + " │")
    out.append("╰" + "─" * (inner + 2) + "╯")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Prompts (the only place the accent color appears)
# ---------------------------------------------------------------------------
class _Back:
    """Sentinel returned by prompts when the operator steps back."""

    def __repr__(self) -> str:  # pragma: no cover - debugging nicety
        return "<BACK>"


#: Returned by prompt_text/confirm/choose when ``allow_back`` is set and
#: the operator types ``b`` (or ``back``). Callers re-open the previous
#: screen; prompts themselves never navigate.
BACK = _Back()


def prompt_text(
    term: Term, prompt: str, *, default: str = "", allow_back: bool = False
):
    suffix = term.secondary(f" [{default}]") if default else ""
    if allow_back:
        suffix += term.secondary(" (b = back)")
    try:
        reply = input(f"  {term.accent('?')} {prompt}{suffix}: ").strip()
    except EOFError:
        print("")
        return default
    if allow_back and reply.lower() in {"b", "back"}:
        return BACK
    return reply or default


def confirm(
    term: Term,
    prompt: str,
    *,
    default: bool = False,
    assume_yes: bool = False,
    allow_back: bool = False,
):
    if assume_yes:
        print(f"  {term.accent('?')} {prompt} {term.secondary('yes (--yes)')}")
        return True
    suffix = "[Y/n]" if default else "[y/N]"
    if allow_back:
        suffix += " (b = back)"
    try:
        reply = input(
            f"  {term.accent('?')} {prompt} {term.secondary(suffix)} "
        ).strip().lower()
    except EOFError:
        print("")
        return default
    if allow_back and reply in {"b", "back"}:
        return BACK
    if not reply:
        return default
    return reply in {"y", "yes"}


def choose(
    term: Term,
    prompt: str,
    options: list[tuple[str, str]],
    *,
    default: str,
    allow_back: bool = False,
):
    """Numbered single-choice menu; returns the chosen option key."""
    print(f"  {term.accent('?')} {prompt}")
    keys = [key for key, _ in options]
    for index, (key, label) in enumerate(options, start=1):
        marker = term.secondary(" (default)") if key == default else ""
        print(f"      {term.bold(str(index))}. {label}{marker}")
    hint = f"    choice [{keys.index(default) + 1}]"
    if allow_back:
        hint += " (b = back)"
    while True:
        try:
            reply = input(hint + ": ").strip()
        except EOFError:
            print("")
            return default
        if allow_back and reply.lower() in {"b", "back"}:
            return BACK
        if not reply:
            return default
        if reply.isdigit() and 1 <= int(reply) <= len(options):
            return keys[int(reply) - 1]
        if reply in keys:
            return reply
        print(term.secondary(f"    enter 1-{len(options)}"))


def review_choice(
    term: Term,
    prompt: str,
    *,
    choices: tuple[str, ...],
    allow_back: bool = False,
    allow_quit: bool = True,
):
    """Read a review-card action.

    Return means continue, a listed number means edit that row, and the
    optional navigation keys remain available without crowding the card
    itself. This follows the Blueprint Wizard's review-before-run pattern.
    """
    hints = ["Return = continue", f"{'/'.join(choices)} = change"]
    if allow_back:
        hints.append("b = back")
    if allow_quit:
        hints.append("q = leave")
    suffix = term.secondary("  [" + " · ".join(hints) + "]")
    while True:
        try:
            reply = input(f"  {term.accent('?')} {prompt}{suffix}: ").strip().lower()
        except EOFError:
            print("")
            return ""
        if not reply:
            return ""
        if allow_back and reply in {"b", "back"}:
            return BACK
        if allow_quit and reply in {"q", "quit"}:
            return "q"
        if reply in choices:
            return reply
        valid = ", ".join(choices)
        navigation = ", b" if allow_back else ""
        navigation += ", q" if allow_quit else ""
        print(term.secondary(f"    press Return, or enter {valid}{navigation}"))


# ---------------------------------------------------------------------------
# Live step board
# ---------------------------------------------------------------------------
SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
# A small star drifting across the flavor line while a step runs.
SPARKLE = ["✦ · ·", "· ✦ ·", "· · ✦", "· ✦ ·"]


class StepBoard:
    """Live display for pipeline steps driven by progress events.

    TTY mode redraws in place; plain mode prints one line per state change.
    Step labels always come from the events that created the board — the
    board itself invents nothing.
    """

    def __init__(self, term: Term, steps: list[str], flavor: dict[str, str] | None = None) -> None:
        self.term = term
        self.steps = steps
        self.flavor = flavor or {}
        self.state = ["todo"] * len(steps)
        self.seconds = [0.0] * len(steps)
        self.current = -1
        self.started = 0.0
        self.tail: list[str] = []
        self._drawn_lines = 0
        self._spin = 0

    # -- event handlers -----------------------------------------------------
    def step_start(self, index: int) -> None:
        self.current = index - 1
        if 0 <= self.current < len(self.steps):
            self.state[self.current] = "run"
            self.started = time.monotonic()
        if self.term.plain:
            print(f"[{index}/{len(self.steps)}] {self.steps[index - 1]} ...", flush=True)
        else:
            self.draw()

    def step_end(self, index: int, status: str, seconds: float) -> None:
        slot = index - 1
        if 0 <= slot < len(self.steps):
            self.state[slot] = "ok" if status == "ok" else "bad"
            self.seconds[slot] = seconds
        if self.term.plain:
            print(f"[{index}/{len(self.steps)}] {'done' if status == 'ok' else 'FAILED'} "
                  f"({seconds:.1f}s)", flush=True)
        else:
            self.draw()

    def output_line(self, line: str) -> None:
        line = line.rstrip()
        if not line:
            return
        self.tail.append(line)
        self.tail = self.tail[-4:]
        if self.term.plain:
            print(f"    | {line}", flush=True)
        else:
            self.draw()

    def tick(self) -> None:
        if not self.term.plain and 0 <= self.current < len(self.steps):
            self._spin += 1
            self.draw()

    # -- rendering ----------------------------------------------------------
    def draw(self) -> None:
        term = self.term
        term.lines_up(self._drawn_lines)
        lines: list[str] = []
        for index, label in enumerate(self.steps):
            state = self.state[index]
            if state == "run":
                # The accent (loom rose) is reserved for prompts — the wizard
                # asking for input — so the spinner and sparkle stay neutral.
                mark = term.bold(SPINNER[self._spin % len(SPINNER)])
                elapsed = time.monotonic() - self.started
                suffix = term.dim(f"{elapsed:5.1f}s")
                lines.append(f"  {mark} {term.bold(label)}  {suffix}")
                flavor = self.flavor.get(label)
                if flavor:
                    twinkle = SPARKLE[(self._spin // 2) % len(SPARKLE)]
                    lines.append("")
                    lines.append(
                        "        "
                        + term.italic(term.secondary(flavor))
                        + "  "
                        + term.secondary(twinkle)
                    )
                    lines.append("")
            elif state == "ok":
                lines.append(f"  {term.good('✓')} {label}  {term.dim(f'{self.seconds[index]:5.1f}s')}")
            elif state == "bad":
                lines.append(f"  {term.bad('✗')} {term.bold(label)}")
            else:
                lines.append(term.dim(f"  ○ {label}"))
        if self.tail:
            lines.append(term.dim("  ┆ " + "·" * 3))
            width = term.width - 6
            for raw in self.tail:
                lines.append(term.dim("  ┆ " + raw[:width]))
        limit = max(20, term.width - 2)
        lines = [clip(line, limit) for line in lines]
        sys.stdout.write("\n".join(lines) + "\n")
        sys.stdout.flush()
        self._drawn_lines = len(lines)

    def finish(self) -> None:
        self.current = -1
        if not self.term.plain:
            self.draw()
