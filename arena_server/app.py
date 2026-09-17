"""Command-line entry point for the local Arena web application."""

from __future__ import annotations

import argparse
import threading
import webbrowser
from pathlib import Path

from .http import create_server
from .sessions import SessionStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the local B-problem Arena")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=0, type=int)
    parser.add_argument("--data-dir", default="data/sessions", type=Path)
    parser.add_argument("--no-browser", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    store = SessionStore(args.data_dir)
    server = create_server((args.host, args.port), store=store)
    url = f"http://{args.host}:{server.server_port}/"
    print(f"Arena running at {url}", flush=True)
    print("Press Ctrl+C to stop.", flush=True)
    if not args.no_browser:
        threading.Timer(0.25, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

