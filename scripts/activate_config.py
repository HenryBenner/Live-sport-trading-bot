from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Allow running from repo root without installing as a package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.config_loader import ConfigError, load_config


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate and atomically activate an AI-generated event config."
    )
    parser.add_argument("candidate", type=Path)
    parser.add_argument(
        "--target", type=Path, default=Path("config/active.json")
    )
    args = parser.parse_args()

    try:
        config = load_config(args.candidate)
    except (ConfigError, OSError, json.JSONDecodeError) as exc:
        print(f"CONFIG NOT ACTIVATED: {exc}")
        return 1

    args.target.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.target.with_suffix(args.target.suffix + ".tmp")
    temporary.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, args.target)
    print(f"ACTIVATED: {args.target}")
    print(f"Event: {config['event_name']} ({config['event_ticker']})")
    print("Restart kalshi-command-bot to load it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
