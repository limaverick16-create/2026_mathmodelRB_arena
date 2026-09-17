"""CLI used by CI to validate every submitted replay without executing user code."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .schema_v2 import SubmissionError, validate_public_submission


def validate_directory(root: Path) -> int:
    count = 0
    for path in sorted(Path(root).rglob("*.json")):
        try:
            validate_public_submission(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, SubmissionError) as error:
            raise SubmissionError(f"{path}: {error}") from error
        count += 1
    return count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path, nargs="?", default=Path("submissions"))
    args = parser.parse_args(argv)
    count = validate_directory(args.root)
    print(f"validated {count} submission(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
