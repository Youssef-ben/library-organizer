from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Callable

from .compare import _full_hash
from .pipeline import _build_collision_safe_path
from .progress import ProgressCallback


def load_compare_report(input_json: Path) -> dict:
    """Load a compare_results.json report."""
    input_path = input_json.expanduser().resolve()
    if not input_path.exists():
        raise FileNotFoundError(f"Compare report not found: {input_path}")
    with input_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _safe_relative(path: Path, root: Path) -> Path | None:
    """Return path relative to root, or None if not under root."""
    try:
        return path.resolve().relative_to(root.resolve())
    except ValueError:
        return None


def sync_files(
    entries: list[dict],
    source_root: Path,
    dest_root: Path,
    dry_run: bool,
    progress_callback: ProgressCallback | None,
    label: str,
) -> tuple[list[Path], list[str]]:
    copied_paths: list[Path] = []
    errors: list[str] = []

    entries_list = list(entries)
    total = len(entries_list)
    report: Callable[[int, int, str, str], None]
    report = progress_callback or (lambda c, t, p, ph: None)

    if total == 0:
        return copied_paths, errors

    for index, entry in enumerate(entries_list, 1):
        raw_path = entry.get("path")
        digest = entry.get("hash", "")
        if not raw_path:
            errors.append("[SYNC] Missing path in entry")
            continue
        source_path = Path(raw_path).expanduser().resolve()

        rel = _safe_relative(source_path, source_root)
        if rel is None:
            errors.append(
                f"[SYNC] Path not under root: {source_path} (hash={digest})"
            )
            continue

        dest_base = dest_root / rel.parent
        try:
            dest_base.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            errors.append(
                f"[SYNC] Failed to create destination directory {dest_base}: {exc}"
            )
            continue

        dest_existing = dest_base / source_path.name
        if dest_existing.exists() and dest_existing.is_file() and digest:
            existing_result = _full_hash(dest_existing)
            if existing_result is not None and existing_result[1] == digest:
                if index % 5 == 0 or index == total:
                    report(index, total, label, f"{label}_sync")
                continue

        dest_candidate = _build_collision_safe_path(dest_base, source_path.name)

        try:
            if not dry_run:
                if not source_path.exists() or not source_path.is_file():
                    raise FileNotFoundError(source_path)
                shutil.copy2(source_path, dest_candidate)
            copied_paths.append(dest_candidate)
        except Exception as exc:
            errors.append(
                f"[SYNC] Failed to copy {source_path} -> {dest_candidate}: {exc}"
            )

        if index % 5 == 0 or index == total:
            report(index, total, label, f"{label}_sync")

    return copied_paths, errors


def run_sync(
    source_root: Path,
    target_root: Path,
    input_json: Path,
    direction: str,
    dry_run: bool,
    progress_callback: ProgressCallback | None,
) -> dict:
    """Orchestrate sync operations based on compare report and direction."""
    report = load_compare_report(input_json)

    to_target_copied = 0
    to_target_errors = 0
    to_source_copied = 0
    to_source_errors = 0

    if direction in {"to-target", "both"}:
        entries = report.get("missing_in_target", [])
        copied, errs = sync_files(
            entries,
            source_root=source_root,
            dest_root=target_root,
            dry_run=dry_run,
            progress_callback=progress_callback,
            label="to_target",
        )
        to_target_copied = len(copied)
        to_target_errors = len(errs)

    if direction in {"to-source", "both"}:
        entries = report.get("missing_in_source", [])
        # Entries are paths under target_root, so target_root acts as the source root here.
        copied, errs = sync_files(
            entries,
            source_root=target_root,
            dest_root=source_root,
            dry_run=dry_run,
            progress_callback=progress_callback,
            label="to_source",
        )
        to_source_copied = len(copied)
        to_source_errors = len(errs)

    return {
        "direction": direction,
        "to_target_copied": to_target_copied,
        "to_target_errors": to_target_errors,
        "to_source_copied": to_source_copied,
        "to_source_errors": to_source_errors,
    }

