"""Offline, bounded import of Harness² demo metrics. Never applies harness edits.

No imports from JESSYCA or Harness²: this boundary remains usable independently.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path

UPSTREAM_COMMIT = "1cfe254e8d25b15f37048c3730134686abe60335"
MAX_REPORT_BYTES = 65536


@dataclass(frozen=True)
class Review:
    upstream_commit: str
    completed: int
    failed: int
    execution_count: int
    editor_calls: int
    status: str = "review_only"
    production_ready: bool = False


def review_demo(payload: bytes, *, enabled: bool = False) -> Review:
    """Explicit opt-in; accept metrics only, discard upstream scripts and lessons.

    Provenance must be checked separately against the pinned checkout; the commit
    in Review identifies the supported schema, not an attestation of the input.
    """
    if enabled is not True:
        raise PermissionError("Harness² lab is disabled; explicit opt-in required")
    if len(payload) > MAX_REPORT_BYTES:
        raise ValueError("Report exceeds 64 KiB")
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object")
    values = []
    for key in ("done", "failed", "execution_count", "editor_calls"):
        value = data.get(key)
        if type(value) is not int or not 0 <= value <= 10000:
            raise ValueError(f"Invalid bounded integer: {key}")
        values.append(value)
    return Review(UPSTREAM_COMMIT, *values)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--enable-lab", action="store_true")
    args = parser.parse_args()
    if not args.enable_lab:
        parser.error("Explicit --enable-lab required")
    with args.report.open("rb") as stream:
        payload = stream.read(MAX_REPORT_BYTES + 1)
    print(json.dumps(asdict(review_demo(payload, enabled=True)), indent=2))


if __name__ == "__main__":
    main()
