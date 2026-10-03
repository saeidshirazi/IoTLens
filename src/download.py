"""Downloads and verifies authoritative security standard documents."""

from __future__ import annotations

import hashlib
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List

import requests

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOURCES_FILE = PROJECT_ROOT / "data" / "sources.json"


def compute_sha256(file_path: Path) -> str:
    """Compute SHA-256 digest of a file."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def load_sources(sources_path: Path = SOURCES_FILE) -> List[Dict[str, Any]]:
    """Load metadata for standard sources."""
    if not sources_path.exists():
        raise FileNotFoundError(f"Sources file not found: {sources_path}")
    with open(sources_path, "r", encoding="utf-8") as f:
        return json.load(f)


def download_source(entry: Dict[str, Any], project_root: Path = PROJECT_ROOT) -> bool:
    """Ensure a source file is downloaded and matches its recorded checksum."""
    rel_path = entry.get("path")
    if not rel_path:
        return True

    target_path = project_root / rel_path
    target_path.parent.mkdir(parents=True, exist_ok=True)

    expected_sha256 = entry.get("sha256", "")
    url = entry.get("url")

    if target_path.exists():
        actual_sha256 = compute_sha256(target_path)
        if expected_sha256 and actual_sha256 != expected_sha256:
            logger.warning(
                "Checksum mismatch for %s (expected %s, got %s). Re-downloading...",
                target_path,
                expected_sha256,
                actual_sha256,
            )
        else:
            logger.info("Validated %s (%s)", entry["source_id"], target_path)
            return True

    if not url:
        logger.error("No URL available to download %s", entry["source_id"])
        return False

    logger.info("Downloading %s from %s ...", entry["source_id"], url)
    response = requests.get(url, stream=True, timeout=30)
    response.raise_for_status()

    with open(target_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=65536):
            if chunk:
                f.write(chunk)

    actual_sha256 = compute_sha256(target_path)
    if expected_sha256 and actual_sha256 != expected_sha256:
        logger.error(
            "Downloaded file %s failed checksum validation (expected %s, got %s)",
            target_path,
            expected_sha256,
            actual_sha256,
        )
        return False

    logger.info("Successfully downloaded and validated %s", target_path)
    return True


def download_all(sources_path: Path = SOURCES_FILE, project_root: Path = PROJECT_ROOT) -> bool:
    """Download and validate all registered sources."""
    sources = load_sources(sources_path)
    success = True
    for entry in sources:
        if not download_source(entry, project_root):
            success = False
    return success


def main() -> int:
    """CLI runner for downloading sources."""
    ok = download_all()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
