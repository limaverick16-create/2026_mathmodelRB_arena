import json

import pytest

import arena_server.leaderboard as leaderboard_module
from arena_core import GameMode
from arena_leaderboard.github_auth import TokenStore
from arena_leaderboard.schema_v2 import (
    SubmissionError,
    build_encrypted_submission,
)
from arena_leaderboard.submission import GitHubAPIError
from arena_server.leaderboard import LeaderboardService
from arena_server.sessions import SessionStore


PUBLIC_JWK = {"kty": "RSA", "n": "test-modulus", "e": "AQAB", "alg": "RSA-OAEP-256"}


def complete_session(tmp_path):
    managed = SessionStore(tmp_path / "sessions").create(
        mode=GameMode.OMNIDIRECTIONAL, seed=9
    )
    for source in managed.game.sources.values():
        managed.apply_action({"type": "move", "x": source.x, "y": source.y})
        managed.apply_action({"type": "clear", "channel": source.channel})
    return managed


def configured_service(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "owner": "owner",
                "repo": "arena",
                "default_branch": "main",
                "oauth_client_id": "client-id",
                "encryption_key_id": "arena-test-01",
                "encryption_public_key_jwk": PUBLIC_JWK,
            }
        ),
        encoding="utf-8",
    )
    return LeaderboardService(
        config_path=config_path,
        exports_root=tmp_path / "exports",
        token_store=TokenStore(tmp_path / "github-token.json"),
    )


class UserAPI:
    def __init__(self, token):
        assert token == "valid-token"

    def request(self, method, path, payload=None):
        if path == "/user":
            return {"login": "alice"}
        return {}


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


def test_prepare_requires_login_without_exporting_plaintext(tmp_path):
    service = configured_service(tmp_path)
    assert service.prepare(complete_session(tmp_path), nickname="Player") == {
        "status": "needs_auth"
    }
    assert not (tmp_path / "exports").exists()


def test_prepare_uses_server_actor_and_never_exposes_local_strategy_name(
    tmp_path, monkeypatch
):
    service = configured_service(tmp_path)
    service.token_store.save("valid-token")
    monkeypatch.setattr(leaderboard_module, "GitHubAPI", UserAPI)
    managed = complete_session(tmp_path)
    managed.actor = "strategy"
    managed.strategy_name = "local_example_strategy"

    result = service.prepare(
        managed, nickname="Player", public_strategy_name="公开名称"
    )

    assert result["status"] == "ready"
    assert result["key_id"] == "arena-test-01"
    assert result["public_key_jwk"] == PUBLIC_JWK
    assert result["summary"]["category"] == "strategy_omnidirectional"
    assert result["summary"]["public_strategy_name"] == "公开名称"
    assert "local_example_strategy" not in json.dumps(result, ensure_ascii=False)
    assert result["replay"]["actions"]
    assert not (tmp_path / "exports").exists()


def test_assisted_session_cannot_prepare(tmp_path, monkeypatch):
    service = configured_service(tmp_path)
    service.token_store.save("valid-token")
    monkeypatch.setattr(leaderboard_module, "GitHubAPI", UserAPI)
    managed = complete_session(tmp_path)
    managed.game.assisted = True
    with pytest.raises(SubmissionError, match="assisted"):
        service.prepare(managed, nickname="Player")


def test_submit_clears_rejected_token_and_requests_new_authorization(
    tmp_path, monkeypatch
):
    service = configured_service(tmp_path)
    service.token_store.save("expired-token")

    class UnauthorizedAPI:
        def __init__(self, token):
            assert token == "expired-token"

        def request(self, method, path, payload=None):
            raise GitHubAPIError("Bad credentials", status=401)

    monkeypatch.setattr(leaderboard_module, "GitHubAPI", UnauthorizedAPI)

    assert service.submit(complete_session(tmp_path), {}) == {"status": "needs_auth"}
    assert service.token_store.load() is None


def test_submit_checks_envelope_against_session_before_publishing(tmp_path, monkeypatch):
    service = configured_service(tmp_path)
    service.token_store.save("valid-token")
    monkeypatch.setattr(leaderboard_module, "GitHubAPI", UserAPI)
    managed = complete_session(tmp_path)
    prepared = service.prepare(managed, nickname="Player")
    submission = encrypted_stub(prepared["summary"])
    published = []

    class Publisher:
        def __init__(self, api, config):
            pass

        def publish(self, payload, *, login):
            published.append((payload, login))
            return {"status": "submitted", "pull_request_url": "https://example/pr/1"}

    monkeypatch.setattr(leaderboard_module, "GitHubPublisher", Publisher)

    result = service.submit(managed, submission)
    assert result["status"] == "submitted"
    assert published == [(submission, "alice")]
    stored = list((tmp_path / "exports").glob("*.json"))
    assert len(stored) == 1
    assert "replay" not in json.loads(stored[0].read_text(encoding="utf-8"))

    changed = json.loads(json.dumps(submission))
    changed["summary"]["virtual_time_s"] = 1.0
    changed["summary"]["seconds_per_source"] = 1.0 / changed["summary"]["source_count"]
    changed = encrypted_stub(changed["summary"])
    with pytest.raises(SubmissionError, match="session"):
        service.submit(managed, changed)


def test_poll_auth_validates_token_before_saving(tmp_path, monkeypatch):
    service = configured_service(tmp_path)

    class AuthorizedFlow:
        def poll(self):
            return {"status": "authorized", "access_token": "rejected-token"}

    class UnauthorizedAPI:
        def __init__(self, token):
            assert token == "rejected-token"

        def request(self, method, path, payload=None):
            raise GitHubAPIError("Bad credentials", status=401)

    service.device_flow = AuthorizedFlow()
    monkeypatch.setattr(leaderboard_module, "GitHubAPI", UnauthorizedAPI)

    with pytest.raises(GitHubAPIError, match="Bad credentials"):
        service.poll_auth()
    assert service.token_store.load() is None
