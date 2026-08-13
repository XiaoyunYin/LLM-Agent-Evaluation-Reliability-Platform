"""Download and pin the Spider 1.0 benchmark plus the official execution evaluator.

Two separate artifacts are needed, and they come from different places:

1. The benchmark archive (`spider_data.zip`) holds `dev.json`, `tables.json`,
   `dev_gold.sql`, and the `database/` folder of SQLite files. Execution-based
   verification is impossible without the actual databases, which is why the
   HuggingFace parquet mirrors of Spider are not sufficient - they carry the
   questions and gold SQL but no databases.

2. The official evaluator (`taoyds/test-suite-sql-eval`). Result-comparison
   semantics for SQL are subtle (row order, duplicate rows, column permutation),
   so P0 vendors the established implementation rather than writing its own.

Both are checksummed and recorded in `datasets/spider/PIN.json` so the benchmark
version is pinned rather than "whatever downloaded that day".

Usage:
    python scripts/download_spider.py
    python scripts/download_spider.py --force
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DATASET_ROOT = REPO_ROOT / "datasets" / "spider"
DOWNLOAD_DIR = DATASET_ROOT / "_download"
EVALUATOR_DIR = REPO_ROOT / "backend" / "app" / "spider" / "official_eval"
PIN_PATH = DATASET_ROOT / "PIN.json"

# Canonical Spider 1.0 archive published by the Yale LILY group.
SPIDER_ARCHIVE_URL = (
    "https://drive.usercontent.google.com/download"
    "?id=1TqleXec_OykOYFREKKtschzY29dUcVAQ&export=download&confirm=t"
)
SPIDER_ARCHIVE_NAME = "spider_data.zip"

# The official test-suite evaluator. `master` is pinned by content hash below
# rather than by commit, because the repository publishes no tags.
EVALUATOR_BASE_URL = (
    "https://raw.githubusercontent.com/taoyds/test-suite-sql-eval/master/"
)
EVALUATOR_FILES = ("evaluation.py", "exec_eval.py", "process_sql.py", "parse.py")

# Files that must exist inside the extracted archive for it to be usable.
REQUIRED_DATASET_FILES = ("dev.json", "tables.json", "dev_gold.sql")


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "llm-eval-platform/0.1"})
    with urllib.request.urlopen(request, timeout=300) as response:
        total = response.headers.get("Content-Length")
        total_bytes = int(total) if total else None
        written = 0
        with destination.open("wb") as handle:
            while True:
                block = response.read(1024 * 256)
                if not block:
                    break
                handle.write(block)
                written += len(block)
                if total_bytes:
                    percent = 100 * written / total_bytes
                    print(
                        f"\r  {destination.name}: {written / 1e6:.1f}"
                        f"/{total_bytes / 1e6:.1f} MB ({percent:.0f}%)",
                        end="",
                        flush=True,
                    )
    if total_bytes:
        print()


def flatten_extracted(extract_root: Path) -> Path:
    """Return the directory that actually holds dev.json.

    The archive has been published with different top-level folder names over
    time (`spider/`, `spider_data/`), so the layout is discovered rather than
    assumed.
    """
    if (extract_root / "dev.json").exists():
        return extract_root

    for candidate in sorted(extract_root.iterdir()):
        if candidate.is_dir() and (candidate / "dev.json").exists():
            return candidate

    raise FileNotFoundError(
        f"No dev.json found under {extract_root}. Archive layout changed."
    )


def install_dataset(archive_path: Path, force: bool) -> dict:
    marker = DATASET_ROOT / "dev.json"
    if marker.exists() and not force:
        print(f"Dataset already installed at {DATASET_ROOT}. Use --force to re-extract.")
    else:
        staging = DOWNLOAD_DIR / "_extract"
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True)

        print(f"Extracting {archive_path.name} ...")
        with zipfile.ZipFile(archive_path) as archive:
            archive.extractall(staging)

        source = flatten_extracted(staging)
        for item in source.iterdir():
            if item.name.startswith("_") or item.name == "__MACOSX":
                continue
            target = DATASET_ROOT / item.name
            if target.exists():
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
            shutil.move(str(item), str(target))
        shutil.rmtree(staging, ignore_errors=True)

    missing = [
        name for name in REQUIRED_DATASET_FILES if not (DATASET_ROOT / name).exists()
    ]
    if missing:
        raise FileNotFoundError(f"Spider install incomplete, missing: {missing}")

    database_dir = DATASET_ROOT / "database"
    sqlite_files = sorted(database_dir.rglob("*.sqlite"))
    dev_rows = json.loads((DATASET_ROOT / "dev.json").read_text(encoding="utf-8"))

    return {
        "dev_examples": len(dev_rows),
        "databases": len(sqlite_files),
        "tables_json_sha256": sha256_of(DATASET_ROOT / "tables.json"),
        "dev_json_sha256": sha256_of(DATASET_ROOT / "dev.json"),
    }


def install_evaluator(force: bool) -> dict:
    EVALUATOR_DIR.mkdir(parents=True, exist_ok=True)
    (EVALUATOR_DIR / "__init__.py").write_text(
        '"""Vendored copy of the official Spider test-suite evaluator.\n\n'
        "Downloaded by scripts/download_spider.py. Do not edit by hand - the\n"
        "point of vendoring is that result-comparison semantics match the\n"
        "published implementation exactly.\n"
        '"""\n',
        encoding="utf-8",
    )

    hashes: dict[str, str] = {}
    for name in EVALUATOR_FILES:
        target = EVALUATOR_DIR / name
        if target.exists() and not force:
            hashes[name] = sha256_of(target)
            continue
        url = EVALUATOR_BASE_URL + name
        try:
            download(url, target)
        except Exception as error:  # noqa: BLE001 - parse.py is optional
            if name == "parse.py":
                print(f"  optional {name} unavailable ({error}); skipping")
                continue
            raise
        hashes[name] = sha256_of(target)
        print(f"  vendored {name}")

    return hashes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download and re-extract even if artifacts already exist.",
    )
    args = parser.parse_args()

    DATASET_ROOT.mkdir(parents=True, exist_ok=True)
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    archive_path = DOWNLOAD_DIR / SPIDER_ARCHIVE_NAME
    if archive_path.exists() and not args.force:
        print(f"Using cached archive {archive_path} ({archive_path.stat().st_size / 1e6:.1f} MB)")
    else:
        print(f"Downloading Spider archive from {SPIDER_ARCHIVE_URL[:60]}...")
        download(SPIDER_ARCHIVE_URL, archive_path)

    archive_sha = sha256_of(archive_path)
    print(f"Archive sha256: {archive_sha}")

    dataset_info = install_dataset(archive_path, args.force)
    print("Vendoring official evaluator ...")
    evaluator_hashes = install_evaluator(args.force)

    pin = {
        "benchmark": "spider-1.0",
        "pinned_at": datetime.now(timezone.utc).isoformat(),
        "archive_url": SPIDER_ARCHIVE_URL,
        "archive_sha256": archive_sha,
        "archive_bytes": archive_path.stat().st_size,
        "evaluator_source": EVALUATOR_BASE_URL,
        "evaluator_file_sha256": evaluator_hashes,
        **dataset_info,
    }
    PIN_PATH.write_text(json.dumps(pin, indent=2) + "\n", encoding="utf-8")

    print()
    print(f"Dev examples:  {dataset_info['dev_examples']}")
    print(f"Databases:     {dataset_info['databases']}")
    print(f"Pin written:   {PIN_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
