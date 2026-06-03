"""Load and verify the standard Civ6 ``test 1`` save from the shell."""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Load a Civ6 save, defaulting to the standard test 1 save.",
    )
    parser.add_argument("--save-name", default="test 1")
    parser.add_argument("--port", type=int, default=4318)
    parser.add_argument("--initial-wait-seconds", type=float, default=10.0)
    parser.add_argument("--verify-timeout", type=float, default=240.0)
    parser.add_argument("--load-timeout", type=float, default=90.0)
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    parser.add_argument("--connect-retries", type=int, default=3)
    parser.add_argument("--load-retries", type=int, default=1)
    parser.add_argument(
        "--no-launch",
        action="store_true",
        help="fail instead of launching Civ6 when FireTuner is not reachable",
    )
    parser.add_argument(
        "--force-restart",
        action="store_true",
        help="kill and relaunch Civ6 before loading the save",
    )
    parser.add_argument(
        "--no-continue-screen",
        action="store_true",
        help="do not try to dismiss the leader continue screen after loading",
    )
    parser.add_argument(
        "--no-ocr-fallback",
        action="store_true",
        help="fail if FireTuner Lua cannot load the save; do not use OCR/menu fallback",
    )
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    return parser


async def load_and_verify(
    *,
    save_name: str,
    port: int,
    initial_wait_seconds: float,
    verify_timeout: float,
    poll_seconds: float,
    launch_if_needed: bool,
    connect_retries: int,
    load_retries: int,
    load_timeout: float,
    force_restart: bool,
    continue_screen: bool,
    allow_ocr_fallback: bool = True,
) -> dict[str, Any]:
    from civ6_connector.connection import GameConnection
    from civ6_connector import game_launcher
    from civ6_connector.game_lifecycle import front_end_load_game_save, load_game_save
    from civ6_connector.game_state import GameState

    conn = GameConnection(port=port)
    payload: dict[str, Any] = {
        "ok": False,
        "save_name": save_name,
        "firetuner_port": port,
    }
    try:
        if force_restart:
            payload["kill_result"] = await game_launcher.kill_game()
            payload["launch_result"] = await game_launcher.launch_game()
            await asyncio.sleep(poll_seconds)

        launched = False
        last_connect_error = ""
        for attempt in range(1, max(1, connect_retries) + 1):
            try:
                await conn.connect()
                payload["connect_attempts"] = attempt
                break
            except Exception as exc:  # noqa: BLE001 - FireTuner can reset during launch.
                last_connect_error = f"{type(exc).__name__}: {exc}"
                if launch_if_needed and not launched:
                    payload["launch_result"] = await game_launcher.launch_game()
                    launched = True
                await asyncio.sleep(poll_seconds)
        else:
            raise ConnectionError(last_connect_error)

        last_load_error = ""
        for attempt in range(1, max(1, load_retries + 1) + 1):
            try:
                if _front_end_ready(conn) and conn.gamecore_index is None:
                    payload["load_path"] = "front_end_lua"
                    payload["load_result"] = await asyncio.wait_for(
                        front_end_load_game_save(conn, save_name),
                        timeout=load_timeout,
                    )
                else:
                    payload["load_path"] = "game_lifecycle"
                    payload["load_result"] = await asyncio.wait_for(
                        load_game_save(conn, save_name, allow_ocr_fallback=allow_ocr_fallback),
                        timeout=load_timeout,
                    )
                if str(payload["load_result"]).startswith("Error:"):
                    raise RuntimeError(str(payload["load_result"]))
                payload["load_attempts"] = attempt
                break
            except Exception as exc:  # noqa: BLE001 - reload often resets FireTuner once.
                last_load_error = f"{type(exc).__name__}: {exc}"
                if attempt > load_retries:
                    raise
                try:
                    await conn.reconnect()
                except Exception:
                    pass
                await asyncio.sleep(poll_seconds)
        else:
            raise RuntimeError(last_load_error)

        if initial_wait_seconds > 0:
            await asyncio.sleep(initial_wait_seconds)
        if continue_screen:
            payload["continue_result"] = await asyncio.to_thread(
                _try_continue_from_leader_screen, game_launcher
            )

        gs = GameState(conn)
        deadline = asyncio.get_running_loop().time() + verify_timeout
        attempt = 0
        last_error = ""
        continue_retry_done = False
        while asyncio.get_running_loop().time() <= deadline:
            attempt += 1
            try:
                await conn.reconnect()
                overview = await gs.get_game_overview()
                payload.update(
                    {
                        "ok": True,
                        "verified": True,
                        "attempts": attempt,
                        "overview": str(overview),
                    }
                )
                return payload
            except Exception as exc:  # noqa: BLE001 - report retryable runtime state.
                last_error = f"{type(exc).__name__}: {exc}"
                if continue_screen and not continue_retry_done:
                    continue_retry_done = True
                    payload["continue_retry_result"] = await asyncio.to_thread(
                        _try_continue_from_leader_screen, game_launcher
                    )
                await asyncio.sleep(poll_seconds)

        payload.update(
            {
                "verified": False,
                "attempts": attempt,
                "last_error": last_error,
            }
        )
        return payload
    finally:
        await conn.disconnect()


def _front_end_ready(conn: Any) -> bool:
    return any(name in {"LoadGameMenu", "FrontEnd"} for name in conn.lua_states.values())


def _try_continue_from_leader_screen(game_launcher: Any) -> str:
    try:
        import ctypes
        import sys
        import time

        game_launcher._bring_to_front()
        clicked = []
        for text in ("CONTINUE", "继续游戏", "繼續遊戲"):
            try:
                if game_launcher._click_text(text, timeout=2, post_delay=0.5):
                    clicked.append(f"text:{text}")
                    break
            except Exception:
                pass
        try:
            game_launcher._click_continue_positional()
            clicked.append("positional")
        except Exception:
            pass
        if sys.platform == "win32":
            user32 = ctypes.windll.user32
            for vk in (0x1B, 0x20, 0x0D, 0x0D):  # Esc, Space, Enter, Enter
                user32.keybd_event(vk, 0, 0, 0)
                time.sleep(0.08)
                user32.keybd_event(vk, 0, 2, 0)
                time.sleep(0.4)
            clicked.append("keys")
        return "attempted " + ", ".join(clicked)
    except Exception as exc:  # noqa: BLE001 - best-effort UI recovery.
        return f"continue attempt failed: {type(exc).__name__}: {exc}"


def print_human(payload: dict[str, Any]) -> None:
    print(payload.get("load_result", "No load result returned."))
    if payload.get("ok"):
        print()
        print(payload["overview"])
        return
    print()
    print("Load verification failed.")
    if payload.get("last_error"):
        print(payload["last_error"])
    if payload.get("error"):
        print(payload["error"])


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    try:
        payload = asyncio.run(
            load_and_verify(
                save_name=args.save_name,
                port=args.port,
                initial_wait_seconds=args.initial_wait_seconds,
                verify_timeout=args.verify_timeout,
                poll_seconds=args.poll_seconds,
                launch_if_needed=not args.no_launch,
                connect_retries=args.connect_retries,
                load_retries=args.load_retries,
                load_timeout=args.load_timeout,
                force_restart=args.force_restart,
                continue_screen=not args.no_continue_screen,
                allow_ocr_fallback=not args.no_ocr_fallback,
            )
        )
    except Exception as exc:  # noqa: BLE001 - shell command should fail legibly.
        payload = {
            "ok": False,
            "save_name": args.save_name,
            "firetuner_port": args.port,
            "error": f"{type(exc).__name__}: {exc}",
        }

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print_human(payload)

    if not payload.get("ok"):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
