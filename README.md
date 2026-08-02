# Kalshi Command Bot

A fast iSH-to-VPS command system for placing configured Kalshi orders. The phone
contains no Kalshi credentials and makes no market decisions; it sends trade keys
and runtime control commands to the VPS.

## What it provides

- Paper, one-contract test, and live modes.
- Aggressive IOC order-book sweeps for live buys.
- One deterministic JSON event config with exact event/market tickers, URLs, and
  line or proposition text.
- Persistent event-session blocks, kill state, runtime cap overrides, and all-in
  spending totals.
- Per-press, per-market, and per-event cost caps.
- Append-only JSONL command and trade logs; no database.
- A responsive kill switch that interrupts active sweeps and cancels all resting
  orders on the configured Kalshi subaccount.

## Architecture

```text
iPhone: iSH sender
        |
        | private WebSocket over Tailscale
        v
AWS VPS: command server -> runtime controls -> Kalshi REST API
```

The recommended private connection is documented in
[`docs/IPHONE_VPS_CONNECTION.md`](docs/IPHONE_VPS_CONNECTION.md).

## VPS install

```bash
git clone <your-repo-url>
cd Live-sport-trading-bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
cp config/active.example.json config/active.json
```

`.env` is the single source of truth for the Kalshi environment and account-level
risk defaults:

```text
KALSHI_ENV=demo
DEFAULT_MARKET_COST_CAP_DOLLARS=
EVENT_COST_CAP_DOLLARS=
```

The Kalshi signing key is stored directly in `.env`, on one line with literal
`\n` separators:

```text
KALSHI_PRIVATE_KEY_PEM='-----BEGIN PRIVATE KEY-----\nKEY_BODY\n-----END PRIVATE KEY-----'
```

Keep the single quotes. The `.env` file is excluded from Git, so the key itself is
never committed.

Blank market or event caps mean infinite. `DEFAULT_MARKET_COST_CAP_DOLLARS` applies
independently to every buy key. Runtime `/limit` commands override these defaults
for the current event session.

The all-in caps count confirmed contract cost plus the fees reported by Kalshi.
The server reserves the configured fee rate and flat amount before submitting an
order so the trade is kept inside the all-in allowance.

## AI-generated event configs

Use [`docs/AI_CONFIG_SPEC.md`](docs/AI_CONFIG_SPEC.md) as the contract for the setup
agent. The generated JSON supplies exact endpoints and mappings; the trading bot
does not select or infer markets.

Upload the candidate and activate it atomically:

```bash
python scripts/activate_config.py /path/to/generated-match.json
sudo systemctl restart kalshi-command-bot
```

A different `event_ticker` creates a fresh session. Replacing the file for the same
event preserves blocks, limits, kill state, and spending across phone reconnects
and VPS process restarts.

## Runtime commands

Trade keys remain single characters such as `A`, `S`, `D`, `F`, `1`, and `2`.

```text
/help
/status
/block A
/block all
/unblock A
/unblock all
/limit press A 50
/limit market A 150
/limit market A infinite
/limit event 500
/limit event infinite
/disarm
/arm
/reset kill
K
```

`/block A` prevents `A` from executing and signals an active `A` sweep to stop.
`K` persists the kill state, signals every active sweep, cancels all resting orders,
waits for the order worker, and cancels once more. `/reset kill` clears the kill
state but does not remove command blocks.

## Configured buy command

```json
"A": {
  "label": "Team A spread",
  "action": "buy",
  "market_ticker": "EXACT_KALSHI_MARKET_TICKER",
  "market_url": "https://kalshi.com/markets/EXACT_KALSHI_MARKET_TICKER",
  "line_or_prop": "Team A -3.5",
  "side": "yes",
  "spend_up_to_dollars": 50,
  "enabled": true
}
```

`spend_up_to_dollars` is the normal per-press all-in ceiling. It can be changed for
the active session with `/limit press A AMOUNT`.

## Files written at runtime

```text
config/runtime_state.json  local-run controls, limits, and spending totals
logs/commands.jsonl        local-run command and trade audit records
```

Both paths can be changed in `.env`; both are excluded from Git. The supplied
systemd unit uses `/var/lib/kalshi-command-bot/runtime_state.json` and
`/var/log/kalshi-command-bot/commands.jsonl`, with writable directories created by
systemd for the unprivileged `kalshi` service user.

## Tests

```bash
pip install -r requirements-dev.txt
pytest -q
```

## Legal and platform note

Use only official Kalshi APIs, comply with applicable market rules and location
restrictions, and treat all event-contract trading as financially risky.
