"""JSON-lines subprocess that loads one user strategy."""

from __future__ import annotations

import contextlib
import importlib.util
import json
import sys
import traceback
from pathlib import Path


def _load(path: Path):
    spec = importlib.util.spec_from_file_location("arena_user_strategy", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load strategy")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    strategy_type = getattr(module, "Strategy", None)
    if strategy_type is None:
        raise RuntimeError("strategy must define class Strategy")
    return strategy_type()


def main() -> int:
    with contextlib.redirect_stdout(sys.stderr):
        strategy = _load(Path(sys.argv[1]).resolve())
    for raw in sys.stdin:
        try:
            request = json.loads(raw)
            operation = request["operation"]
            with contextlib.redirect_stdout(sys.stderr):
                if operation == "reset":
                    result = strategy.reset(request["payload"])
                elif operation == "next_action":
                    result = strategy.next_action(request["payload"])
                else:
                    raise RuntimeError("unknown worker operation")
            response = {"ok": True, "result": result}
        except Exception as error:  # strategy failures must stay in the worker
            response = {
                "ok": False,
                "error": f"{type(error).__name__}: {error}",
                "traceback": traceback.format_exc(limit=8),
            }
        print(json.dumps(response, ensure_ascii=False, allow_nan=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
