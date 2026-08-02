# iPhone to AWS VPS Connection

The recommended setup is Tailscale on the existing AWS VPS and the Tailscale iOS
app. The bot port stays off the public internet, while iSH connects directly to the
VPS's private Tailscale IP with very little setup.

## VPS

SSH to the VPS and install Tailscale using the
[official AWS instructions](https://tailscale.com/docs/install/cloud/aws/quickstart).
After
authentication, obtain the private address:

```bash
tailscale ip -4
```

Put that exact address in `.env`:

```text
WS_HOST=100.x.y.z
WS_PORT=8765
```

Keep TCP port 8765 closed to the public internet in the AWS security group. The
existing SSH port can remain configured as it is now.

## iPhone and iSH

1. Install and sign into the Tailscale iOS app using the same tailnet by following
   the [official iOS instructions](https://tailscale.com/docs/install/ios).
2. Enable Tailscale on the phone.
3. In iSH, install Python and the one phone-side dependency:

```sh
apk add python3 py3-pip
python3 -m pip install websockets
```

4. Run `iphone/iphone_sender.py` and enter:

```text
WebSocket URL: ws://100.x.y.z:8765
Control token: the CONTROL_TOKEN from the VPS
```

The sender authenticates before the server exposes the event profile. Incoming
results print in the background, so `K` or `/block A` can be sent while a sweep is
still active.

Use `/mode paper`, `/mode test`, or `/mode live` to change the current event
session's mode from the phone. The override persists across reconnects and server
restarts. Use `/mode config` to return to the mode in the active config file.
