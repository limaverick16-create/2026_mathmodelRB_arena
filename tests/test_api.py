import json
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from arena_server.http import create_server
from arena_server.leaderboard import LeaderboardService
from arena_server.sessions import SessionStore


@pytest.fixture
def api(tmp_path):
    strategies = tmp_path / "strategies"
    strategies.mkdir()
    (strategies / "demo.py").write_text(
        "class Strategy:\n"
        "    def reset(self, game_info): pass\n"
        "    def next_action(self, observation):\n"
        "        return {'type': 'move', 'x': 15, 'y': 0}\n",
        encoding="utf-8",
    )
    store = SessionStore(tmp_path / "sessions")
    leaderboard = LeaderboardService(
        config_path=tmp_path / "missing.json", exports_root=tmp_path / "exports"
    )
    server = create_server(
        ("127.0.0.1", 0),
        store=store,
        strategies_root=strategies,
        leaderboard_service=leaderboard,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        yield base
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def request_json(base, path, method="GET", payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    request = Request(
        base + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=2) as response:
        return response.status, json.loads(response.read())


def test_create_read_and_act_without_page_reload(api):
    status, created = request_json(
        api,
        "/api/sessions",
        "POST",
        {"mode": "omnidirectional", "seed": 10, "source_count": 10},
    )
    session_id = created["session_id"]
    assert status == 201
    assert created["source_count"] is None

    status, moved = request_json(
        api,
        f"/api/sessions/{session_id}/actions",
        "POST",
        {"action": {"type": "move", "x": 30, "y": 40}, "command_id": "one"},
    )
    assert status == 200
    assert moved["position"] == [30.0, 40.0]
    assert moved["virtual_time_s"] == 10.0

    _, read_back = request_json(api, f"/api/sessions/{session_id}")
    assert read_back["position"] == [30.0, 40.0]


def test_public_api_always_uses_random_source_count(api):
    _, created = request_json(
        api,
        "/api/sessions",
        "POST",
        {"mode": "showcase", "seed": 10, "source_count": 1},
    )

    assert 10 <= created["source_count"] <= 16


def test_bad_action_returns_json_error_without_changing_state(api):
    _, created = request_json(
        api,
        "/api/sessions",
        "POST",
        {"mode": "omnidirectional", "seed": 10, "source_count": 10},
    )
    session_id = created["session_id"]
    with pytest.raises(HTTPError) as error:
        request_json(
            api,
            f"/api/sessions/{session_id}/actions",
            "POST",
            {"action": {"type": "measure", "channel": 99}},
        )
    assert error.value.code == 400

    _, state = request_json(api, f"/api/sessions/{session_id}")
    assert state["virtual_time_s"] == 0


def test_static_home_page_is_served(api):
    with urlopen(api + "/", timeout=2) as response:
        body = response.read().decode()
    assert "B题机器狗竞技场" in body
    assert "策略实验室" in body
    assert "人工排行榜" in body
    assert "策略排行榜" in body
    with urlopen(api + "/leaderboard-crypto.mjs", timeout=2) as response:
        assert "encryptSubmission" in response.read().decode()


def test_strategy_can_be_listed_started_and_stepped(api):
    _, listed = request_json(api, "/api/strategies")
    assert listed == {"strategies": [{"name": "demo", "file": "demo.py"}]}

    _, created = request_json(
        api,
        "/api/sessions",
        "POST",
        {"mode": "omnidirectional", "seed": 7, "source_count": 10},
    )
    session_id = created["session_id"]
    _, started = request_json(
        api,
        f"/api/sessions/{session_id}/strategy/start",
        "POST",
        {"name": "demo"},
    )
    assert started["strategy"] == {"name": "demo", "running": True}

    _, stepped = request_json(
        api, f"/api/sessions/{session_id}/strategy/step", "POST", {}
    )
    assert stepped["state"]["position"] == [15.0, 0.0]
    assert stepped["action"]["type"] == "move"


def test_session_replay_can_be_exported_and_verified(api):
    _, created = request_json(
        api,
        "/api/sessions",
        "POST",
        {"mode": "omnidirectional", "seed": 10},
    )
    _, replay = request_json(api, f"/api/sessions/{created['session_id']}/export")
    assert len(replay["payload_sha256"]) == 64
    assert "sources" not in replay


def test_leaderboard_status_and_unconfigured_prepare_error(api):
    _, status = request_json(api, "/api/leaderboard")
    assert status["configured"] is False
    _, created = request_json(
        api,
        "/api/sessions",
        "POST",
        {"mode": "omnidirectional", "seed": 10, "source_count": 10},
    )
    with pytest.raises(HTTPError) as error:
        request_json(
            api,
            f"/api/sessions/{created['session_id']}/leaderboard/prepare",
            "POST",
            {"nickname": "Player"},
        )
    assert error.value.code == 400
