# Kalshi Command Bot

A slim command execution system for sending short iPhone Python commands to a VPS, then placing Kalshi orders from the VPS.

This project is intentionally small.

It uses:

- iPhone Python script as the controller
- WebSocket from iPhone to VPS
- Kalshi API on the VPS only
- One active config file
- Paper mode
- Test mode
- Live mode
- `M` to sell the current Kalshi YES position for the last bought market
- `K` as a kill switch that cancels known open orders

It does not include:

- Web page
- Dashboard
- Database
- Position tracker
- Saved trade history
- Multi-exchange support
- Automatic retries
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
Order submitted
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
  .env.example
  requirements.txt
```

## Important Kalshi API notes

Kalshi uses separate production and demo API hosts. Production REST uses `https://external-api.kalshi.com/trade-api/v2`. Demo REST uses `https://external-api.demo.kalshi.co/trade-api/v2`.

Authenticated requests require:

- `KALSHI-ACCESS-KEY`
- `KALSHI-ACCESS-TIMESTAMP`
- `KALSHI-ACCESS-SIGNATURE`

The signature is created from `timestamp + HTTP_METHOD + path`, signed with RSA-PSS and SHA256.

This project uses the V2 event-market order endpoint:

```text
POST /portfolio/events/orders
```

It also uses:

```text
GET /portfolio/positions
DELETE /portfolio/events/orders/{order_id}
```

## Safety model

The iPhone never stores Kalshi credentials.

Only the VPS stores:

- Kalshi API key ID
- Kalshi private key path
- WebSocket control token

The iPhone only sends commands like:

```text
A
S
1
M
K
```

## Install on VPS

Clone the repo on the VPS.

```bash
git clone <your-repo-url>
cd kalshi-command-bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
cp config/active.example.json config/active.json
```

Edit `.env`.

```bash
nano .env
```

Edit `config/active.json`.

```bash
nano config/active.json
```

Validate config.

```bash
python scripts/validate_config.py
```

Run server.

```bash
python -m server.server
```

## Run on iPhone

Use an iPhone Python app that can install or include the `websockets` package.

Set these values inside `iphone/iphone_sender.py`, or enter them when prompted:

```text
wss://YOUR_VPS_DOMAIN_OR_IP:8765
CONTROL_TOKEN
```

Run the script.

Type commands.

```text
A
M
K
```

The first version uses Enter after each command.

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

### Paper mode

No Kalshi order is placed.

The server prints what would happen.

### Test mode

Every buy command places exactly one contract.

`M` sells up to one contract from the current Kalshi YES position for the last bought market.

### Live mode

Buy commands use `spend_up_to_dollars`.

`M` sells the full current Kalshi YES position for the last bought market.

## Commands

Commands live in `config/active.json`.

Example:

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

```json
"M": {
  "label": "Sell current Kalshi position for last bought market",
  "action": "sell_last_market_position",
  "enabled": true
}
```

```json
"K": {
  "label": "Kill switch",
  "action": "kill_switch",
  "enabled": true
}
```

## Order behavior

This project uses aggressive immediate-or-cancel orders.

Default buy price:

```text
0.9900
```

Default sell price:

```text
0.0100
```

These are not strategy settings. They are aggressive limit prices used to make the order marketable while still using Kalshi's limit order API shape.

You can override them in config:

```json
"aggressive_buy_price": "0.9900",
"aggressive_sell_price": "0.0100"
```

## No automatic retries

Failed orders are not retried.

Reason:

A retry can arrive late and place an unwanted order.

## Creating your GitHub repo

This folder is ready to push.

Option 1, GitHub CLI:

```bash
git init
git add .
git commit -m "Initial Kalshi command bot"
gh repo create kalshi-command-bot --private --source=. --remote=origin --push
```

Option 2, GitHub website:

1. Create a private empty repo on GitHub.
2. Copy the repo URL.
3. Run:

```bash
git init
git add .
git commit -m "Initial Kalshi command bot"
git remote add origin <your-repo-url>
git branch -M main
git push -u origin main
```

## Legal and platform note

Use only official Kalshi APIs.

Do not use this from a restricted jurisdiction.

Follow Kalshi's API agreement, trading rules, and market rules.
