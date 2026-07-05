# Keep the sandbox alive across sessions (macOS launchd)

These LaunchAgents run the Tvist API (uvicorn on 127.0.0.1:8077) and a
cloudflared quick tunnel as user services with `KeepAlive` + `RunAtLoad`:
they survive terminal/agent session restarts, auto-restart on crash, and
come back after reboot.

Install (adjust absolute paths for your machine):

```bash
cp ai.tvist.*.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/ai.tvist.api.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/ai.tvist.tunnel.plist
```

Current public URL (quick tunnels get a new hostname only if cloudflared
itself restarts):

```bash
grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' ~/Library/Logs/tvist-tunnel.log | tail -1
```

Stop / remove:

```bash
launchctl bootout gui/$(id -u)/ai.tvist.api
launchctl bootout gui/$(id -u)/ai.tvist.tunnel
```

For a truly permanent URL, deploy to Railway / Render / Fly instead (see
../../README.md) — this launchd setup is the best possible *sandbox*
stability without a cloud account.
