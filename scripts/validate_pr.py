"""Validate one encrypted score PR using only trusted base-branch code."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

TRUSTED_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TRUSTED_ROOT))

from arena_leaderboard.schema_v2 import (  # noqa: E402
    SubmissionError,
    account_hash,
    validate_decrypted_submission,
    validate_public_submission,
)


def changed_submission(candidate: Path, base: str, head: str) -> tuple[str, Path]:
    output = subprocess.run(
        [
            "git",
            "-C",
            str(candidate),
            "diff",
            "--name-status",
            "--no-renames",
            base,
            head,
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    if len(output) != 1:
        raise SubmissionError("score PR must add exactly one submission file")
    parts = output[0].split("\t")
    if len(parts) != 2 or parts[0] != "A":
        raise SubmissionError("score PR must only add a new submission file")
    relative = parts[1]
    if not relative.startswith("submissions/") or not relative.endswith(".json"):
        raise SubmissionError("score PR must add one submissions/**/*.json file")
    root = candidate.resolve()
    path = candidate / relative
    if path.is_symlink() or not path.is_file() or root not in path.resolve().parents:
        raise SubmissionError("invalid submission path")
    if path.stat().st_size > 2_000_000:
        raise SubmissionError("submission file is too large")
    return relative, path


def decrypt_replay(path: Path, output: Path) -> None:
    if not os.environ.get("LEADERBOARD_PRIVATE_KEY_PEM"):
        raise SubmissionError("leaderboard verifier is not configured")
    subprocess.run(
        [
            "node",
            str(TRUSTED_ROOT / "scripts" / "decrypt_submission.mjs"),
            "--submission",
            str(path),
            "--output",
            str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )


def validate_candidate(
    *, candidate: Path, base: str, head: str, author: str, config_path: Path
) -> str:
    relative, path = changed_submission(candidate, base, head)
    submission = validate_public_submission(json.loads(path.read_text(encoding="utf-8")))
    config = json.loads(config_path.read_text(encoding="utf-8"))
    expected_key_id = config.get("encryption_key_id")
    if not isinstance(expected_key_id, str) or not expected_key_id:
        raise SubmissionError("leaderboard verifier has no active key")
    expected_directory = account_hash(author)
    if relative != f"submissions/{expected_directory}/{submission['submission_id']}.json":
        raise SubmissionError("submission path does not match its author and id")
    with tempfile.TemporaryDirectory(prefix="arena-verify-") as temporary:
        replay_path = Path(temporary) / "replay.json"
        try:
            decrypt_replay(path, replay_path)
            replay = json.loads(replay_path.read_text(encoding="utf-8"))
            validate_decrypted_submission(
                submission,
                replay,
                author=author,
                expected_key_id=expected_key_id,
            )
        finally:
            if replay_path.exists():
                replay_path.unlink()
    return submission["submission_id"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--author", required=True)
    parser.add_argument(
        "--config", type=Path, default=TRUSTED_ROOT / "leaderboard" / "config.json"
    )
    args = parser.parse_args()
    try:
        submission_id = validate_candidate(
            candidate=args.candidate,
            base=args.base,
            head=args.head,
            author=args.author,
            config_path=args.config,
        )
    except Exception as error:
        print(f"encrypted leaderboard submission validation failed: {error}", file=sys.stderr)
        return 1
    print(f"valid encrypted submission {submission_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
