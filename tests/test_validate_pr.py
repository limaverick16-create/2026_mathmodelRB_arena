import json
import subprocess

import pytest

import scripts.validate_pr as validate_pr
from arena_core import GameMode
from arena_leaderboard.schema_v2 import (
    SubmissionError,
    account_hash,
    build_encrypted_submission,
    prepare_submission,
)
from arena_server.sessions import SessionStore


def complete_session(tmp_path):
    managed = SessionStore(tmp_path / "sessions").create(
        mode=GameMode.OMNIDIRECTIONAL, seed=31
    )
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


def git(repo, *arguments):
    return subprocess.run(
        ["git", "-C", str(repo), *arguments],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_changed_submission_only_accepts_one_new_json(tmp_path):
    repo = tmp_path / "candidate"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    git(repo, "add", "README.md")
    git(repo, "commit", "-m", "base")
    base = git(repo, "rev-parse", "HEAD")
    path = repo / "submissions" / ("a" * 64) / ("b" * 20 + ".json")
    path.parent.mkdir(parents=True)
    path.write_text("{}", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "score")
    head = git(repo, "rev-parse", "HEAD")

    relative, selected = validate_pr.changed_submission(repo, base, head)
    assert relative == path.relative_to(repo).as_posix()
    assert selected == path

    (repo / "README.md").write_text("changed\n", encoding="utf-8")
    git(repo, "add", "README.md")
    git(repo, "commit", "-m", "extra")
    with pytest.raises(SubmissionError, match="exactly one"):
        validate_pr.changed_submission(repo, base, git(repo, "rev-parse", "HEAD"))


def test_validate_candidate_replays_decrypted_payload(tmp_path, monkeypatch):
    prepared = prepare_submission(
        complete_session(tmp_path), login="Alice", nickname="Player"
    )
    submission = encrypted_stub(prepared["summary"])
    relative = (
        f"submissions/{account_hash('alice')}/{submission['submission_id']}.json"
    )
    candidate = tmp_path / "candidate"
    path = candidate / relative
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(submission), encoding="utf-8")
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"encryption_key_id": "arena-test-01"}), encoding="utf-8"
    )
    monkeypatch.setattr(
        validate_pr,
        "changed_submission",
        lambda candidate, base, head: (relative, path),
    )

    def decrypt(_path, output):
        output.write_text(json.dumps(prepared["replay"]), encoding="utf-8")

    monkeypatch.setattr(validate_pr, "decrypt_replay", decrypt)
    assert validate_pr.validate_candidate(
        candidate=candidate,
        base="base",
        head="head",
        author="ALICE",
        config_path=config,
    ) == submission["submission_id"]


def test_validate_candidate_rejects_duplicate_category(tmp_path, monkeypatch):
    prepared = prepare_submission(
        complete_session(tmp_path), login="alice", nickname="Player"
    )
    submission = encrypted_stub(prepared["summary"])
    directory = account_hash("alice")
    submissions_dir = tmp_path / "submissions" / directory
    submissions_dir.mkdir(parents=True)

    existing = encrypted_stub(prepared["summary"])
    (submissions_dir / "00000000000000000000.json").write_text(
        json.dumps(existing), encoding="utf-8"
    )

    new_path = submissions_dir / f"{submission['submission_id']}.json"
    new_path.write_text(json.dumps(submission), encoding="utf-8")
    relative = f"submissions/{directory}/{submission['submission_id']}.json"

    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"encryption_key_id": "arena-test-01"}), encoding="utf-8"
    )
    monkeypatch.setattr(
        validate_pr,
        "changed_submission",
        lambda candidate, base, head: (relative, new_path),
    )
    monkeypatch.setattr(
        validate_pr,
        "decrypt_replay",
        lambda _path, output: output.write_text(
            json.dumps(prepared["replay"]), encoding="utf-8"
        ),
    )

    with pytest.raises(SubmissionError, match="already has a score"):
        validate_pr.validate_candidate(
            candidate=tmp_path,
            base="base",
            head="head",
            author="alice",
            config_path=config,
        )


def test_validate_candidate_rejects_author_path_mismatch(tmp_path, monkeypatch):
    prepared = prepare_submission(
        complete_session(tmp_path), login="alice", nickname="Player"
    )
    submission = encrypted_stub(prepared["summary"])
    path = tmp_path / "submission.json"
    path.write_text(json.dumps(submission), encoding="utf-8")
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"encryption_key_id": "arena-test-01"}), encoding="utf-8"
    )
    monkeypatch.setattr(
        validate_pr,
        "changed_submission",
        lambda candidate, base, head: (
            f"submissions/{'0' * 64}/{submission['submission_id']}.json",
            path,
        ),
    )
    with pytest.raises(SubmissionError, match="author"):
        validate_pr.validate_candidate(
            candidate=tmp_path,
            base="base",
            head="head",
            author="alice",
            config_path=config,
        )
