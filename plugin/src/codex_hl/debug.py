"""Minimal connector diagnostics for the Codex HL Civ6 plugin."""

from __future__ import annotations

import argparse
import json
import socket
from pathlib import Path

from civ6_connector import game_launcher


def tuner_port_open(port: int = 4318) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=2):
            return True
    except OSError:
        return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run safe Codex HL Civ6 connector diagnostics."
    )
    parser.add_argument("--port", type=int, default=4318)
    args = parser.parse_args()

    payload = {
        "plugin_root": str(Path(__file__).resolve().parents[2]),
        "save_dir": str(game_launcher.SINGLE_SAVE_DIR),
        "game_running": game_launcher.is_game_running(),
        "firetuner_port": args.port,
        "firetuner_reachable": tuner_port_open(args.port),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
