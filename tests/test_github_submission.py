import json

import pytest

from arena_leaderboard.schema_v2 import account_hash
from arena_leaderboard.submission import GitHubAPIError
from arena_leaderboard.submission import GitHubPublisher, RepositoryConfig


class FakeAPI:
    def __init__(self):
        self.calls = []

    def request(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        if path == "/user":
            return {"login": "alice"}
        if path == "/repos/alice/arena":
            return {"full_name": "alice/arena"}
        if path.endswith("/git/ref/heads/main"):
            return {"object": {"sha": "abc123"}}
        if path.endswith("/pulls"):
            return {"html_url": "https://github.com/owner/arena/pull/7", "number": 7}
        return {}


def test_publish_creates_branch_file_and_pull_request():
    api = FakeAPI()
    publisher = GitHubPublisher(
        api,
        RepositoryConfig(owner="owner", repo="arena", default_branch="main"),
        id_factory=lambda: "fixed",
    )
    submission = {
        "summary": {"account_hash": account_hash("alice"), "nickname": "Player"},
        "submission_id": "score1",
    }
    result = publisher.publish(submission, login="alice")

    assert result["pull_request_url"].endswith("/pull/7")
    paths = [call[1] for call in api.calls]
    assert "/repos/alice/arena/git/refs" in paths
    destination = f"/repos/alice/arena/contents/submissions/{account_hash('alice')}/score1.json"
    assert destination in paths
    pull = next(call for call in api.calls if call[1].endswith("/pulls"))
    assert pull[2]["head"] == "alice:arena-score-fixed"
    assert json.loads(submission_json(api))["submission_id"] == "score1"


def test_publish_rejects_account_hash_mismatch():
    publisher = GitHubPublisher(
        FakeAPI(), RepositoryConfig(owner="owner", repo="arena", default_branch="main")
    )
    submission = {
        "summary": {"account_hash": account_hash("bob"), "nickname": "Player"},
        "submission_id": "score1",
    }
    with pytest.raises(GitHubAPIError, match="account"):
        publisher.publish(submission, login="alice")


def submission_json(api):
    import base64

    upload = next(call for call in api.calls if "/contents/submissions/" in call[1])
    return base64.b64decode(upload[2]["content"]).decode()
