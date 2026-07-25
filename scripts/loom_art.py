#!/usr/bin/env python3
"""Splash screen: a pixel-art weaving loom for the Rubric Loom wizard.

The scene is a character grid (one char = one pixel) rendered two pixel rows
per terminal line using the half-block trick: ``▀`` drawn with the upper
pixel's color as foreground and the lower pixel's color as background. Style
follows brightspace-blueprint-runner/scripts/art.py (re-authored, not
imported; see loom_ui.py for the sharing rationale). Pure stdlib.

This is a splash and nothing more: it carries no progress semantics, runs
only on a TTY, is skippable with any key, and ``--brisk``/``--plain`` get a
static one-line banner instead.
"""
from __future__ import annotations

import select
import sys
import time

# One char per pixel. Legend maps chars to 256-color indexes; '.' is transparent.
# The loom: top and bottom beams (F), side posts, warp threads (W) strung
# vertically, woven cloth (C/c) below the fell line, a shuttle (S) resting on
# the weft thread (T) it has laid, and a few sparks (*) above the frame.
SCENE = [
    "......................*.......................",
    ".....*..................................*.....",
    "..............................................",
    "..FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF...",
    "..FF.W.W.W.W.W.W.W.W.W.W.W.W.W.W.W.W.W.WFF...",
    "..FF.W.W.W.W.W.W.W.W.W*W.W.W.W.W.W.W.W.WFF...",
    "..FF.W.W.W.W.W.W.W.W.W.W.W.W.W.W.W.W.W.WFF...",
    "..FF.W.W.W.W.W.W.W.W.W.W.W.W.W.W.W.W.W.WFF...",
    "..FF.W.W.W.W.W.W.W.W.W.W.W.W.W.W.W.W.W.WFF...",
    "..FF.W.W.W.W.W.W.W.W.W.W.W.W.W.W.W.W.W.WFF...",
    "..FF.W.W.W.W.W.W.W.W.W.W.W.W.W.W.W.W.W.WFF...",
    "..FF.W.W.W.W.W.W.W.W.W.W.W.W.W.W.W*W.W.WFF...",
    "..FF.W.W.W.W.W.W.W.W.W.W.W.W.W.W.W.W.W.WFF...",
    "..FFTTTTTTTTTTsSSSSSSs.W.W.W.W.W.W.W.W.WFF...",
    "..FFCcCcCcCcCcCcCcCcCcCcCcCcCcCcCcCcCcCcFF...",
    "..FFcCcCcCcCcCcCcCcCcCcCcCcCcCcCcCcCcCcCFF...",
    "..FFCcCcCcCcCcCcCcCcCcCcCcCcCcCcCcCcCcCcFF...",
    "..FFcCcCcCcCcCcCcCcCcCcCcCcCcCcCcCcCcCcCFF...",
    "..FFCcCcCcCcCcCcCcCcCcCcCcCcCcCcCcCcCcCcFF...",
    "..FFcCcCcCcCcCcCcCcCcCcCcCcCcCcCcCcCcCcCFF...",
    "..FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF...",
    "..ff....................................ff....",
    "..ff....................................ff....",
    "..............................................",
]

# No pixel uses the UI accent index (loom_ui.ACCENT = 168): the accent is
# reserved for prompts even here, matching the family art's discipline.
PALETTE = {
    "F": 137,  # loom frame wood
    "f": 94,   # frame legs / shadow
    "W": 187,  # warp threads (undyed)
    "T": 211,  # weft thread just laid (rose)
    "S": 179,  # shuttle body
    "s": 137,  # shuttle tips
    "C": 175,  # woven cloth (rose, deliberately off-accent)
    "c": 132,  # cloth weave shadow
    "*": 222,  # sparks
    "!": 230,  # sparkle at the shuttle tip (animation only)
}

TITLE = "R U B R I C   L O O M"
SUBTITLE = "Unravel exports  ·  Weave rubric-only import packages"

# The shuttle's row and resting position in SCENE (used by the animation).
SHUTTLE_ROW = 13
SHUTTLE = "sSSSSSSs"
SHUTTLE_REST = 14      # column where the scene shows the shuttle at rest
WARP_START = 4         # first interior column between the posts
WARP_END = 39          # last interior column


def banner(term) -> None:
    """Static one-line banner for --brisk, --plain, and non-interactive runs."""
    if term.plain:
        print("RUBRIC LOOM")
        return
    print("  " + term.bold(TITLE) + "  " + term.dim("· " + SUBTITLE))


def _grid() -> list[list[str]]:
    width = max(len(row) for row in SCENE)
    return [list(row.ljust(width, ".")) for row in SCENE]


def _render(grid: list[list[str]], term) -> str:
    """Half-block render: two pixel rows per text line."""
    lines = []
    for upper_row in range(0, len(grid) - 1, 2):
        chars = []
        for col in range(len(grid[0])):
            upper = PALETTE.get(grid[upper_row][col])
            lower = PALETTE.get(grid[upper_row + 1][col])
            if upper is None and lower is None:
                chars.append(" ")
            elif upper is not None and lower is None:
                chars.append(f"\x1b[38;5;{upper}m▀\x1b[0m")
            elif upper is None and lower is not None:
                chars.append(f"\x1b[38;5;{lower}m▄\x1b[0m")
            else:
                chars.append(f"\x1b[38;5;{upper};48;5;{lower}m▀\x1b[0m")
        lines.append("  " + "".join(chars))
    return "\n".join(lines)


def _key_pressed(timeout: float) -> bool:
    """Best-effort non-blocking key check (POSIX); falls back to plain sleep."""
    try:
        ready, _, _ = select.select([sys.stdin], [], [], timeout)
        if ready:
            sys.stdin.readline()
            return True
        return False
    except (OSError, ValueError):
        time.sleep(timeout)
        return False


def _shuttle_frame(grid: list[list[str]], pos: int) -> None:
    """Place the shuttle at interior column ``pos`` with its weft trail behind.

    Mutates the working grid's shuttle row: laid thread (T) to the left,
    shuttle at pos, untouched warp ahead, and a sparkle at the leading tip.
    """
    row = grid[SHUTTLE_ROW]
    for col in range(WARP_START, WARP_END + 1):
        # Restore the warp pattern ahead of the shuttle from the warp rows.
        row[col] = SCENE[SHUTTLE_ROW - 1][col]
    for col in range(WARP_START, min(pos, WARP_END + 1)):
        row[col] = "T"
    for offset, char in enumerate(SHUTTLE):
        col = pos + offset
        if col <= WARP_END:
            row[col] = char
    tip = pos + len(SHUTTLE)
    if tip <= WARP_END:
        row[tip] = "!"


def splash(term, *, animate: bool = True, version: str = "") -> None:
    """Draw the loom. Animated on a TTY: the shuttle lays one pick of weft."""
    title_line = f"  {term.bold(TITLE)}"
    subtitle_line = "  " + term.dim(SUBTITLE + (f"  ·  {version}" if version else ""))

    if term.plain:
        banner(term)
        return

    grid = _grid()
    frame_height = (len(grid) // 2) + 3  # art lines + blank + title + subtitle

    def draw(current: list[list[str]], first: bool) -> None:
        if not first:
            sys.stdout.write(f"\x1b[{frame_height}F")
        sys.stdout.write(_render(current, term) + "\n\n")
        sys.stdout.write(title_line + "\n" + subtitle_line + "\n")
        sys.stdout.flush()

    term.hide_cursor()
    try:
        if animate:
            working = [row[:] for row in grid]
            drawn_any = False
            # Glide the shuttle from the left post to its resting position,
            # laying the weft thread behind it. Roughly a second in total;
            # any key skips ahead.
            for pos in range(WARP_START, SHUTTLE_REST + 1, 2):
                _shuttle_frame(working, pos)
                draw(working, first=not drawn_any)
                drawn_any = True
                if _key_pressed(0.12):
                    break
            draw(grid, first=not drawn_any)
        else:
            draw(grid, first=True)
    finally:
        term.show_cursor()
    print()
