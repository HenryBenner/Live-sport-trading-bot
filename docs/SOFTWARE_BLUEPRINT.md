# Slim Kalshi Python Command Trading Bot Blueprint

## Purpose

Build a small Kalshi command execution tool.

The iPhone runs a Python sender.

The VPS runs the trading server.

The phone sends commands only.

The VPS places Kalshi orders.

## Flow

```text
iPhone Python script
  ↓
WebSocket
  ↓
VPS server
  ↓
Kalshi API
```

## Runtime state

The server keeps only:

```text
active_config
kill_switch_active
last_market_ticker
last_label
open_order_ids
```

There is no database.

There is no local position tracker.

For M, the server asks Kalshi for the current YES position in the last bought market.

## Modes

```text
paper
test
live
```

Paper mode prints only.

Test mode places one contract.

Live mode uses spend_up_to_dollars.

## Commands

Normal buy commands are set in `config/active.json`.

Special commands:

```text
M = sell current Kalshi YES position for last bought market
K = kill switch and cancel known open orders
```

## Event reset

Before each event:

1. Replace `config/active.json`.
2. Set mode to paper.
3. Restart server.
4. Test commands.
5. Set mode to test.
6. Restart server.
7. Test one-contract order.
8. Set mode to live.
9. Restart server.
10. Use during the event.
