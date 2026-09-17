"""Privacy-preserving leaderboard submission schema."""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from pathlib import Path
from typing import Any

from arena_core import ENGINE_VERSION, GameMode, GameSession
from arena_core.replay import ReplayError, build_replay, verify_replay


class SubmissionError(ValueError):
    """Raised when a run or encrypted submission is not leaderboard eligible."""


ACTORS = {"human", "strategy"}
MODES = {GameMode.OMNIDIRECTIONAL.value, GameMode.MIXED_DIRECTIONAL.value}
LOGIN_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
ID_PATTERN = re.compile(r"^[0-9a-f]{20}$")
KEY_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
BASE64URL_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
ALGORITHM = "RSA-OAEP-3072+A256GCM"

SUBMISSION_FIELDS = {
    "schema_version",
    "key_id",
    "summary",
    "encrypted_replay",
    "submission_id",
}
SUMMARY_FIELDS = {
    "engine_version",
    "nickname",
    "account_hash",
    "actor",
    "mode",
    "category",
    "virtual_time_s",
    "source_count",
    "seconds_per_source",
    "directional_count",
    "omnidirectional_count",
    "public_strategy_name",
}
ENCRYPTED_FIELDS = {"algorithm", "wrapped_key", "iv", "ciphertext"}


def canonical_json(payload: Any) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def account_hash(login: str) -> str:
    if not isinstance(login, str) or not LOGIN_PATTERN.fullmatch(login):
        raise SubmissionError("invalid GitHub login")
    return hashlib.sha256(login.lower().encode("utf-8")).hexdigest()


def category_for(actor: str, mode: str) -> str:
    if actor not in ACTORS:
        raise SubmissionError("actor must be human or strategy")
    if mode not in MODES:
        raise SubmissionError("showcase runs cannot enter the leaderboard")
    return f"{actor}_{mode}"


def _display_name(value: Any, *, label: str, limit: int) -> str:
    if not isinstance(value, str) or value != value.strip() or not 1 <= len(value) <= limit:
        raise SubmissionError(f"{label} must contain 1-{limit} characters")
    if any(unicodedata.category(character).startswith("C") for character in value):
        raise SubmissionError(f"{label} contains unsupported characters")
    return value


def _number(value: Any, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise SubmissionError(f"invalid {label}")
    return float(value)


def _integer(value: Any, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SubmissionError(f"invalid {label}")
    return value


def prepare_submission(
    managed: Any,
    *,
    login: str,
    nickname: str,
    public_strategy_name: str | None = None,
) -> dict[str, Any]:
    game = managed.game
    if not game.completed:
        raise SubmissionError("only complete runs can be submitted")
    if game.assisted:
        raise SubmissionError("assisted runs cannot be submitted")
    actor = managed.actor
    category = category_for(actor, game.mode.value)
    public_name = None
    if actor == "strategy":
        public_name = _display_name(
            public_strategy_name or "匿名策略",
            label="public strategy name",
            limit=32,
        )
    summary = {
        "engine_version": ENGINE_VERSION,
        "nickname": _display_name(nickname, label="nickname", limit=24),
        "account_hash": account_hash(login),
        "actor": actor,
        "mode": game.mode.value,
        "category": category,
        "virtual_time_s": game.virtual_time_s,
        "source_count": game.source_count,
        "seconds_per_source": game.virtual_time_s / game.source_count,
        "directional_count": game.directional_count,
        "omnidirectional_count": game.omnidirectional_count,
        "public_strategy_name": public_name,
    }
    return {"summary": summary, "replay": build_replay(managed)}


def _submission_id(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()[:20]


def build_encrypted_submission(
    summary: dict[str, Any], *, key_id: str, encrypted_replay: dict[str, Any]
) -> dict[str, Any]:
    payload = {
        "schema_version": 2,
        "key_id": key_id,
        "summary": summary,
        "encrypted_replay": encrypted_replay,
    }
    payload["submission_id"] = _submission_id(payload)
    return validate_public_submission(payload)


def validate_public_submission(submission: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(submission, dict):
        raise SubmissionError("submission must be an object")
    if set(submission) != SUBMISSION_FIELDS:
        raise SubmissionError("unexpected submission fields")
    if submission.get("schema_version") != 2:
        raise SubmissionError("unsupported submission schema")
    key_id = submission.get("key_id")
    if not isinstance(key_id, str) or not KEY_ID_PATTERN.fullmatch(key_id):
        raise SubmissionError("invalid key id")

    summary = submission.get("summary")
    if not isinstance(summary, dict) or set(summary) != SUMMARY_FIELDS:
        raise SubmissionError("unexpected summary fields")
    if summary.get("engine_version") != ENGINE_VERSION:
        raise SubmissionError("engine version mismatch")
    _display_name(summary.get("nickname"), label="nickname", limit=24)
    if not isinstance(summary.get("account_hash"), str) or not HASH_PATTERN.fullmatch(
        summary["account_hash"]
    ):
        raise SubmissionError("invalid account hash")
    expected_category = category_for(summary.get("actor"), summary.get("mode"))
    if summary.get("category") != expected_category:
        raise SubmissionError("category mismatch")
    source_count = _integer(summary.get("source_count"), label="source count")
    directional = _integer(summary.get("directional_count"), label="directional count")
    omnidirectional = _integer(
        summary.get("omnidirectional_count"), label="omnidirectional count"
    )
    if source_count <= 0 or directional < 0 or omnidirectional < 0:
        raise SubmissionError("invalid source counts")
    if directional + omnidirectional != source_count:
        raise SubmissionError("source count mismatch")
    virtual_time = _number(summary.get("virtual_time_s"), label="virtual time")
    score = _number(summary.get("seconds_per_source"), label="score")
    if virtual_time < 0 or not math.isclose(
        score, virtual_time / source_count, rel_tol=1e-12, abs_tol=1e-9
    ):
        raise SubmissionError("score mismatch")
    if summary["actor"] == "strategy":
        _display_name(
            summary.get("public_strategy_name"), label="public strategy name", limit=32
        )
    elif summary.get("public_strategy_name") is not None:
        raise SubmissionError("human submissions cannot name a strategy")

    encrypted = submission.get("encrypted_replay")
    if not isinstance(encrypted, dict) or set(encrypted) != ENCRYPTED_FIELDS:
        raise SubmissionError("unexpected encrypted replay fields")
    if encrypted.get("algorithm") != ALGORITHM:
        raise SubmissionError("unsupported encryption algorithm")
    for field in ("wrapped_key", "iv", "ciphertext"):
        value = encrypted.get(field)
        if not isinstance(value, str) or not BASE64URL_PATTERN.fullmatch(value):
            raise SubmissionError(f"invalid encrypted replay {field}")
    if len(encrypted["wrapped_key"]) != 512:
        raise SubmissionError("invalid encrypted replay wrapped_key")
    if len(encrypted["iv"]) != 16:
        raise SubmissionError("invalid encrypted replay iv")
    if not 24 <= len(encrypted["ciphertext"]) <= 1_800_000:
        raise SubmissionError("invalid encrypted replay ciphertext")

    claimed_id = submission.get("submission_id")
    if not isinstance(claimed_id, str) or not ID_PATTERN.fullmatch(claimed_id):
        raise SubmissionError("invalid submission id")
    id_payload = {key: submission[key] for key in submission if key != "submission_id"}
    if claimed_id != _submission_id(id_payload):
        raise SubmissionError("submission id mismatch")
    return dict(submission)


def validate_decrypted_submission(
    submission: dict[str, Any],
    replay: dict[str, Any],
    *,
    author: str,
    expected_key_id: str | None = None,
) -> dict[str, Any]:
    normalized = validate_public_submission(submission)
    if expected_key_id is not None and normalized["key_id"] != expected_key_id:
        raise SubmissionError("key id mismatch")
    summary = normalized["summary"]
    if summary["account_hash"] != account_hash(author):
        raise SubmissionError("submission author mismatch")
    try:
        result = verify_replay(replay)
    except (KeyError, ReplayError, TypeError, ValueError) as error:
        raise SubmissionError(str(error)) from error
    if not result["completed"]:
        raise SubmissionError("run is not complete")
    if result["assisted"]:
        raise SubmissionError("assisted run is ineligible")
    if replay.get("mode") != summary["mode"]:
        raise SubmissionError("mode mismatch")
    source_count = int(replay["source_count"])
    game = GameSession.new(seed=int(replay["seed"]), mode=GameMode(replay["mode"]))
    numeric_checks = {
        "virtual time": (summary["virtual_time_s"], result["virtual_time_s"]),
        "score": (summary["seconds_per_source"], result["virtual_time_s"] / source_count),
    }
    for label, (claimed, expected) in numeric_checks.items():
        if not math.isclose(float(claimed), expected, rel_tol=1e-12, abs_tol=1e-9):
            raise SubmissionError(f"{label} mismatch")
    count_checks = {
        "source_count": source_count,
        "directional_count": game.directional_count,
        "omnidirectional_count": game.omnidirectional_count,
    }
    for key, expected in count_checks.items():
        if summary[key] != expected:
            raise SubmissionError(f"{key} mismatch")
    return normalized


def write_submission(submission: dict[str, Any], root: Path) -> Path:
    validate_public_submission(submission)
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{submission['submission_id']}.json"
    path.write_text(
        json.dumps(submission, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return path
