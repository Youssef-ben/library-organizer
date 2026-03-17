from __future__ import annotations

import json
import sys
from typing import Callable

ProgressCallback = Callable[[int, int, str, str | None], None]


def _print_progress(current: int, total: int, prefix: str = "Progress") -> None:
    """Prints a single-line dynamic progress bar to the terminal."""
    if total <= 0:
        return
    percent = (current / total) * 100
    bar_length = 40
    filled_length = int(bar_length * current // total)
    bar = "#" * filled_length + "-" * (bar_length - filled_length)
    sys.stdout.write(f"\r{prefix}: |{bar}| {percent:.1f}% ({current}/{total})")
    sys.stdout.flush()
    if current == total:
        print()


def _progress_callback_from_format(progress_format: str) -> ProgressCallback:
    """Build a progress callback for the chosen output format (text or JSON).

    Supports both legacy 3-argument calls:
        cb(current, total, prefix)
    and new 4-argument calls:
        cb(current, total, prefix, phase)
    """
    if progress_format == "json":

        def json_progress(*args) -> None:
            # Allow both (current, total, prefix) and (current, total, prefix, phase)
            if len(args) == 3:
                current, total, prefix = args
                phase = None
            else:
                current, total, prefix, phase = args

            if total <= 0:
                return

            stage = str(prefix).strip()
            payload = {
                "type": "progress",
                "stage": stage,
                "phase": phase or stage,
                "current": current,
                "total": total,
            }
            print(json.dumps(payload), flush=True)

        return json_progress

    def text_progress(*args) -> None:
        if len(args) == 3:
            current, total, prefix = args
        else:
            current, total, prefix, _phase = args
        _print_progress(current, total, prefix)

    return text_progress

