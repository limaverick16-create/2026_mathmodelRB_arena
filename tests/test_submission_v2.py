import json

import pytest

from arena_core import GameMode
from arena_leaderboard.schema_v2 import (
    SubmissionError,
    account_hash,
    build_encrypted_submission,
    canonical_json,
    prepare_submission,
    validate_decrypted_submission,
    validate_public_submission,
    write_submission,
)
from arena_server.sessions import SessionStore


def complete_session(tmp_path, mode=GameMode.OMNIDIRECTIONAL):
    managed = SessionStore(tmp_path / "sessions").create(mode=mode, seed=21)
    for source in managed.game.sources.values():
        managed.apply_action({"type": "move", "x": source.x, "y": source.y})
        managed.apply_action({"type": "clear", "channel": source.channel})
    return managed


def encrypted_stub(summary):
    return build_encrypted_submission(
        summary,
        key_id="arena-test-01",
        encrypted_replay={
            "algorithm": "RSA-OAEP-3072+A256GCM",
            "wrapped_key": "A" * 512,
            "iv": "A" * 16,
            "ciphertext": "A" * 24,
        },
    )


def test_canonical_json_matches_browser_test_vector():
    assert canonical_json(
        {"z": 1, "nested": {"b": "中文", "a": 2}, "a": [3, {"y": 1, "x": 2}]}
    ) == '{"a":[3,{"x":2,"y":1}],"nested":{"a":2,"b":"中文"},"z":1}'


def test_prepared_submission_separates_private_replay_from_public_summary(tmp_path):
    managed = complete_session(tmp_path)
    managed.actor = "strategy"
    managed.strategy_name = "local_example_strategy"

    prepared = prepare_submission(
        managed,
        login="Alice",
        nickname="小明",
        public_strategy_name="匿名策略",
    )

    assert prepared["summary"]["nickname"] == "小明"
    assert prepared["summary"]["account_hash"] == account_hash("alice")
    assert prepared["summary"]["public_strategy_name"] == "匿名策略"
    assert "replay" not in prepared["summary"]
    assert "seed" not in prepared["summary"]
    assert "actions" not in prepared["summary"]
    assert "strategy_name" not in prepared["summary"]
    assert "local_example_strategy" not in json.dumps(prepared["summary"], ensure_ascii=False)
    assert prepared["replay"]["actions"]


def test_public_submission_rejects_plaintext_and_unknown_fields(tmp_path):
    prepared = prepare_submission(
        complete_session(tmp_path), login="alice", nickname="Player"
    )
    submission = encrypted_stub(prepared["summary"])
    assert validate_public_submission(submission) == submission

    for forbidden in ("replay", "seed", "actions", "email", "strategy_name"):
        changed = dict(submission)
        changed[forbidden] = "private"
        with pytest.raises(SubmissionError, match="unexpected submission fields"):
            validate_public_submission(changed)


def test_nickname_and_public_strategy_name_are_validated(tmp_path):
    managed = complete_session(tmp_path)
    with pytest.raises(SubmissionError, match="nickname"):
        prepare_submission(managed, login="alice", nickname="")
    with pytest.raises(SubmissionError, match="nickname"):
        prepare_submission(managed, login="alice", nickname="x" * 25)

    managed.actor = "strategy"
    with pytest.raises(SubmissionError, match="public strategy name"):
        prepare_submission(
            managed, login="alice", nickname="Player", public_strategy_name="\n"
        )


def test_trusted_validation_replays_ciphertext_plaintext_and_checks_author(tmp_path):
    prepared = prepare_submission(
        complete_session(tmp_path), login="Alice", nickname="Player"
    )
    submission = encrypted_stub(prepared["summary"])

    assert validate_decrypted_submission(
        submission, prepared["replay"], author="ALICE", expected_key_id="arena-test-01"
    )["summary"]["nickname"] == "Player"

    changed = json.loads(json.dumps(submission))
    changed["summary"]["virtual_time_s"] = 1.0
    changed["summary"]["seconds_per_source"] = 1.0 / changed["summary"]["source_count"]
    changed = build_encrypted_submission(
        changed["summary"],
        key_id=changed["key_id"],
        encrypted_replay=changed["encrypted_replay"],
    )
    with pytest.raises(SubmissionError, match="mismatch"):
        validate_decrypted_submission(changed, prepared["replay"], author="alice")

    with pytest.raises(SubmissionError, match="author"):
        validate_decrypted_submission(submission, prepared["replay"], author="bob")


def test_only_encrypted_submission_is_written(tmp_path):
    prepared = prepare_submission(
        complete_session(tmp_path), login="alice", nickname="Player"
    )
    submission = encrypted_stub(prepared["summary"])
    path = write_submission(submission, tmp_path / "out")
    public = json.loads(path.read_text(encoding="utf-8"))

    assert path.name == f"{submission['submission_id']}.json"
    assert "encrypted_replay" in public
    assert "replay" not in public
    assert "seed" not in path.read_text(encoding="utf-8")
