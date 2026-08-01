# Kalshi Command Bot

A slim command execution system for sending short iPhone Python commands to a VPS, then placing Kalshi orders from the VPS.

It uses:

- iPhone Python script as the controller
- WebSocket from iPhone to VPS
- Kalshi API on the VPS only
- One active config file
- Paper mode
- Test mode
- Live mode
- Aggressive order-book sweeps for live buys
- `M` to sell the current Kalshi YES position for the last bought market
- `K` as a kill switch that cancels known open orders

It does not include:

- Web page
- Dashboard
- Database
- Saved trade history
- Multi-exchange support
- Market search during live trading

## Architecture

```text
iPhone Python script
  ↓
WebSocket command
  ↓
VPS server
  ↓
Kalshi REST API
  ↓
Orders submitted
```

## Repo structure

```text
kalshi-command-bot/
  iphone/
    iphone_sender.py
  server/
    server.py
    config_loader.py
    command_router.py
    mode_handler.py
    kalshi_client.py
    aggressive_buyer.py
    open_order_manager.py
  config/
    active.example.json
  scripts/
    validate_config.py
    run_server.sh
  systemd/
    kalshi-command-bot.service
  docs/
    SOFTWARE_BLUEPRINT.md
    GAME_SETUP_CHECKLIST.md
  tests/
    test_aggressive_buy.py
  .env.example
  requirements.txt
  requirements-dev.txt
```

## Safety model

The iPhone never stores Kalshi credentials.

Only the VPS stores:

- Kalshi API key ID
- Kalshi private key path
- WebSocket control token

The iPhone sends commands such as:

```text
A
S
1
M
K
```

## Install on VPS

```bash
git clone <your-repo-url>
cd kalshi-command-bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
cp config/active.example.json config/active.json
```

Edit `.env` and `config/active.json`.

```bash
nano .env
nano config/active.json
python scripts/validate_config.py
python -m server.server
```

## Run on iPhone

Use an iPhone Python app that can install or include the `websockets` package.

Set these values inside `iphone/iphone_sender.py`, or enter them when prompted:

```text
wss://YOUR_VPS_DOMAIN_OR_IP:8765
CONTROL_TOKEN
```

Run the script and type a one-character command.

## Modes

Set mode in `config/active.json`.

```json
"mode": "paper"
```

Allowed modes:

```text
paper
test
live
```

Paper mode places no order.

Test mode submits one contract.

Live mode aggressively sweeps the current YES asks until it reaches the command's contract-cost cap or a stop condition occurs.

## Aggressive live-buy behavior

For every live buy command, the VPS:

1. Reads the full market order book.
2. Converts resting NO bids into executable YES asks.
3. Calculates the largest IOC order that can sweep the cheapest available asks without exceeding the remaining contract-cost budget.
4. Submits the IOC order at the highest ask included in that sweep.
5. Reads the actual fill count and average fill price.
6. Refreshes the order book and repeats immediately.

The loop stops when:

- The contract-cost cap is reached.
- No executable liquidity appears for the configured number of checks.
- The retry time window expires.
- The maximum number of sweep orders is reached.
- Kalshi returns a fatal market, authentication, balance, or validation error.
- An ambiguous write cannot be confirmed safely.

Rate-limit and temporary server failures retry automatically. Ambiguous write failures reuse the exact same `client_order_id`, which prevents a timeout retry from becoming a duplicate order.

Buy orders use:

```text
time_in_force = immediate_or_cancel
self_trade_prevention_type = maker
post_only = false
```

The `maker` self-trade setting cancels your conflicting resting maker order and allows the aggressive taker order to continue matching.

## Live-buy settings

```json
"aggressive_buy_price": "1.0000",
"buy_retry_max_attempts": 100,
"buy_retry_max_seconds": 10.0,
"buy_retry_no_progress_limit": 20,
"buy_retry_delay_seconds": 0.05,
"buy_retry_error_limit": 10
```

`aggressive_buy_price` is a maximum price ceiling. The bot submits orders at actual executable order-book prices below that ceiling. `1.0000` includes every valid YES ask without submitting an invalid $1.00 order.

`spend_up_to_dollars` caps contract purchase cost. Kalshi fees are reported separately and can make the total account debit slightly higher than this value.

## Commands

Normal buy commands are set in `config/active.json`.

```json
"A": {
  "label": "Team A spread",
  "action": "buy",
  "market_ticker": "EXACT_KALSHI_MARKET_TICKER",
  "side": "yes",
  "spend_up_to_dollars": 500,
  "enabled": true
}
```

Special commands:

```text
M = sell current Kalshi YES position for last bought market
K = kill switch and cancel known open orders
```

## Tests

```bash
pip install -r requirements-dev.txt
pytest -q
```

## Legal and platform note

Use only official Kalshi APIs.

Do not use this from a restricted jurisdiction.

Follow Kalshi's API agreement, trading rules, and market rules.
