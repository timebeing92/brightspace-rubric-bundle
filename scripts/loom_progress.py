#!/usr/bin/env python3
"""Shared progress-event process consumer for Rubric Loom journeys.

The consumer understands only the coursecraft.progress/1 event envelope used
by the Loom boards. Journey modules remain responsible for interpreting their
own final outputs; this module never infers artifacts or pipeline semantics.
"""
from __future__ import annotations

import collections
from dataclasses import dataclass
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import time

import loom_ui


@dataclass
class ProgressRun:
    return_code: int
    run_end: dict | None
    ok_steps: list[str]
    failed_step: str | None
    failed_message: str
    interrupted: bool


def consume(
    term: loom_ui.Term,
    command: list[str],
    log_path: Path,
    *,
    log_title: str,
    flavor: dict[str, str] | None = None,
    min_step_seconds: float = 0.0,
    exclusive_log: bool = False,
) -> ProgressRun:
    """Run a subprocess and render its progress-event stream.

    Non-JSON child lines pass through to the board. Completed TTY steps may be
    held for ``min_step_seconds`` as display pacing; event timings are shown
    without alteration.
    """
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_WRONLY | os.O_CREAT
        flags |= os.O_EXCL if exclusive_log else os.O_TRUNC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(log_path, flags, 0o600)
        log = os.fdopen(descriptor, "w", encoding="utf-8")
    except OSError as exc:
        return ProgressRun(
            return_code=2,
            run_end=None,
            ok_steps=[],
            failed_step=None,
            failed_message=f"could not open a safe local run log: {exc.strerror or type(exc).__name__}",
            interrupted=False,
        )
    log.write(log_title + "\n")
    log.write("started: " + time.strftime("%Y-%m-%d %H:%M:%S") + "\n---\n")

    board: loom_ui.StepBoard | None = None
    run_end: dict | None = None
    ok_steps: list[str] = []
    failed_step: str | None = None
    failed_message = ""
    steps: list[str] = []
    display_started = 0.0
    last_tick = 0.0
    paced = (not term.plain) and min_step_seconds > 0
    pending: collections.deque[dict] = collections.deque()

    def apply(event: dict) -> None:
        nonlocal board, run_end, failed_step, failed_message
        nonlocal steps, display_started
        kind = event.get("event")
        if kind == "run_start":
            steps = [str(step) for step in event.get("steps", [])]
            board = loom_ui.StepBoard(term, steps, flavor=flavor or {})
        elif kind == "step_start" and board is not None:
            display_started = time.monotonic()
            board.step_start(int(event.get("index", 0)))
        elif kind == "step_end" and board is not None:
            index = int(event.get("index", 0))
            status = str(event.get("status", "error"))
            board.step_end(index, status, float(event.get("seconds") or 0.0))
            if 1 <= index <= len(steps):
                if status == "ok":
                    ok_steps.append(steps[index - 1])
                else:
                    failed_step = steps[index - 1]
                    failed_message = str(event.get("message") or "")
        elif kind == "run_end":
            run_end = event

    def pump() -> None:
        nonlocal last_tick
        while pending:
            event = pending[0]
            if (
                paced
                and event.get("event") == "step_end"
                and board is not None
                and time.monotonic() - display_started < min_step_seconds
            ):
                break
            apply(pending.popleft())
        now = time.monotonic()
        if board is not None and now - last_tick >= 0.1:
            board.tick()
            last_tick = now

    proc = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert proc.stdout is not None
    interrupted = False
    reader_done = False
    try:
        while not reader_done or pending:
            if not reader_done:
                ready, _, _ = select.select([proc.stdout], [], [], 0.08)
                if ready:
                    line = proc.stdout.readline()
                    if not line:
                        reader_done = True
                    else:
                        log.write(line)
                        stripped = line.strip()
                        if stripped:
                            try:
                                event = json.loads(stripped)
                            except json.JSONDecodeError:
                                if board is not None:
                                    board.output_line(stripped)
                                else:
                                    print("  " + term.dim(stripped))
                            else:
                                if isinstance(event, dict):
                                    pending.append(event)
                elif proc.poll() is not None:
                    reader_done = True
            else:
                time.sleep(0.05)
            pump()
    except KeyboardInterrupt:
        interrupted = True
        try:
            if proc.poll() is None:
                proc.send_signal(signal.SIGINT)
                proc.wait(timeout=5)
        except (subprocess.TimeoutExpired, OSError, ValueError):
            proc.terminate()
    finally:
        return_code = proc.wait()
        if board is not None and not interrupted:
            board.finish()
        log.write(f"---\nchild exit: {return_code}\n")
        log.close()

    return ProgressRun(
        return_code=return_code,
        run_end=run_end,
        ok_steps=ok_steps,
        failed_step=failed_step,
        failed_message=failed_message,
        interrupted=interrupted,
    )
