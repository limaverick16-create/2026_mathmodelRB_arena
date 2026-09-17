import json

import pytest

from arena_core import GameMode
from arena_leaderboard import build as leaderboard_build
from arena_leaderboard.schema_v2 import (
    SubmissionError,
    build_encrypted_submission,
    prepare_submission,
)
from arena_leaderboard.validate_path import validate_directory
from arena_sdk import Action, GameInfo, Observation
from arena_server.app import build_parser
from arena_server.sessions import SessionStore


def submission(tmp_path):
    managed = SessionStore(tmp_path / "sessions").create(
        mode=GameMode.OMNIDIRECTIONAL, seed=15
    )
    for source in managed.game.sources.values():
        managed.apply_action({"type": "move", "x": source.x, "y": source.y})
        managed.apply_action({"type": "clear", "channel": source.channel})
    prepared = prepare_submission(managed, login="alice", nickname="Alice")
    return build_encrypted_submission(
        prepared["summary"],
        key_id="arena-test-01",
        encrypted_replay={
            "algorithm": "RSA-OAEP-3072+A256GCM",
            "wrapped_key": "A" * 512,
            "iv": "A" * 16,
            "ciphertext": "A" * 24,
        },
    )


def test_validate_directory_and_build_cli(tmp_path):
    root = tmp_path / "submissions"
    root.mkdir()
    (root / "one.json").write_text(json.dumps(submission(tmp_path)), encoding="utf-8")
    assert validate_directory(root) == 1

    output = tmp_path / "site" / "index.html"
    assert leaderboard_build.main(["--submissions", str(root), "--output", str(output)]) == 0
    assert "Alice" in output.read_text(encoding="utf-8")


def test_validate_directory_identifies_bad_file(tmp_path):
    root = tmp_path / "submissions"
    root.mkdir()
    (root / "bad.json").write_text("{}", encoding="utf-8")
    with pytest.raises(SubmissionError, match="bad.json"):
        validate_directory(root)


def test_runtime_parser_and_sdk_types_are_importable():
    args = build_parser().parse_args(["--host", "localhost", "--port", "8123", "--no-browser"])
    assert (args.host, args.port, args.no_browser) == ("localhost", 8123, True)
    assert Action.__name__ == "Action"
    assert GameInfo.__name__ == "GameInfo"
    assert Observation is dict or str(Observation).startswith("dict")
