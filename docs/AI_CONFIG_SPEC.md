# AI Event Config Contract

Give this file, `config/active.example.json`, and the Kalshi match details to the
agent that prepares an event. The agent must map supplied data; it must not pick
markets, invent lines, or choose strategy.

## Required output

Return one JSON object with:

- `profile_name`: short operator-facing name.
- `sport`: supplied sport name.
- `event_name`: exact match name.
- `event_ticker`: exact Kalshi event ticker.
- `event_url`: Kalshi URL containing that event ticker.
- `mode`: always `paper` for a newly generated file.
- retry and aggressive-price settings copied from `active.example.json` unless
  the operator supplies replacements.
- `commands`: the supplied hotkey mappings.

Every buy command must contain:

- one-character key;
- exact operator-facing label;
- `action: "buy"`;
- exact `market_ticker`;
- `market_url` containing that exact ticker;
- exact `line_or_prop` wording supplied for the match;
- `side: "yes"`;
- per-press all-in ceiling in `spend_up_to_dollars`;
- `enabled: true` or `false`.

The file must contain `K` with `action: "kill_switch"`. `M` may be retained for
selling the last market with a confirmed bot fill.

Do not include API keys, private-key paths, the control token, Kalshi environment,
event caps, or default per-market caps. Those belong in `.env` on the VPS.

## Activation

Upload the generated file to the VPS, then run from the repository:

```bash
python scripts/activate_config.py /path/to/generated-match.json
sudo systemctl restart kalshi-command-bot
```

The activation script validates the complete candidate before atomically replacing
`config/active.json`. A different `event_ticker` starts a fresh persistent event
session. Replacing the config for the same event preserves blocks, runtime limits,
kill state, and spending totals.
