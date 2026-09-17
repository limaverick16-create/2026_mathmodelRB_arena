import json

import arena_leaderboard.build as build_module
from arena_leaderboard.build import best_records, leaderboard_data, render_leaderboard
from arena_leaderboard.schema_v2 import account_hash


def record(entrant, category, score, *, sources=10, directional=0):
    return {
        "summary": {
            "nickname": entrant,
            "account_hash": account_hash(entrant),
            "category": category,
            "seconds_per_source": score,
            "virtual_time_s": score * sources,
            "source_count": sources,
            "directional_count": directional,
            "omnidirectional_count": sources - directional,
            "public_strategy_name": None,
        },
        "submission_id": f"{entrant}-{category}-{score}",
    }


def test_best_record_per_user_per_category_is_kept():
    records = [
        record("alice", "human_omnidirectional", 20),
        record("alice", "human_omnidirectional", 10),
        record("alice", "strategy_omnidirectional", 5),
        record("bob", "human_omnidirectional", 15),
    ]
    best = best_records(records)
    assert [item["seconds_per_source"] for item in best["human_omnidirectional"]] == [10, 15]
    assert best["strategy_omnidirectional"][0]["seconds_per_source"] == 5


def test_rendered_page_is_one_leaderboard_with_four_tabs_and_source_counts():
    html = render_leaderboard([
        record("alice", "human_mixed_directional", 9, sources=12, directional=5)
    ])
    assert "排行榜" in html
    assert "娱乐榜" not in html
    assert html.count('role="tab"') == 4
    assert "12 个源" in html
    assert "5 定向 / 7 非定向" in html


def test_homepage_data_contains_at_most_top_fifty_per_category():
    records = [
        record(f"player-{index:02d}", "strategy_omnidirectional", index + 1)
        for index in range(55)
    ]
    records[0]["summary"]["public_strategy_name"] = "fast_solver"

    data = leaderboard_data(records)
    rows = data["categories"]["strategy_omnidirectional"]

    assert len(rows) == 50
    assert rows[0] == {
        "rank": 1,
        "nickname": "player-00",
        "seconds_per_source": 1,
        "virtual_time_s": 10,
        "source_count": 10,
        "directional_count": 0,
        "omnidirectional_count": 10,
        "public_strategy_name": "fast_solver",
    }
    assert rows[-1]["rank"] == 50


def test_build_writes_homepage_json_next_to_full_page(tmp_path, monkeypatch):
    records = [record("alice", "human_omnidirectional", 8)]
    monkeypatch.setattr(build_module, "load_submissions", lambda root: records)
    output = tmp_path / "generated" / "index.html"

    assert build_module.main(["--submissions", str(tmp_path), "--output", str(output)]) == 0

    data = json.loads(output.with_name("leaderboard.json").read_text(encoding="utf-8"))
    assert output.exists()
    assert data["limit"] == 50
    assert data["categories"]["human_omnidirectional"][0]["nickname"] == "alice"
