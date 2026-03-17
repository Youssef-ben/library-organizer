from __future__ import annotations

import sys

from . import __version__
from .cli import parse_args
from .pipeline import (
    run_compare_pipeline,
    run_delete_duplicates_pipeline,
    run_duplicate_pipeline,
    run_organize_pipeline,
    run_sync_pipeline,
)


def main() -> None:
    if "--version" in sys.argv:
        print(f"v{__version__}")
        sys.exit(0)
    args = parse_args()
    if args.mode == "find-duplicate":
        exit_code = run_duplicate_pipeline(args)
    elif args.mode == "compare":
        exit_code = run_compare_pipeline(args)
    elif args.mode == "sync":
        exit_code = run_sync_pipeline(args)
    elif args.mode == "delete-duplicate":
        exit_code = run_delete_duplicates_pipeline(args)
    else:
        exit_code = run_organize_pipeline(args)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()

