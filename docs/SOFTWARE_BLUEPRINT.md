# Kalshi Command Bot Blueprint

## Components

```text
iSH input and background receiver
  -> authenticated private WebSocket
  -> concurrent control router on the VPS
  -> serialized order worker
  -> Kalshi REST API
```

Trade execution runs in a worker thread so the WebSocket loop can process `K` and
`/block` while a sweep is active. Only one buy or sell worker may execute at once.

## Persistent event session

`config/runtime_state.json` stores:

- session and event identifiers;
- blocked buy keys;
- persistent kill-switch state;
- per-press, per-market, and event limit overrides;
- confirmed all-in event and per-market spending.

The state survives phone reconnects and process restarts. A new event ticker starts
a new session. `logs/commands.jsonl` contains append-only command and result records.

## Cost limits

- Per press: `spend_up_to_dollars` in the event config, overridable with a command.
- Per market: `.env` default applied separately to each buy key, overridable per key.
- Per event: `.env` default shared by all buy keys, overridable for the session.

Blank `.env` market and event limits are infinite. Confirmed contract cost and
reported Kalshi fees count against both persistent totals. A configurable reserve
reduces the submitted contract budget before the order is sent.

## Kill behavior

`K` first persists the kill state and sets cancellation events for every active
sweep. It then asks Kalshi for all resting orders on the configured subaccount and
cancels them, waits for the serialized worker to stop, and repeats the query and
cancellation. New trades remain rejected until `/reset kill`.

## Event replacement

An external AI setup agent produces deterministic JSON using exact supplied Kalshi
tickers, URLs, and proposition text. `scripts/activate_config.py` validates the whole
candidate and atomically replaces `config/active.json`. The service is restarted to
load the file.
