# Match Setup Checklist

## Prepare and activate

1. Give the setup agent the exact Kalshi event, market endpoints, command mapping,
   lines or propositions, and per-press amounts.
2. Have it follow `docs/AI_CONFIG_SPEC.md` and return JSON only.
3. Upload the candidate JSON to the VPS.
4. Activate and restart:

```bash
python scripts/activate_config.py /path/to/generated-match.json
sudo systemctl restart kalshi-command-bot
```

5. Connect from iSH and run `/status`.

## Test and live

1. Start every new config in `paper` mode.
2. Exercise each enabled buy key and the runtime limit commands.
3. Change the config to `test`, reactivate it, and place the intended one-contract
   test.
4. Change the config to `live` only after the test result is confirmed.
5. Use `/disarm`, `/block`, and the cost limits for normal runtime control.
6. Use `K` for an emergency stop; use `/reset kill` only when trading may resume.

## After the event

1. Run `/disarm` or `K`.
2. Review `logs/commands.jsonl` and Kalshi positions.
3. Generate and activate a new config for the next event. A new event ticker starts
   a new persistent session automatically.
