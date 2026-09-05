"""Offline import and synthetic-cache baseline. Run with the development Python.

Prints JSON to stdout; creates data only in a TemporaryDirectory. This is not a
browser provisioning benchmark: no network, executable launch, or real download.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from collections.abc import Sequence
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any

import aselenium
from aselenium.manager._cache import digest
from aselenium.manager.file import ChromeFileManager
from aselenium.manager.version import ChromiumVersion


def summarize(values: Sequence[float]) -> dict[str, Any]:
    """Return the median, extrema, and original benchmark samples.

    Args:
        values: Input values evaluated in order by this operation.

    Returns:
        The median, extrema, and original benchmark samples.
    """
    return {
        "median": statistics.median(values),
        "min": min(values),
        "max": max(values),
        "samples": values,
    }


def import_samples(count: int, cwd: Path) -> list[dict[str, Any]]:
    """Measure fresh-interpreter package import time and resident memory.

    Args:
        count: Number of independent measurements to collect.
        cwd: Working directory used by the isolated subprocess.

    Returns:
        The import samples values in order.
    """
    code = """
import time
start = time.perf_counter()
import aselenium
duration = time.perf_counter() - start
import json, psutil
print(json.dumps({'milliseconds': duration * 1000, 'rss_bytes': psutil.Process().memory_info().rss}))
"""
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    return [
        json.loads(
            subprocess.run(
                [sys.executable, "-c", code],
                cwd=cwd,
                env=environment,
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            ).stdout
        )
        for _ in range(count)
    ]


def cache_samples(
    root: Path, size: int, samples: int, iterations: int
) -> dict[str, Any]:
    """Benchmark synthetic SQLite cache lookups in a disposable directory.

    Args:
        root: Anchored root directory of the managed filesystem operation.
        size: Declared member size in bytes.
        samples: Number of repeated benchmark samples to collect.
        iterations: Operations executed within each timed sample.

    Returns:
        A mapping containing the cache samples data.
    """
    base = root / str(size)
    base.mkdir()
    manager = ChromeFileManager(base)
    for patch in range(size):
        seeded_version = "120.0.6099.%d" % patch
        key = manager._key("driver", seeded_version)
        folder = manager._directory / key
        folder.mkdir()
        location = folder / "chromedriver.fixture"
        location.write_bytes(b"not an executable; benchmark fixture only\\n")
        manager._publish(
            dict(
                key=key,
                product=manager.product,
                platform=manager._platform,
                kind="driver",
                version=seeded_version,
                executable=location.name,
                sha256=digest(location),
                created=patch,
            )
        )
    hit = ChromiumVersion("120.0.6099.%d" % (size - 1))
    miss = ChromiumVersion("999.0.0.1")
    matched = manager.match_driver(hit)
    if matched is None:
        raise RuntimeError("Synthetic cache exact-hit lookup returned no entry")
    if matched["version"] != hit:
        raise RuntimeError(
            "Synthetic cache exact-hit lookup returned the wrong version"
        )
    if manager.match_driver(miss) is not None:
        raise RuntimeError("Synthetic cache exact-miss lookup returned an entry")

    results: dict[str, Any] = {}
    for label, query_version in [("exact_hit_us", hit), ("exact_miss_us", miss)]:
        # Warm the query machinery once; setup/seed costs are not measured.
        manager.match_driver(query_version)
        timings = []
        for _ in range(samples):
            start = time.perf_counter()
            for _ in range(iterations):
                manager.match_driver(query_version)
            timings.append((time.perf_counter() - start) * 1_000_000 / iterations)
        results[label] = summarize(timings)

    reads = []
    for _ in range(samples):
        start = time.perf_counter()
        with manager._db() as db:
            db.execute("SELECT count(*) FROM artifacts").fetchone()
        reads.append((time.perf_counter() - start) * 1000)
    results["sqlite_open_query_ms"] = summarize(reads)
    results["metadata_bytes"] = manager._database.stat().st_size
    return {"entries": size, **results}


def positive_int(value: str) -> int:
    """Parse a positive integer command-line argument.

    Args:
        value: A positive integer command-line argument supplied for validation.

    Returns:
        A positive integer command-line argument.
    """
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be positive")
    return number


def source_identity() -> dict[str, Any]:
    """Hash the measured package source and report the local revision when available.

    Returns:
        A mapping containing the source identity data.
    """
    package_root = Path(aselenium.__file__).resolve().parent
    digest = hashlib.sha256()
    paths = sorted(
        path for path in package_root.rglob("*") if path.suffix in {".py", ".json"}
    )
    for path in paths:
        digest.update(path.relative_to(package_root).as_posix().encode() + b"\0")
        digest.update(path.read_bytes() + b"\0")
    repository = Path(__file__).resolve().parents[1]
    revision = None
    if shutil.which("git"):
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repository,
            text=True,
            capture_output=True,
            timeout=5,
            check=False,
        )
        if result.returncode == 0:
            revision = result.stdout.strip()
    return {
        "repository_head": revision,
        "package_source_sha256": digest.hexdigest(),
        "package_source_file_count": len(paths),
        "digest_definition": "Sorted package-relative POSIX paths and contents of .py/.json files, each NUL-terminated; includes uncommitted source.",
        "benchmark_script_sha256": hashlib.sha256(
            Path(__file__).read_bytes()
        ).hexdigest(),
    }


def main() -> None:
    """Parse command-line arguments and run the requested program workflow."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=positive_int, default=7)
    parser.add_argument("--lookup-iterations", type=positive_int, default=100)
    parser.add_argument(
        "--cache-entries", nargs="+", type=positive_int, default=[10, 100, 1000]
    )
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="aselenium-benchmark-") as directory:
        root = Path(directory)
        imports = import_samples(args.samples, root)
        caches = [
            cache_samples(root, size, args.samples, args.lookup_iterations)
            for size in dict.fromkeys(args.cache_entries)
        ]
    report = {
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "python": sys.version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "source": source_identity(),
        "dependencies": dict(
            sorted(
                (dist.metadata["Name"], dist.version)
                for dist in metadata.distributions()
            )
        ),
        "parameters": vars(args),
        "scope": "Fresh interpreter package import; OS disk caches not flushed. Synthetic SQLite cache lookup/open, including executable checksum verification; no browser, network or install timing.",
        "import_ms": summarize([item["milliseconds"] for item in imports]),
        "post_import_rss_bytes": summarize([item["rss_bytes"] for item in imports]),
        "caches": caches,
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
