"""GitHub REST client that publishes a score through a fork pull request."""

from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .schema_v2 import account_hash


class GitHubAPIError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class RepositoryConfig:
    owner: str
    repo: str
    default_branch: str = "main"
    oauth_client_id: str = ""
    leaderboard_url: str = ""
    encryption_key_id: str = ""
    encryption_public_key_jwk: dict[str, Any] | None = None

    @classmethod
    def load(cls, path: Path) -> "RepositoryConfig":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            owner=str(payload["owner"]),
            repo=str(payload["repo"]),
            default_branch=str(payload.get("default_branch", "main")),
            oauth_client_id=str(payload.get("oauth_client_id", "")),
            leaderboard_url=str(payload.get("leaderboard_url", "")),
            encryption_key_id=str(payload.get("encryption_key_id", "")),
            encryption_public_key_jwk=payload.get("encryption_public_key_jwk"),
        )


class GitHubAPI:
    BASE_URL = "https://api.github.com"

    def __init__(self, token: str) -> None:
        self.token = token

    def request(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        raw = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.BASE_URL + path,
            data=raw,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "b-problem-arena",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = response.read()
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as error:
            try:
                message = json.loads(error.read()).get("message", str(error))
            except (json.JSONDecodeError, AttributeError):
                message = str(error)
            raise GitHubAPIError(message, status=error.code) from error


class GitHubPublisher:
    def __init__(
        self,
        api: Any,
        config: RepositoryConfig,
        *,
        id_factory: Callable[[], str] = lambda: uuid.uuid4().hex[:10],
    ) -> None:
        self.api = api
        self.config = config
        self.id_factory = id_factory

    def _ensure_fork(self, login: str) -> None:
        if login == self.config.owner:
            return
        try:
            self.api.request("GET", f"/repos/{login}/{self.config.repo}")
            return
        except GitHubAPIError as error:
            if error.status != 404:
                raise
        self.api.request(
            "POST", f"/repos/{self.config.owner}/{self.config.repo}/forks", {}
        )
        for _ in range(10):
            try:
                self.api.request("GET", f"/repos/{login}/{self.config.repo}")
                return
            except GitHubAPIError as error:
                if error.status != 404:
                    raise
                time.sleep(1)
        raise GitHubAPIError("GitHub fork is still being created; please try again")

    def publish(self, submission: dict[str, Any], *, login: str) -> dict[str, Any]:
        if submission.get("summary", {}).get("account_hash") != account_hash(login):
            raise GitHubAPIError("submission account does not match signed-in GitHub user")
        self._ensure_fork(login)
        suffix = self.id_factory()
        branch = f"arena-score-{suffix}"
        upstream = f"/repos/{self.config.owner}/{self.config.repo}"
        fork = f"/repos/{login}/{self.config.repo}"
        base_ref = self.api.request(
            "GET", f"{upstream}/git/ref/heads/{self.config.default_branch}"
        )
        self.api.request(
            "POST",
            f"{fork}/git/refs",
            {"ref": f"refs/heads/{branch}", "sha": base_ref["object"]["sha"]},
        )
        destination = (
            f"submissions/{account_hash(login)}/{submission['submission_id']}.json"
        )
        content = json.dumps(
            submission, ensure_ascii=False, indent=2, allow_nan=False
        ) + "\n"
        self.api.request(
            "PUT",
            f"{fork}/contents/{destination}",
            {
                "message": f"score: submit {submission['submission_id']}",
                "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
                "branch": branch,
            },
        )
        pull = self.api.request(
            "POST",
            f"{upstream}/pulls",
            {
                "title": f"Arena score: {submission['summary']['nickname']}",
                "body": "Submitted by the local B-problem Arena. The replay is validated by GitHub Actions.",
                "head": f"{login}:{branch}",
                "base": self.config.default_branch,
            },
        )
        return {
            "status": "submitted",
            "pull_request_url": pull["html_url"],
            "pull_request_number": pull["number"],
        }
