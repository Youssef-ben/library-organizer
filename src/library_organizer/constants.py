from __future__ import annotations

from pathlib import Path

# Centralized configuration for media files and directory skipping.
# Only files with these extensions are considered by scanning/compare/duplicate logic.

IMAGE_FILE_EXTENSIONS: set[str] = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".bmp",
    ".tiff",
    ".tif",
    ".webp",
}

VIDEO_FILE_EXTENSIONS: set[str] = {
    ".mp4",
    ".mkv",
    ".avi",
    ".mov",
    ".wmv",
    ".flv",
    ".webm",
    ".m4v",
}

# Directories that should be skipped during scanning/walking.
SKIP_DIR_NAMES: set[str] = {"temporary", "organized", "logs"}


def is_media_file(path: Path) -> bool:
    """
    Return True if the path has an image or video extension.
    """
    suffix = path.suffix.lower()
    return suffix in IMAGE_FILE_EXTENSIONS or suffix in VIDEO_FILE_EXTENSIONS

