from __future__ import annotations

import calendar
import json
import shutil
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable

from .compare import compare_folders
from .constants import SKIP_DIR_NAMES, is_media_file
from .duplicate import find_duplicates
from .extractor import configure_warning_log, get_true_date
from .progress import ProgressCallback, _progress_callback_from_format


@dataclass
class StagedFile:
    source_path: Path
    staged_path: Path
    true_date: date


def _iter_files(source_root: Path) -> list[Path]:
    """Finds all valid files while skipping the script's own output folders."""
    files: list[Path] = []
    for current_root, dir_names, file_names in source_root.walk(top_down=True):
        dir_names[:] = [name for name in dir_names if name.lower() not in SKIP_DIR_NAMES]
        for file_name in file_names:
            file_path = current_root / file_name
            if not is_media_file(file_path):
                continue
            files.append(file_path)
    return files


def _stage_source_files(source_root: Path) -> list[Path]:
    """Staging phase for flatten/all: discover source files."""
    return _iter_files(source_root)


def _iter_temporary_files(temporary_dir: Path) -> list[Path]:
    """Returns files from an existing temporary folder (non-recursive)."""
    if not temporary_dir.exists() or not temporary_dir.is_dir():
        return []
    files: list[Path] = []
    for path in temporary_dir.iterdir():
        if not path.is_file():
            continue
        if not is_media_file(path):
            continue
        files.append(path)
    return files


def _build_collision_safe_path(base_dir: Path, file_name: str) -> Path:
    """Ensures no file is overwritten by appending _1, _2, etc."""
    candidate = base_dir / file_name
    if not candidate.exists():
        return candidate

    stem = candidate.stem
    suffix = candidate.suffix
    index = 1
    while True:
        candidate = base_dir / f"{stem}_{index}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def _flatten_to_temporary(
    source_files: Iterable[Path],
    temporary_dir: Path,
    dry_run: bool,
    progress_callback: ProgressCallback | None = None,
) -> tuple[list[StagedFile], list[str]]:
    """Flattening phase: copy staged source files into a flat temporary folder."""
    staged_files: list[StagedFile] = []
    errors: list[str] = []
    files_list = list(source_files)
    total = len(files_list)
    report = progress_callback or (lambda c, t, p, ph: None)

    if not dry_run:
        if temporary_dir.exists():
            shutil.rmtree(temporary_dir)
        temporary_dir.mkdir(parents=True, exist_ok=True)

    for i, source_file in enumerate(files_list, 1):
        try:
            file_date = get_true_date(source_file)
            staged_path = _build_collision_safe_path(temporary_dir, source_file.name)
            if not dry_run:
                shutil.copy2(source_file, staged_path)
            staged_files.append(StagedFile(source_file, staged_path, file_date))
        except Exception as exc:
            errors.append(f"[FLATTEN] {source_file.name}: {exc}")
        if i % 5 == 0 or i == total:
            report(i, total, "Flattening", "flattening_to_temporary")
    return staged_files, errors


def _stage_temporary_files(
    temporary_files: Iterable[Path],
    progress_callback: ProgressCallback | None = None,
) -> tuple[list[StagedFile], list[str]]:
    """Builds staged metadata objects from already-flattened temporary files."""
    staged_files: list[StagedFile] = []
    errors: list[str] = []
    files_list = list(temporary_files)
    total = len(files_list)
    report = progress_callback or (lambda c, t, p, ph: None)

    for i, temp_file in enumerate(files_list, 1):
        try:
            file_date = get_true_date(temp_file)
            staged_files.append(StagedFile(temp_file, temp_file, file_date))
        except Exception as exc:
            errors.append(f"[STAGE] {temp_file.name}: {exc}")
        if i % 5 == 0 or i == total:
            report(i, total, "Staging", "staging_temporary")
    return staged_files, errors


def _organize_files(
    staged_files: Iterable[StagedFile],
    organized_dir: Path,
    dry_run: bool,
    progress_callback: ProgressCallback | None = None,
) -> tuple[list[Path], list[str]]:
    """Copies files from temporary folder to YYYY/MM-Month folders."""
    copied_paths: list[Path] = []
    errors: list[str] = []
    items_list = list(staged_files)
    total = len(items_list)
    report = progress_callback or (lambda c, t, p, ph: None)

    for i, item in enumerate(items_list, 1):
        try:
            year_part = f"{item.true_date.year:04d}"
            month_num = item.true_date.month
            month_part = f"{month_num:02d}-{calendar.month_name[month_num]}"
            destination_dir = organized_dir / year_part / month_part
            destination_file = _build_collision_safe_path(
                destination_dir, item.staged_path.name
            )
            if not dry_run:
                destination_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item.staged_path, destination_file)
            copied_paths.append(destination_file)
        except Exception as exc:
            errors.append(f"[ORGANIZE] {item.staged_path.name}: {exc}")
        if i % 5 == 0 or i == total:
            report(i, total, "Organizing", "organizing_to_final")
    return copied_paths, errors


def _verify_copy(staged_files: list[StagedFile], copied_paths: list[Path], dry_run: bool) -> bool:
    if dry_run:
        return True
    if len(staged_files) != len(copied_paths):
        return False
    return all(path.exists() and path.is_file() for path in copied_paths)


def _cleanup_temporary(
    temporary_dir: Path,
    should_cleanup: bool,
    dry_run: bool,
) -> tuple[bool, str]:
    if not should_cleanup:
        return False, "Skipped cleanup because verification failed."
    if dry_run:
        return True, "Dry run enabled: temporary cleanup skipped."
    if temporary_dir.exists():
        shutil.rmtree(temporary_dir)
    return True, "Temporary folder deleted."


def run_duplicate_pipeline(args) -> int:
    source_root = Path(args.source_root).expanduser().resolve()
    if not source_root.is_dir():
        print(f"Error: {source_root} is not a valid directory.")
        return 1

    candidate = source_root / "temporary"
    scan_dir: Path = candidate if candidate.exists() and candidate.is_dir() else source_root

    if not scan_dir.exists() or not scan_dir.is_dir():
        print(f"Error: {scan_dir} is not a valid directory.")
        return 1

    dupe_output = (
        Path(args.output).expanduser().resolve()
        if getattr(args, "output", None)
        else Path.cwd() / "duplicates_results.json"
    )

    progress_cb = _progress_callback_from_format(args.progress_format)
    if args.progress_format == "text":
        print("--- Running duplicate finder ---")
        print(f"Scan directory : {scan_dir}")
        print(f"Output JSON    : {dupe_output}")
    report = find_duplicates(scan_dir, dupe_output, progress_callback=progress_cb)
    if args.progress_format == "json":
        print(
            json.dumps(
                {
                    "type": "summary",
                    "action": "duplicate_finder",
                    "scanned": report["scanned"],
                    "duplicate_groups": report["duplicate_groups"],
                    "duplicate_files": report["duplicate_files"],
                    "report_path": str(dupe_output),
                }
            ),
            flush=True,
        )
    else:
        print("\n--- Duplicate summary ---")
        print(f"Scanned files     : {report['scanned']}")
        print(f"Duplicate groups  : {report['duplicate_groups']}")
        print(f"Duplicate files   : {report['duplicate_files']}")
        print(f"Report written to : {dupe_output}")
    return 0


def run_compare_pipeline(args) -> int:
    source = Path(args.source_root).expanduser().resolve()
    target = Path(args.target).expanduser().resolve()

    if not source.is_dir():
        print(f"Error: {source} is not a valid directory.")
        return 1
    if not target.is_dir():
        print(f"Error: {target} is not a valid directory.")
        return 1

    output = (
        Path(args.output).expanduser().resolve()
        if getattr(args, "output", None)
        else Path.cwd() / "compare_results.json"
    )

    progress_cb = _progress_callback_from_format(args.progress_format)

    report = compare_folders(source, target, output, progress_callback=progress_cb)

    missing_in_target_count = len(report.get("missing_in_target", []))
    missing_in_source_count = len(report.get("missing_in_source", []))

    if args.progress_format == "json":
        print(
            json.dumps(
                {
                    "type": "summary",
                    "action": "compare",
                    "source_scanned": report.get("source_scanned", 0),
                    "target_scanned": report.get("target_scanned", 0),
                    "matching_files": report.get("matching_files", 0),
                    "missing_in_target": missing_in_target_count,
                    "missing_in_source": missing_in_source_count,
                    "report_path": str(output),
                }
            ),
            flush=True,
        )
    else:
        print("\n--- Compare summary ---")
        print(f"Source scanned      : {report.get('source_scanned', 0)}")
        print(f"Target scanned      : {report.get('target_scanned', 0)}")
        print(f"Matching files      : {report.get('matching_files', 0)}")
        print(f"Missing in target   : {missing_in_target_count}")
        print(f"Missing in source   : {missing_in_source_count}")
        print(f"Report written to   : {output}")

    return 0


def run_sync_pipeline(args) -> int:
    # Local import to avoid circular dependency:
    # sync.py imports _build_collision_safe_path from pipeline.py,
    # so a top-level import here would create a cycle.
    from .sync import run_sync

    source_root = Path(args.source_root).expanduser().resolve()
    target_root = Path(args.target).expanduser().resolve()

    if not source_root.is_dir():
        print(f"Error: {source_root} is not a valid directory.")
        return 1
    if not target_root.is_dir():
        print(f"Error: {target_root} is not a valid directory.")
        return 1

    input_json = (
        Path(args.input).expanduser().resolve()
        if getattr(args, "input", None)
        else Path.cwd() / "compare_results.json"
    )
    if not input_json.exists():
        print(f"Error: Compare report not found: {input_json}")
        return 1

    output = (
        Path(args.output).expanduser().resolve()
        if getattr(args, "output", None)
        else Path.cwd() / "sync_results.json"
    )

    log_path = configure_warning_log()
    # Append a simple header so the log file is non-empty even if no warnings occur.
    log_path.parent.mkdir(parents=True, exist_ok=True)
    header_lines = [
        "##########################################",
        f"Log: {log_path.name}",
        "Action: Sync",
        f"Args: mode={args.mode}, direction={args.direction}",
        "##########################################",
        "",
    ]
    with log_path.open("a", encoding="utf-8") as f:
        f.write("\n".join(header_lines))
    progress_cb = _progress_callback_from_format(args.progress_format)

    report = run_sync(
        source_root=source_root,
        target_root=target_root,
        input_json=input_json,
        direction=args.direction,
        dry_run=args.dry_run,
        progress_callback=progress_cb,
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    has_errors = (report.get("to_target_errors", 0) or 0) > 0 or (
        report.get("to_source_errors", 0) or 0
    ) > 0

    if args.progress_format == "json":
        print(
            json.dumps(
                {
                    "type": "summary",
                    "action": "sync",
                    "direction": report.get("direction"),
                    "to_target_copied": report.get("to_target_copied", 0),
                    "to_target_errors": report.get("to_target_errors", 0),
                    "to_source_copied": report.get("to_source_copied", 0),
                    "to_source_errors": report.get("to_source_errors", 0),
                    "report_path": str(output),
                }
            ),
            flush=True,
        )
    else:
        print("\n--- Sync summary ---")
        print(f"Direction           : {report.get('direction')}")
        print(f"To-target copied    : {report.get('to_target_copied', 0)}")
        print(f"To-target errors    : {report.get('to_target_errors', 0)}")
        print(f"To-source copied    : {report.get('to_source_copied', 0)}")
        print(f"To-source errors    : {report.get('to_source_errors', 0)}")
        print(f"Report written to   : {output}")
        print(f"Log path            : {log_path.resolve()}")

    return 2 if has_errors else 0


def run_organize_pipeline(args) -> int:
    source_root = Path(args.source_root).expanduser().resolve()
    if not source_root.is_dir():
        print(f"Error: {source_root} is not a valid directory.")
        return 1

    log_path = configure_warning_log()
    action = "File Organizer"

    log_path.parent.mkdir(parents=True, exist_ok=True)
    header_lines = [
        "##########################################",
        f"Log: {log_path.name}",
        f"Action: {action}",
        f"Args: mode={args.mode}",
        "##########################################",
        "",
    ]
    with log_path.open("a", encoding="utf-8") as f:
        f.write("\n".join(header_lines))

    temp_dir = source_root / "temporary"
    org_dir = source_root / "organized"

    mode = args.mode

    source_files: list[Path] = []
    staged: list[StagedFile] = []
    final_paths: list[Path] = []
    s_errs: list[str] = []
    o_errs: list[str] = []
    is_verified = True
    cleaned = False
    cleanup_message = "Not applicable for selected mode."

    progress_cb = _progress_callback_from_format(args.progress_format)

    if mode in {"all", "flatten"}:
        # Staging phase (source): discover files
        source_files = _stage_source_files(source_root)
        if not source_files:
            print("No files found to process.")
            return 0
        if args.progress_format == "text":
            print(
                f"--- Staging from source: {len(source_files)} files discovered (mode: {mode}) ---"
            )
        # Show staging progress bar for source files
        total_staging = len(source_files)
        if total_staging > 0:
            for i, _ in enumerate(source_files, 1):
                if i % 5 == 0 or i == total_staging:
                    progress_cb(i, total_staging, "Staging", "staging_source")
        # Flattening phase: copy into temporary
        staged, s_errs = _flatten_to_temporary(
            source_files, temp_dir, args.dry_run, progress_callback=progress_cb
        )

    if mode == "flatten":
        cleanup_message = "Skipped cleanup in flatten mode."
    elif mode == "organize":
        temporary_files = _iter_temporary_files(temp_dir)
        if not temporary_files:
            print(f"Error: Temporary folder is missing or empty: {temp_dir}")
            return 1
        if args.progress_format == "text":
            print(
                f"--- Staging temporary: {len(temporary_files)} files discovered (mode: {mode}) ---"
            )
        # Staging-from-temp phase
        staged, s_errs = _stage_temporary_files(temporary_files, progress_callback=progress_cb)
        # Organizing phase
        final_paths, o_errs = _organize_files(
            staged,
            org_dir,
            args.dry_run,
            progress_callback=progress_cb,
        )
        is_verified = _verify_copy(staged, final_paths, args.dry_run)
        cleaned, cleanup_message = _cleanup_temporary(temp_dir, is_verified, args.dry_run)
    else:
        final_paths, o_errs = _organize_files(
            staged,
            org_dir,
            args.dry_run,
            progress_callback=progress_cb,
        )
        is_verified = _verify_copy(staged, final_paths, args.dry_run)
        cleaned, cleanup_message = _cleanup_temporary(temp_dir, is_verified, args.dry_run)

    if args.progress_format == "json":
        print(
            json.dumps(
                {
                    "type": "summary",
                    "action": "organize",
                    "mode": mode,
                    "scanned": len(source_files),
                    "staged": len(staged),
                    "organized": len(final_paths),
                    "errors": len(s_errs) + len(o_errs),
                    "verified": is_verified,
                    "cleanup_done": cleaned,
                    "cleanup_message": cleanup_message,
                    "log_path": str(log_path.resolve()),
                }
            ),
            flush=True,
        )
    else:
        print("\n--- Summary ---")
        print(f"Mode: {mode}")
        print(f"Total Scanned:  {len(source_files)}")
        print(f"Total Staged: {len(staged)}")
        print(f"Successfully Organized: {len(final_paths)}")
        print(f"Errors Encountered:    {len(s_errs) + len(o_errs)}")
        print(f"Verified: {is_verified}")
        print(f"Cleanup: {cleanup_message}")
        print(f"Cleanup Done: {cleaned}")
        if s_errs or o_errs:
            print(f"Check logs for details: {log_path.resolve()}")

    if not is_verified and not args.dry_run:
        print("Warning: Verification failed. Some files may not have moved correctly.")
        return 2

    return 0


def _is_within_root(root: Path, path: Path) -> bool:
    """Return True if path is a descendant of root (safety check)."""
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def run_delete_duplicates_pipeline(args) -> int:
    source_root = Path(args.source_root).expanduser().resolve()
    if not source_root.is_dir():
        print(f"Error: {source_root} is not a valid directory.")
        return 1

    input_json = (
        Path(args.input).expanduser().resolve()
        if getattr(args, "input", None)
        else Path.cwd() / "duplicates_results.json"
    )
    if not input_json.exists():
        print(f"Error: Duplicate report not found: {input_json}")
        return 1

    output = (
        Path(args.output).expanduser().resolve()
        if getattr(args, "output", None)
        else Path.cwd() / "delete_results.json"
    )

    log_path = configure_warning_log()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    header_lines = [
        "##########################################",
        f"Log: {log_path.name}",
        "Action: Delete duplicates",
        f"Args: mode={args.mode}, dry_run={args.dry_run}, input={input_json}",
        "##########################################",
        "",
    ]
    with log_path.open("a", encoding="utf-8") as f:
        f.write("\n".join(header_lines))

    try:
        with input_json.open("r", encoding="utf-8") as f:
            report = json.load(f)
    except json.JSONDecodeError as exc:
        print(f"Error: Failed to parse duplicate report {input_json}: {exc}")
        return 1

    candidate_paths: list[Path] = []
    # The 'delete' format is produced by an external tool (e.g. the Electron UI),
    # which allows the user to select a subset of duplicates before deletion.
    # Format: {"delete": {"files": ["path/to/file1", ...], "count": N}}
    # If this key is absent, fall back to the standard duplicates_results.json format.
    delete_obj = report.get("delete")
    delete_format_valid = isinstance(delete_obj, dict) and isinstance(
        delete_obj.get("files"), list
    )
    if delete_format_valid:
        files_list = delete_obj["files"]
        for item in files_list:
            if isinstance(item, str) and item.strip():
                candidate_paths.append(Path(item).expanduser())
        if "count" in delete_obj and delete_obj["count"] != len(files_list):
            with log_path.open("a", encoding="utf-8") as f:
                f.write(
                    f"[WARN] delete.count ({delete_obj['count']}) != len(files) "
                    f"({len(files_list)}). Using len(files).\n"
                )
    else:
        groups = report.get("groups")
        if isinstance(groups, list):
            for group in groups:
                files = group.get("files") if isinstance(group, dict) else None
                if not isinstance(files, list) or len(files) <= 1:
                    continue
                for entry in files[1:]:
                    if not isinstance(entry, dict):
                        continue
                    path_str = entry.get("path")
                    if isinstance(path_str, str):
                        candidate_paths.append(Path(path_str).expanduser())
        else:
            print(
                "Error: Input must be a delete list (top-level 'delete' with 'files' "
                "array) or a duplicates report ('groups' array)."
            )
            return 1

    seen_resolved: set[Path] = set()
    deduped: list[Path] = []
    for p in candidate_paths:
        try:
            r = p.resolve()
        except (OSError, RuntimeError):
            continue
        if r not in seen_resolved:
            seen_resolved.add(r)
            deduped.append(p)
    candidate_paths = deduped

    total_candidates = len(candidate_paths)
    requested = total_candidates
    deleted = 0
    missing = 0
    skipped = 0
    errors = 0

    progress_cb = _progress_callback_from_format(args.progress_format)

    for idx, raw_path in enumerate(candidate_paths, start=1):
        resolved = raw_path.resolve()
        if not _is_within_root(source_root, resolved):
            skipped += 1
            with log_path.open("a", encoding="utf-8") as f:
                f.write(
                    f"[SKIP] {resolved} is outside source_root {source_root}. "
                    "Skipping deletion.\n"
                )
            if idx % 5 == 0 or idx == total_candidates:
                progress_cb(idx, total_candidates, "Deleting", "delete_duplicates")
            continue

        if not resolved.exists():
            missing += 1
            if idx % 5 == 0 or idx == total_candidates:
                progress_cb(idx, total_candidates, "Deleting", "delete_duplicates")
            continue

        if args.dry_run:
            deleted += 1  # count what would be deleted
            if idx % 5 == 0 or idx == total_candidates:
                progress_cb(idx, total_candidates, "Deleting", "delete_duplicates")
            continue

        try:
            resolved.unlink()
            deleted += 1
        except OSError as exc:
            errors += 1
            with log_path.open("a", encoding="utf-8") as f:
                f.write(f"[ERROR] Failed to delete {resolved}: {exc}\n")
        if idx % 5 == 0 or idx == total_candidates:
            progress_cb(idx, total_candidates, "Deleting", "delete_duplicates")

    summary = {
        "requested": requested,
        "deleted": deleted,
        "missing": missing,
        "skipped": skipped,
        "errors": errors,
        "dry_run": bool(args.dry_run),
        "source_root": str(source_root),
        "input_path": str(input_json),
        "log_path": str(log_path.resolve()),
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    if args.progress_format == "json":
        print(
            json.dumps(
                {
                    "type": "summary",
                    "action": "delete-duplicate",
                    "requested": requested,
                    "deleted": deleted,
                    "missing": missing,
                    "skipped": skipped,
                    "errors": errors,
                    "dry_run": bool(args.dry_run),
                    "report_path": str(output),
                }
            ),
            flush=True,
        )
    else:
        print("\n--- Delete-duplicate summary ---")
        print(f"Requested deletions : {requested}")
        print(f"Deleted files       : {deleted}")
        print(f"Missing files       : {missing}")
        print(f"Skipped (outside root) : {skipped}")
        print(f"Errors              : {errors}")
        print(f"Dry run             : {bool(args.dry_run)}")
        print(f"Report written to   : {output}")
        print(f"Log path            : {log_path.resolve()}")

    return 2 if errors > 0 else 0

