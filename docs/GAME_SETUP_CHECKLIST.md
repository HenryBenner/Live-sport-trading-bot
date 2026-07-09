# Game Setup Checklist

## Before event

1. Find exact Kalshi market tickers.
2. Copy `config/active.example.json` to `config/active.json`.
3. Paste market tickers.
4. Set command keys.
5. Set dollar amounts.
6. Set mode to `paper`.
7. Restart VPS server.
8. Run iPhone sender.
9. Test every command.

## Test mode

1. Set mode to `test`.
2. Restart VPS server.
3. Run iPhone sender.
4. Press one buy key.
5. Press M.
6. Press K if needed.

## Live mode

1. Set mode to `live`.
2. Restart VPS server.
3. Confirm profile name and event name.
4. Confirm commands.
5. Use single-character commands only.

## After event

1. Stop server.
2. Replace `active.json` before the next event.
3. Never reuse old config without checking every ticker.
