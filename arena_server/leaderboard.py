"""Local orchestration for export, GitHub login, and score publication."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from arena_leaderboard.github_auth import DeviceFlow, GitHubAuthError, TokenStore
from arena_leaderboard.schema_v2 import (
    SubmissionError,
    canonical_json,
    prepare_submission,
    validate_public_submission,
    write_submission,
)
from arena_leaderboard.submission import (
    GitHubAPI,
    GitHubAPIError,
    GitHubPublisher,
    RepositoryConfig,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class LeaderboardService:
    def __init__(
        self,
        *,
        config_path: Path = PROJECT_ROOT / "leaderboard" / "config.json",
        exports_root: Path = PROJECT_ROOT / "data" / "submissions",
        token_store: TokenStore | None = None,
    ) -> None:
        self.config_path = Path(config_path)
        self.exports_root = Path(exports_root)
        self.token_store = token_store or TokenStore()
        self.device_flow: DeviceFlow | None = None
        self.config: RepositoryConfig | None = None
        if self.config_path.exists():
            loaded = RepositoryConfig.load(self.config_path)
            if (
                loaded.oauth_client_id
                and not loaded.oauth_client_id.startswith("REPLACE_")
                and loaded.encryption_key_id
                and loaded.encryption_public_key_jwk
            ):
                self.config = loaded

    def status(self) -> dict[str, Any]:
        return {
            "configured": self.config is not None,
            "signed_in": self.token_store.load() is not None,
            "leaderboard_url": self.config.leaderboard_url if self.config else "",
        }

    def export(self, managed: Any, *, entrant: str) -> dict[str, Any]:
        raise SubmissionError("plaintext leaderboard exports are disabled")

    def begin_auth(self) -> dict[str, Any]:
        if self.config is None:
            raise GitHubAuthError("leaderboard GitHub login is not configured")
        self.device_flow = DeviceFlow(self.config.oauth_client_id)
        return self.device_flow.begin()

    def poll_auth(self) -> dict[str, Any]:
        if self.device_flow is None:
            raise GitHubAuthError("device flow has not started")
        result = self.device_flow.poll()
        if result["status"] == "authorized":
            token = result.pop("access_token")
            try:
                result["login"] = GitHubAPI(token).request("GET", "/user")["login"]
            except GitHubAPIError as error:
                if error.status == 401:
                    self.token_store.clear()
                raise
            self.token_store.save(token)
        return result

    def prepare(
        self,
        managed: Any,
        *,
        nickname: str,
        public_strategy_name: str | None = None,
    ) -> dict[str, Any]:
        if self.config is None:
            raise GitHubAPIError("leaderboard upload is not configured")
        token = self.token_store.load()
        if token is None:
            return {"status": "needs_auth"}
        api = GitHubAPI(token)
        try:
            login = api.request("GET", "/user")["login"]
            package = prepare_submission(
                managed,
                login=login,
                nickname=nickname,
                public_strategy_name=public_strategy_name,
            )
            return {
                "status": "ready",
                "summary": package["summary"],
                "replay": package["replay"],
                "key_id": self.config.encryption_key_id,
                "public_key_jwk": self.config.encryption_public_key_jwk,
            }
        except GitHubAPIError as error:
            if error.status == 401:
                self.token_store.clear()
                return {"status": "needs_auth"}
            raise

    def submit(self, managed: Any, submission: dict[str, Any]) -> dict[str, Any]:
        if self.config is None:
            raise GitHubAPIError("leaderboard upload is not configured")
        token = self.token_store.load()
        if token is None:
            return {"status": "needs_auth"}
        api = GitHubAPI(token)
        try:
            login = api.request("GET", "/user")["login"]
            normalized = validate_public_submission(submission)
            if normalized["key_id"] != self.config.encryption_key_id:
                raise SubmissionError("encryption key is out of date")
            summary = normalized["summary"]
            expected = prepare_submission(
                managed,
                login=login,
                nickname=summary["nickname"],
                public_strategy_name=summary["public_strategy_name"],
            )["summary"]
            if canonical_json(summary) != canonical_json(expected):
                raise SubmissionError("submission does not match current session")
            write_submission(normalized, self.exports_root)
            return GitHubPublisher(api, self.config).publish(normalized, login=login)
        except GitHubAPIError as error:
            if error.status == 401:
                self.token_store.clear()
                return {"status": "needs_auth"}
            raise
