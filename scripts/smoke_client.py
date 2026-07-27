from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import shutil
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


ROOT = Path(__file__).resolve().parents[1]
# P0.2: whitelist env-переменных для subprocess — а не весь os.environ.
_ENV_WHITELIST = (
    "PATH",
    "HOME",
    "USER",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "BLOCKSNET_MCP_TRACE",
    # Конфигурация blocksnet-agent (CHAT_URL, API_KEY, MODEL, DATA_DIR, OUTPUT_DIR,
    # MAX_ITERATIONS, DEADLINE_SEC) — пробрасывается через .env сервера.
    "CHAT_URL",
    "API_KEY",
    "MODEL",
    "DATA_DIR",
    "OUTPUT_DIR",
    "MAX_ITERATIONS",
    "DEADLINE_SEC",
)


def _pick_python() -> str:
    """Pick the project venv Python on Windows/POSIX, falling back to PATH/current Python."""

    candidates = []
    if platform.system().lower().startswith("win"):
        candidates.append(ROOT / ".venv" / "Scripts" / "python.exe")
    else:
        candidates.append(ROOT / ".venv" / "bin" / "python")
    candidates.extend([ROOT / ".venv" / "Scripts" / "python.exe", ROOT / ".venv" / "bin" / "python"])
    for candidate in candidates:
        if candidate.exists():
            # Preserve the venv symlink path; resolving to the base interpreter
            # can make subprocess/anyio miss this venv's site-packages.
            return str(candidate)
    return shutil.which("python") or shutil.which("python3") or sys.executable


def _safe_env() -> dict[str, str]:
    """P0.2: вернуть только безопасные переменные окружения для subprocess."""
    return {key: value for key, value in os.environ.items() if key in _ENV_WHITELIST}


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


async def _run(
    question: str | None,
    max_iterations: int,
    call: bool,
    invalid: bool,
    call_timeout: float,
) -> dict[str, Any]:
    params = StdioServerParameters(
        command=_pick_python(),
        args=["-m", "blocksnet_mcp.server"],
        cwd=str(ROOT),
        env=_safe_env(),
    )
    # P0.2: read_timeout_seconds на уровне сессии — не asyncio.wait_for.
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=call_timeout)) as session:
            await session.initialize()
            tools_result = await session.list_tools()
            payload: dict[str, Any] = {
                "tools": [
                    {
                        "name": tool.name,
                        "description": tool.description,
                        "inputSchema": tool.inputSchema,
                    }
                    for tool in tools_result.tools
                ]
            }
            if call:
                args = {"question": "" if invalid else question, "max_iterations": max_iterations}
                try:
                    # P0.2: progress callback слушает notifications/progress от сервера.
                    progress_events: list[dict[str, Any]] = []

                    async def on_progress(progress: float, total: float | None, message: str | None) -> None:
                        progress_events.append(
                            {"progress": progress, "total": total, "message": message or ""}
                        )

                    result = await session.call_tool(
                        "analyze_urban_question",
                        args,
                        progress_callback=on_progress,
                    )
                    payload["call"] = _jsonable(result)
                    if progress_events:
                        payload["progress_events"] = progress_events[-5:]
                except Exception as exc:
                    payload["call_error"] = {"type": type(exc).__name__, "message": str(exc)}
            return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke-test blocksnet-mcp over stdio.")
    parser.add_argument("--question", default="Где разместить новые спортивные площадки?")
    parser.add_argument("--max-iterations", type=int, default=1)
    parser.add_argument("--call-timeout", type=float, default=180.0)
    parser.add_argument("--call", action="store_true", help="Call analyze_urban_question after list_tools.")
    parser.add_argument("--invalid", action="store_true", help="Call with an empty question to test error handling.")
    args = parser.parse_args()

    payload = asyncio.run(_run(args.question, args.max_iterations, args.call, args.invalid, args.call_timeout))
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
