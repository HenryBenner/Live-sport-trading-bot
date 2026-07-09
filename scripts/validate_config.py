from __future__ import annotations

import sys
from pathlib import Path

# Allow running from repo root without installing as package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.config_loader import ConfigError, load_config, profile_summary


def main() -> int:
    path = Path("config/active.json")
    if len(sys.argv) > 1:
        path = Path(sys.argv[1])

    try:
        config = load_config(path)
    except ConfigError as exc:
        print(f"INVALID CONFIG: {exc}")
        return 1

    summary = profile_summary(config)

    print("VALID CONFIG")
    print(f"Profile: {summary['profile_name']}")
    print(f"Event: {summary['event_name']}")
    print(f"Mode: {summary['mode']}")
    print("Commands:")
    for command in summary["commands"]:
        state = "enabled" if command["enabled"] else "disabled"
        print(f"  {command['key']}: {command['label']} [{command['action']}] {state}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
