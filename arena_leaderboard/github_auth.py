"""GitHub OAuth device flow for this local, browser-driven application."""

from __future__ import annotations

import json
import os
import platform
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


class GitHubAuthError(RuntimeError):
    pass


class UrllibTransport:
    def form(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            url,
            data=urllib.parse.urlencode(payload).encode("utf-8"),
            headers={"Accept": "application/json", "User-Agent": "b-problem-arena"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read())


class DeviceFlow:
    DEVICE_URL = "https://github.com/login/device/code"
    TOKEN_URL = "https://github.com/login/oauth/access_token"

    def __init__(self, client_id: str, *, transport: Any | None = None) -> None:
        if not client_id:
            raise GitHubAuthError("GitHub OAuth client ID is not configured")
        self.client_id = client_id
        self.transport = transport or UrllibTransport()
        self.device_code: str | None = None
        self.interval = 5

    def begin(self) -> dict[str, Any]:
        response = self.transport.form(
            self.DEVICE_URL, {"client_id": self.client_id, "scope": "public_repo"}
        )
        try:
            self.device_code = response["device_code"]
            self.interval = int(response.get("interval", 5))
            return {
                "user_code": response["user_code"],
                "verification_uri": response["verification_uri"],
                "expires_in": int(response["expires_in"]),
                "interval": self.interval,
            }
        except (KeyError, TypeError, ValueError) as error:
            raise GitHubAuthError(response.get("error_description", "device flow failed")) from error

    def poll(self) -> dict[str, Any]:
        if self.device_code is None:
            raise GitHubAuthError("device flow has not started")
        response = self.transport.form(
            self.TOKEN_URL,
            {
                "client_id": self.client_id,
                "device_code": self.device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
        )
        if "access_token" in response:
            return {"status": "authorized", "access_token": response["access_token"]}
        error = response.get("error")
        if error == "authorization_pending":
            return {"status": "pending", "interval": self.interval}
        if error == "slow_down":
            self.interval += 5
            return {"status": "pending", "interval": self.interval}
        raise GitHubAuthError(response.get("error_description", error or "authorization failed"))


def default_token_path() -> Path:
    system = platform.system()
    if system == "Darwin":
        root = Path.home() / "Library" / "Application Support"
    elif system == "Windows":
        root = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return root / "BProblemArena" / "github-token.json"


class TokenStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else default_token_path()

    def save(self, token: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"access_token": token}), encoding="utf-8")
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    def load(self) -> str | None:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            token = payload.get("access_token")
            return token if isinstance(token, str) and token else None
        except (OSError, json.JSONDecodeError):
            return None

    def clear(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
