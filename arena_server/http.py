"""Dependency-free local JSON API and static-file server."""

from __future__ import annotations

import json
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from arena_core import ActionError, GameMode
from arena_core.replay import build_replay
from arena_leaderboard.github_auth import GitHubAuthError
from arena_leaderboard.schema_v2 import SubmissionError
from arena_leaderboard.submission import GitHubAPIError

from .leaderboard import LeaderboardService
from .sessions import SessionStore
from .strategy_runner import StrategyController, StrategyError, discover_strategies


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = PROJECT_ROOT / "web"
STRATEGIES_ROOT = PROJECT_ROOT / "strategies"


class ArenaHTTPServer(ThreadingHTTPServer):
    strategy_controller: StrategyController

    def server_close(self) -> None:
        controller = getattr(self, "strategy_controller", None)
        if controller is not None:
            controller.close_all()
        super().server_close()


def create_server(
    address: tuple[str, int],
    *,
    store: SessionStore,
    web_root: Path = WEB_ROOT,
    strategies_root: Path = STRATEGIES_ROOT,
    leaderboard_service: LeaderboardService | None = None,
) -> ThreadingHTTPServer:
    controller = StrategyController(strategies_root)
    leaderboard = leaderboard_service or LeaderboardService()

    class ArenaHandler(BaseHTTPRequestHandler):
        server_version = "ArenaLocal/0.1"

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _send_json(self, status: int, payload: Any) -> None:
            raw = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)

        def _body(self) -> dict[str, Any]:
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if size > 2_000_000:
                    raise ActionError("request body is too large")
                payload = json.loads(self.rfile.read(size) or b"{}")
            except (ValueError, json.JSONDecodeError) as error:
                raise ActionError("invalid JSON body") from error
            if not isinstance(payload, dict):
                raise ActionError("JSON body must be an object")
            return payload

        def _segments(self) -> list[str]:
            return [segment for segment in urlparse(self.path).path.split("/") if segment]

        def _session(self, segments: list[str]):
            if len(segments) < 3:
                raise KeyError("missing session id")
            return store.get(segments[2])

        def _serve_static(self, request_path: str) -> None:
            relative = "index.html" if request_path == "/" else request_path.lstrip("/")
            if relative not in {
                "index.html",
                "styles.css",
                "app.js",
                "map.js",
                "leaderboard-crypto.mjs",
            }:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            path = web_root / relative
            if not path.exists():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            raw = path.read_bytes()
            mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", f"{mime}; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self) -> None:
            segments = self._segments()
            try:
                if segments == ["api", "health"]:
                    self._send_json(HTTPStatus.OK, {"ok": True})
                elif segments == ["api", "strategies"]:
                    self._send_json(
                        HTTPStatus.OK,
                        {"strategies": discover_strategies(strategies_root)},
                    )
                elif segments == ["api", "leaderboard"]:
                    self._send_json(HTTPStatus.OK, leaderboard.status())
                elif len(segments) == 3 and segments[:2] == ["api", "sessions"]:
                    self._send_json(HTTPStatus.OK, self._session(segments).public_state())
                elif (
                    len(segments) == 4
                    and segments[:2] == ["api", "sessions"]
                    and segments[3] == "export"
                ):
                    self._send_json(HTTPStatus.OK, build_replay(self._session(segments)))
                elif not segments or segments[0] not in {"api"}:
                    self._serve_static(urlparse(self.path).path)
                else:
                    self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            except KeyError:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "session not found"})
            except (ActionError, ValueError) as error:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})

        def do_POST(self) -> None:
            segments = self._segments()
            try:
                payload = self._body()
                if segments == ["api", "github", "device", "start"]:
                    self._send_json(HTTPStatus.OK, leaderboard.begin_auth())
                    return
                if segments == ["api", "github", "device", "poll"]:
                    self._send_json(HTTPStatus.OK, leaderboard.poll_auth())
                    return
                if segments == ["api", "sessions"]:
                    managed = store.create(
                        mode=GameMode(payload.get("mode")),
                        seed=payload.get("seed"),
                    )
                    self._send_json(HTTPStatus.CREATED, managed.public_state())
                    return
                managed = self._session(segments)
                if len(segments) == 5 and segments[3] == "strategy":
                    operation = segments[4]
                    if operation == "start":
                        strategy = controller.start(managed, payload.get("name"))
                        state = {"strategy": strategy, "state": managed.public_state()}
                    elif operation == "step":
                        game_state = controller.step(managed)
                        state = {
                            "strategy": {
                                "name": controller.names[managed.game.session_id],
                                "running": True,
                            },
                            "action": game_state["events"][-1],
                            "state": game_state,
                        }
                    elif operation == "stop":
                        controller.stop(managed.game.session_id)
                        state = {
                            "strategy": {"name": None, "running": False},
                            "state": managed.public_state(),
                        }
                    else:
                        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
                        return
                    self._send_json(HTTPStatus.OK, state)
                    return
                if len(segments) == 5 and segments[3] == "leaderboard":
                    operation = segments[4]
                    if operation == "prepare":
                        result = leaderboard.prepare(
                            managed,
                            nickname=payload.get("nickname", ""),
                            public_strategy_name=payload.get("public_strategy_name"),
                        )
                    elif operation == "submit":
                        result = leaderboard.submit(managed, payload.get("submission"))
                    else:
                        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
                        return
                    self._send_json(HTTPStatus.OK, result)
                    return

                operation = segments[3] if len(segments) == 4 else ""
                if operation == "actions":
                    state = managed.apply_action(
                        payload.get("action"), command_id=payload.get("command_id")
                    )
                elif operation == "pause":
                    state = managed.pause()
                elif operation == "resume":
                    state = managed.resume()
                elif operation == "undo":
                    state = managed.undo()
                elif operation == "intel":
                    result = managed.get_intel(payload.get("kind"), payload.get("channel"))
                    state = {"intel": result, "state": managed.public_state()}
                else:
                    self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
                    return
                self._send_json(HTTPStatus.OK, state)
            except KeyError:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "session not found"})
            except (
                ActionError,
                GitHubAPIError,
                GitHubAuthError,
                StrategyError,
                SubmissionError,
                ValueError,
                TypeError,
            ) as error:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})

    server = ArenaHTTPServer(address, ArenaHandler)
    server.strategy_controller = controller
    return server
