"""The loom UI kit degrades cleanly: plain mode carries the same
information with zero escape bytes, and clipping never corrupts styles."""
from __future__ import annotations

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import loom_art  # noqa: E402
import loom_ui  # noqa: E402


def plain_term() -> loom_ui.Term:
    return loom_ui.Term(plain=True)


def test_plain_components_emit_no_escape_bytes(capsys) -> None:
    term = plain_term()
    pieces = [
        loom_ui.heading(term, "The workshop", "1 of 4"),
        loom_ui.rule(term),
        loom_ui.status_line(term, "ok", "check", "detail"),
        loom_ui.status_line(term, "bad", "check"),
        loom_ui.status_line(term, "warn", "check"),
        loom_ui.card(term, "Ready", [("key", "value"), ("", "full width")]),
    ]
    board = loom_ui.StepBoard(term, ["one", "two"])
    board.step_start(1)
    board.output_line("child says hi")
    board.step_end(1, "ok", 0.5)
    board.step_start(2)
    board.step_end(2, "error", 0.1)
    captured = capsys.readouterr()
    text = "\n".join(pieces) + captured.out + captured.err
    assert "\x1b" not in text
    assert "[1/2] one ..." in captured.out
    assert "child says hi" in captured.out
    assert "FAILED" in captured.out


def test_plain_mode_activates_for_dumb_terminals(monkeypatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    term = loom_ui.Term()
    assert term.plain is True
    monkeypatch.delenv("NO_COLOR")
    monkeypatch.setenv("TERM", "dumb")
    assert loom_ui.Term().plain is True


def test_visible_len_and_clip_keep_escapes_intact() -> None:
    styled = "\x1b[1mhello\x1b[0m world"
    assert loom_ui.visible_len(styled) == len("hello world")
    clipped = loom_ui.clip(styled, 7)
    assert loom_ui.visible_len(clipped) <= 7
    assert clipped.endswith("\x1b[0m")
    assert loom_ui.clip("short", 10) == "short"


def test_card_plain_mode_carries_every_row() -> None:
    term = plain_term()
    text = loom_ui.card(
        term, "Ready to unravel", [("source", "input/demo.zip"), ("label", "demo")]
    )
    assert "Ready to unravel" in text
    assert "source" in text and "input/demo.zip" in text
    assert "label" in text and "demo" in text
    assert "╭" not in text  # box drawing stays out of plain mode


def test_banner_plain_is_a_single_plain_line(capsys) -> None:
    loom_art.banner(plain_term())
    captured = capsys.readouterr()
    assert captured.out.strip() == "RUBRIC LOOM"
    assert "\x1b" not in captured.out


def test_card_wraps_long_rows_without_shattering_borders(monkeypatch) -> None:
    """A long path row must never push the right border off the box: the
    card wraps it onto continuation rows, character-exactly."""
    monkeypatch.setenv("COLUMNS", "80")
    monkeypatch.setenv("LINES", "24")
    term = loom_ui.Term()  # non-tty -> plain capability, but geometry holds
    long_path = "/very/deep/" + "segment/" * 18 + "bundle_dir"
    boxed = loom_ui.card(term, "Ready", [("bundle", long_path), ("label", "x")])
    lines = boxed.splitlines()
    assert all(loom_ui.visible_len(line) <= 80 for line in lines)
    # Character-exact wrap: removing whitespace, the full path survives.
    flattened = "".join(line.strip() for line in lines)
    assert long_path.replace(" ", "") in flattened.replace(" ", "")


def test_prompts_return_back_sentinel_only_when_allowed(monkeypatch, capsys) -> None:
    term = plain_term()
    answers = iter(["b", "back", "b", "b", "b"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    assert loom_ui.prompt_text(term, "Label", default="x", allow_back=True) is loom_ui.BACK
    assert loom_ui.confirm(term, "Sure?", default=True, allow_back=True) is loom_ui.BACK
    assert (
        loom_ui.choose(term, "Pick", [("1", "one")], default="1", allow_back=True)
        is loom_ui.BACK
    )
    # Without allow_back, 'b' stays an ordinary answer.
    assert loom_ui.prompt_text(term, "Label", default="x") == "b"
    assert loom_ui.confirm(term, "Sure?", default=True) is False
    capsys.readouterr()


def test_back_hint_appears_only_when_allowed(monkeypatch, capsys) -> None:
    term = plain_term()
    prompts: list[str] = []

    def fake_input(prompt: str = "") -> str:
        prompts.append(prompt)
        return ""

    monkeypatch.setattr("builtins.input", fake_input)
    loom_ui.prompt_text(term, "Label", default="x", allow_back=True)
    loom_ui.prompt_text(term, "Label", default="x")
    assert "(b = back)" in prompts[0]
    assert "(b = back)" not in prompts[1]
    capsys.readouterr()


def test_card_box_mode_keeps_borders_aligned(monkeypatch) -> None:
    monkeypatch.setenv("COLUMNS", "80")
    monkeypatch.setenv("LINES", "24")
    term = loom_ui.Term(plain=False)
    term.plain = False  # force box mode regardless of tty
    long_path = "/very/deep/" + "segment/" * 18 + "bundle_dir"
    boxed = loom_ui.card(term, "Ready", [("bundle", long_path)])
    lines = boxed.splitlines()
    body = [line for line in lines if line.startswith("│")]
    assert body, boxed
    widths = {loom_ui.visible_len(line) for line in lines}
    assert len(widths) == 1  # every box line, borders included, aligns
    assert max(widths) <= 80
