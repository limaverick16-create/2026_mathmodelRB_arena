"""Build the single static leaderboard page from validated JSON submissions."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any, Iterable

from .schema_v2 import SubmissionError, validate_public_submission


CATEGORIES = (
    ("human_omnidirectional", "人工 · 非定向源"),
    ("human_mixed_directional", "人工 · 有定向源"),
    ("strategy_omnidirectional", "策略 · 非定向源"),
    ("strategy_mixed_directional", "策略 · 有定向源"),
)
HOMEPAGE_LIMIT = 50


def best_records(records: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    best: dict[tuple[str, str], dict[str, Any]] = {}
    for submission in records:
        record = {**submission["summary"], "submission_id": submission["submission_id"]}
        key = (record["category"], record["account_hash"])
        if key not in best or record["seconds_per_source"] < best[key]["seconds_per_source"]:
            best[key] = record
    grouped = {category: [] for category, _ in CATEGORIES}
    for (category, _), record in best.items():
        if category in grouped:
            grouped[category].append(record)
    for rows in grouped.values():
        rows.sort(
            key=lambda item: (
                item["seconds_per_source"],
                item["virtual_time_s"],
                item["nickname"].casefold(),
            )
        )
    return grouped


def leaderboard_data(
    records: Iterable[dict[str, Any]], *, limit: int = HOMEPAGE_LIMIT
) -> dict[str, Any]:
    grouped = best_records(records)
    categories: dict[str, list[dict[str, Any]]] = {}
    fields = (
        "nickname",
        "seconds_per_source",
        "virtual_time_s",
        "source_count",
        "directional_count",
        "omnidirectional_count",
        "public_strategy_name",
    )
    for category, _ in CATEGORIES:
        categories[category] = [
            {
                "rank": rank,
                **{field: item.get(field) for field in fields},
            }
            for rank, item in enumerate(grouped[category][:limit], 1)
        ]
    return {"limit": limit, "categories": categories}


def _row(index: int, item: dict[str, Any]) -> str:
    source_text = f"{item['source_count']} 个源"
    if item["category"].endswith("mixed_directional"):
        source_text += f" · {item['directional_count']} 定向 / {item['omnidirectional_count']} 非定向"
    strategy = html.escape(str(item.get("public_strategy_name") or "—"))
    return (
        f"<tr><td>{index}</td><td>{html.escape(item['nickname'])}</td>"
        f"<td>{item['seconds_per_source']:.3f} 秒/源</td>"
        f"<td>{item['virtual_time_s']:.1f} 秒</td><td>{source_text}</td><td>{strategy}</td></tr>"
    )


def render_leaderboard(records: Iterable[dict[str, Any]]) -> str:
    grouped = best_records(records)
    tabs, panels = [], []
    for index, (category, label) in enumerate(CATEGORIES):
        selected = "true" if index == 0 else "false"
        hidden = "" if index == 0 else " hidden"
        tabs.append(f'<button role="tab" aria-selected="{selected}" data-panel="{category}">{label}</button>')
        rows = "".join(_row(rank, item) for rank, item in enumerate(grouped[category], 1))
        if not rows:
            rows = '<tr><td colspan="6">暂无成绩</td></tr>'
        panels.append(
            f'<section id="{category}" role="tabpanel"{hidden}><table><thead><tr>'
            "<th>#</th><th>昵称</th><th>成绩</th><th>虚拟用时</th><th>随机地图</th><th>策略</th>"
            f"</tr></thead><tbody>{rows}</tbody></table></section>"
        )
    return """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Arena 排行榜</title><style>body{font:16px system-ui;margin:0;background:#f4f6f8;color:#172033}main{max-width:1100px;margin:auto;padding:32px}nav{display:flex;gap:8px;flex-wrap:wrap;margin:24px 0}button{padding:10px 14px;border:1px solid #aeb8c6;border-radius:8px;background:white}button[aria-selected=true]{background:#172033;color:white}table{border-collapse:collapse;width:100%;background:white}th,td{padding:12px;border-bottom:1px solid #e1e5eb;text-align:left}</style></head><body><main><h1>排行榜</h1><p>随机地图；按虚拟秒/源从小到大排序。每个账号每类只保留最佳成绩。</p><nav>""" + "".join(tabs) + "</nav>" + "".join(panels) + """</main><script>document.querySelectorAll('[role=tab]').forEach(b=>b.onclick=()=>{document.querySelectorAll('[role=tab]').forEach(x=>x.setAttribute('aria-selected',x===b));document.querySelectorAll('[role=tabpanel]').forEach(x=>x.hidden=x.id!==b.dataset.panel)})</script></body></html>"""


def load_submissions(root: Path) -> list[dict[str, Any]]:
    records = []
    for path in sorted(Path(root).rglob("*.json")):
        try:
            records.append(
                validate_public_submission(json.loads(path.read_text(encoding="utf-8")))
            )
        except (json.JSONDecodeError, SubmissionError) as error:
            raise SubmissionError(f"{path}: {error}") from error
    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--submissions", type=Path, default=Path("submissions"))
    parser.add_argument("--output", type=Path, default=Path("leaderboard/index.html"))
    args = parser.parse_args(argv)
    records = load_submissions(args.submissions)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_leaderboard(records), encoding="utf-8")
    data_path = args.output.with_name("leaderboard.json")
    data_path.write_text(
        json.dumps(leaderboard_data(records), ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
