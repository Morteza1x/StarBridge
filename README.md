# StarBridge

StarBridge is a personal tunnel toolkit for routing traffic through your home connection.

- `relay`: relay server (VPS/internal server)
- `home-agent`: runs on home Windows
- `socks-client`: local SOCKS5 endpoint for client-side apps
- `StarBridgeHomeAgent` GUI: all-in-one app (start/stop, config generator, list/copy URI, network checks)

## Why This Project

For restricted-network scenarios (for example: mobile network only reaches internal/domestic routes), StarBridge lets you split paths:

- relay path via one interface (e.g. SIM/internal route)
- outbound internet via another interface (e.g. Starlink/home WAN)

## Repository Files

- `starbridge.py` - core protocol + CLI
- `starbridge_gui.py` - main GUI app
- `starbridge_config_gui.py` - standalone config-generator GUI

## Features

- Custom relay token authentication
- SOCKS5 CONNECT support
- Multi-profile config generator (`generate-configs`)
- Bind source interface for relay and egress:
  - `--relay-bind-host`
  - `--egress-bind-host`
- Dark-theme GUI
- Network diagnostics panel in GUI:
  - Active adapters list
  - Default route table
  - Relay path test
  - Egress path test

## Requirements

- Python 3.10+
- Windows for GUI builds

## Quick Start (CLI)

1. Start relay:

```powershell
py starbridge.py relay --host 0.0.0.0 --port 9443 --token "YOUR_TOKEN"
```

2. Start home agent:

```powershell
py starbridge.py home-agent --relay-host "YOUR_RELAY_HOST" --relay-port 9443 --token "YOUR_TOKEN" --no-tls
```

3. Start local SOCKS client:

```powershell
py starbridge.py socks-client --relay-host "YOUR_RELAY_HOST" --relay-port 9443 --token "YOUR_TOKEN" --listen-host 127.0.0.1 --listen-port 1080 --no-tls
```

Then set your app/browser proxy to `SOCKS5 127.0.0.1:1080`.

## Dual-Link Example (SIM + Starlink)

```powershell
py starbridge.py home-agent `
  --relay-host "INTERNAL_RELAY_IP" `
  --relay-port 9443 `
  --token "YOUR_TOKEN" `
  --relay-bind-host "SIM_LOCAL_IP" `
  --egress-bind-host "STARLINK_LOCAL_IP" `
  --no-tls
```

## Generate 20 Configs

```powershell
py starbridge.py generate-configs --relay-host "relay.example.ir" --count 20 --no-tls --output-dir generated-configs
```

Outputs:

- `generated-configs/profiles.json`
- `generated-configs/sb-01.json` ... `sb-20.json`

## EXE Usage

From `dist/`:

- `StarBridgeHomeAgent_dark.exe` (recommended)
- `StarBridgeHomeAgent_v2.exe`
- `StarBridgeHomeAgent.exe`
- `StarBridgeCli.exe`
- `StarBridgeConfigTool.exe`

Run:

```powershell
.\dist\StarBridgeHomeAgent_dark.exe
```

## Local End-to-End Test Status

Core tunnel path (`relay + home-agent + socks-client`) has been validated locally in this workspace.

## Security Notes

- `--no-tls` is only for initial testing.
- For real deployment, enable TLS on relay (`--certfile`, `--keyfile`) and client CA validation.
- Do not publish real tokens in public repos.

## Legal / Compliance

You are responsible for local laws, provider policy, and workplace policy.

## Persian Summary (خلاصه فارسی)

- این پروژه یک تونل شخصی است تا ترافیک از مسیر خانه عبور کند.
- برنامه‌ی GUI اصلی (`StarBridgeHomeAgent_dark.exe`) هم‌زمان:
  - Agent را Start/Stop می‌کند
  - کانفیگ می‌سازد
  - لیست کانفیگ می‌دهد و URI کپی می‌کند
  - وضعیت کارت‌های شبکه و تست مسیر را نشان می‌دهد
- برای استفاده واقعی، TLS را فعال کنید.
