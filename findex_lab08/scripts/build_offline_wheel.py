"""Fallback PEP 427 wheel builder when hatchling/uv cannot be downloaded.

The supported release build is still `uv build`. This is a standalone, offline,
pure-Python wheel for local installation and does NOT resolve uv.lock.
"""
from __future__ import annotations

import base64
import csv
import hashlib
import io
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
VERSION = "0.4.0"
DIST_INFO = f"findex-{VERSION}.dist-info"
WHEEL = DIST / f"findex-{VERSION}-py3-none-any.whl"


def main() -> None:
    DIST.mkdir(exist_ok=True)
    written: list[tuple[str, str, int]] = []
    with zipfile.ZipFile(WHEEL, "w", zipfile.ZIP_DEFLATED) as archive:
        def add(name: str, content: bytes) -> None:
            archive.writestr(name, content)
            digest = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b"=").decode("ascii")
            written.append((name, f"sha256={digest}", len(content)))

        for path in sorted((ROOT / "src" / "findex").glob("*.py")):
            add(f"findex/{path.name}", path.read_bytes())
        add(f"{DIST_INFO}/METADATA", (
            "Metadata-Version: 2.1\nName: findex\nVersion: 0.4.0\n"
            "Summary: Streaming inverted-index search engine\nRequires-Python: >=3.12\n"
            "Requires-Dist: typer>=0.12\nRequires-Dist: rich>=13.7\n"
        ).encode())
        add(f"{DIST_INFO}/WHEEL", b"Wheel-Version: 1.0\nGenerator: build_offline_wheel.py\nRoot-Is-Purelib: true\nTag: py3-none-any\n")
        add(f"{DIST_INFO}/entry_points.txt", b"[console_scripts]\nfindex = findex.cli:app\n")
        rows = io.StringIO()
        writer = csv.writer(rows, lineterminator="\n")
        for entry in written:
            writer.writerow(entry)
        writer.writerow((f"{DIST_INFO}/RECORD", "", ""))
        archive.writestr(f"{DIST_INFO}/RECORD", rows.getvalue().encode())
    print(f"Built offline wheel: {WHEEL}")


if __name__ == "__main__":
    main()
