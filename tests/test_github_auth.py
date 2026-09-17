import pytest

from arena_leaderboard.github_auth import DeviceFlow, GitHubAuthError, TokenStore


class FakeTransport:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def form(self, url, payload):
        self.calls.append((url, payload))
        return next(self.responses)


def test_device_flow_uses_public_repo_scope_and_handles_pending():
    transport = FakeTransport([
        {
            "device_code": "secret-device-code",
            "user_code": "ABCD-EFGH",
            "verification_uri": "https://github.com/login/device",
            "expires_in": 900,
            "interval": 5,
        },
        {"error": "authorization_pending"},
        {"access_token": "token", "scope": "public_repo"},
    ])
    flow = DeviceFlow("client-id", transport=transport)
    public = flow.begin()
    assert public["user_code"] == "ABCD-EFGH"
    assert "device_code" not in public
    assert transport.calls[0][1]["scope"] == "public_repo"
    assert flow.poll() == {"status": "pending", "interval": 5}
    assert flow.poll() == {"status": "authorized", "access_token": "token"}


def test_token_store_uses_restricted_permissions(tmp_path):
    path = tmp_path / "user-config" / "github-token.json"
    store = TokenStore(path)
    store.save("secret")
    assert store.load() == "secret"
    assert path.exists()
    assert path.stat().st_mode & 0o077 == 0
    store.clear()
    assert store.load() is None


def test_device_flow_requires_begin_and_surfaces_denial():
    flow = DeviceFlow("client-id", transport=FakeTransport([]))
    with pytest.raises(GitHubAuthError, match="not started"):
        flow.poll()

    denied = DeviceFlow(
        "client-id",
        transport=FakeTransport([
            {"device_code": "d", "user_code": "U", "verification_uri": "url", "expires_in": 1},
            {"error": "access_denied", "error_description": "user denied"},
        ]),
    )
    denied.begin()
    with pytest.raises(GitHubAuthError, match="user denied"):
        denied.poll()


def test_device_flow_slow_down_increases_poll_interval():
    flow = DeviceFlow(
        "client-id",
        transport=FakeTransport([
            {"device_code": "d", "user_code": "U", "verification_uri": "url", "expires_in": 1, "interval": 2},
            {"error": "slow_down"},
        ]),
    )
    flow.begin()
    assert flow.poll() == {"status": "pending", "interval": 7}
