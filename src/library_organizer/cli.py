from __future__ import annotations

import argparse

from . import __version__


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Scan, find duplicates and organize a media library into a clean "
            "folder structure."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
        help="Show program version and exit.",
    )
    parser.add_argument(
        "source_root",
        help="Root folder to scan recursively.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview actions without modifying original files.",
    )
    parser.add_argument(
        "--mode",
        choices=(
            "all",
            "flatten",
            "organize",
            "find-duplicate",
            "compare",
            "sync",
            "delete-duplicate",
        ),
        default="all",
        help=(
            "Execution mode: 'all' (default) runs flatten then organize, "
            "'flatten' only flattens into a temporary folder, "
            "'organize' organizes from an existing temporary folder, "
            "'find-duplicate' runs the duplicate finder, "
            "'compare' compares two folders by content hash, "
            "'sync' copies missing files between source and target based on a compare "
            "report, and 'delete-duplicate' deletes duplicate files based on a "
            "duplicates_results.json report."
        ),
    )
    parser.add_argument(
        "--output",
        help=(
            "Path for the output report JSON. Used by find-duplicate, compare, sync, and "
            "delete-duplicate modes. Defaults to a mode-specific filename in the current "
            "working directory if not provided."
        ),
    )
    parser.add_argument(
        "--target",
        help=(
            "Target folder to compare/sync against (required for --mode compare and --mode sync)."
        ),
    )
    parser.add_argument(
        "--direction",
        choices=("to-target", "to-source", "both"),
        help="Sync direction (required for --mode sync).",
    )
    parser.add_argument(
        "--input",
        help=(
            "Path to compare_results.json (used by --mode sync). "
            "Defaults to ./compare_results.json."
        ),
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Required when using --direction both without --dry-run.",
    )
    parser.add_argument(
        "--progress-format",
        choices=("text", "json"),
        default="text",
        help=(
            "Output format for progress: 'text' (default) for terminal progress bar, "
            " 'json' for one JSON object per line (e.g. for Electron/GUI)."
        ),
    )
    args = parser.parse_args()

    if args.mode == "compare" and not args.target:
        parser.error("--target is required when using --mode compare")

    if args.mode == "sync" and not args.direction:
        parser.error("--direction is required when using --mode sync")
    if args.mode == "sync" and not args.target:
        parser.error("--target is required when using --mode sync")
    if (
        args.mode == "sync"
        and args.direction == "both"
        and not args.dry_run
        and not args.confirm
    ):
        parser.error("--confirm is required when using --direction both without --dry-run")

    return args
