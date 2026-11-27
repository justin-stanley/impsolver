# SPDX-FileCopyrightText: 2026 Justin Stanley
# SPDX-License-Identifier: MIT
"""Check Voteview downloads against data/voteview.sha256 and rebuild the derived files.

Usage: python scripts/reproduce.py   (after scripts/fetch-voteview.sh 116 119)

Exit status 0 means the downloads match the pinned checksums, the rebuilt roster is
byte-identical and the rebuilt alignment files match the committed copies to 1e-6. Voteview
updates its files as new votes are recorded, so a mismatch usually means newer data, not an
error; the report says which.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

from impsolver.alignment import main as align_main
from impsolver.roster import main as roster_main

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "voteview"
MANIFEST = ROOT / "data" / "voteview.sha256"
ACCESSED = "2026-11-27"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check_manifest() -> list[str]:
    problems = []
    for line in MANIFEST.read_text().splitlines():
        if not line.strip():
            continue
        digest, name = line.split()
        path = DATA / name
        if not path.exists():
            problems.append(f"missing {name}; run scripts/fetch-voteview.sh 116 119")
        elif sha256(path) != digest:
            problems.append(f"{name} differs from the pinned checksum (Voteview has newer data)")
    return problems


def rebuild(out: Path) -> None:
    v = DATA
    roster_main([
        "--members", str(v / "H119_members.csv"), "--members", str(v / "S119_members.csv"),
        "--votes", str(v / "H119_votes.csv"), "--votes", str(v / "S119_votes.csv"),
        "--caucus", "328=D", "--member-caucus", "K000401=R", "--vacate", "H001082",
        "--as-of", ACCESSED, "--accessed", ACCESSED, "--out", str(out / "us-119.yaml"),
    ])  # fmt: skip
    for congress, extra in (("116", []), ("119", ["--member-caucus", "K000401=R"])):
        align_main([
            "--votes", str(v / f"H{congress}_votes.csv"),
            "--votes", str(v / f"S{congress}_votes.csv"),
            "--members", str(v / f"H{congress}_members.csv"),
            "--members", str(v / f"S{congress}_members.csv"),
            "--caucus", "328=D", *extra, "--accessed", ACCESSED,
            "--out", str(out / f"us-{congress}.json"),
        ])  # fmt: skip


def close(a: object, b: object, tol: float = 1e-6) -> bool:
    """Structural equality with a tolerance on floats (linear algebra differs slightly by BLAS)."""
    if isinstance(a, float) or isinstance(b, float):
        return isinstance(a, int | float) and isinstance(b, int | float) and abs(a - b) <= tol
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(close(a[k], b[k], tol) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(close(x, y, tol) for x, y in zip(a, b, strict=True))
    return a == b


def same(built: Path, committed: Path) -> bool:
    if built.suffix == ".json":
        return close(json.loads(built.read_text()), json.loads(committed.read_text()))
    return built.read_bytes() == committed.read_bytes()


def main() -> int:
    problems = check_manifest()
    if any(p.startswith("missing") for p in problems):
        print("\n".join(problems))
        return 2
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        rebuild(out)
        pairs = [
            (out / "us-119.yaml", ROOT / "compositions" / "us-119.yaml"),
            (out / "us-116.json", ROOT / "alignment" / "us-116.json"),
            (out / "us-119.json", ROOT / "alignment" / "us-119.json"),
        ]
        for built, committed in pairs:
            if not same(built, committed):
                rel = committed.relative_to(ROOT)
                problems.append(f"rebuilt {rel} differs from the committed copy")
    if problems:
        print("Reproduce found differences:")
        print("\n".join(f"- {p}" for p in problems))
        return 1
    print("Voteview files match the pinned checksums; derived files rebuild identically.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
