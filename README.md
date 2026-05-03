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

- `StarBridge.exe` (recommended main app)
- `StarBridgeCli.exe`
- `StarBridgeConfigTool.exe`

Run:

```powershell
.\dist\StarBridge.exe
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
- برنامه‌ی GUI اصلی (`StarBridge.exe`) هم‌زمان:
  - Agent را Start/Stop می‌کند
  - کانفیگ می‌سازد
  - لیست کانفیگ می‌دهد و URI کپی می‌کند
  - وضعیت کارت‌های شبکه و تست مسیر را نشان می‌دهد
- برای استفاده واقعی، TLS را فعال کنید.

YOUR_TOKEN یعنی یک رمز مشترک بین relay و کلاینت‌ها.

کارش:
- فقط دستگاه‌هایی که این توکن را دارند بتوانند وصل شوند.

مثال:
- توکن انتخاب کن: mihan-2026-sb-9Xk2!
- همین را دقیقا در هر سه جا بزن:
1. relay
2. home-agent
3. socks-client یا کانفیگ تولیدی

نکته:
- توکن باید قوی و تصادفی باشد.
- عمومی منتشرش نکن (داخل اسکرین‌شات/پست نگذار).




Relay Host یعنی آدرس سروری که relay روی آن اجرا شده.

می‌تونه یکی از اینا باشه:
- IP سرور: مثل 185.x.x.x
- دامنه سرور: مثل relay.yourdomain.com
- برای تست لوکال: 127.0.0.1

پس:
- اگر relay روی VPS داخلی نصب کردی، Relay Host = IP همان VPS.





Relay Host یعنی آدرس سروری که relay روی آن اجرا شده.

می‌تونه یکی از اینا باشه:
- IP سرور: مثل 185.x.x.x
- دامنه سرور: مثل relay.yourdomain.com
- برای تست لوکال: 127.0.0.1

پس:
- اگر relay روی VPS داخلی نصب کردی، Relay Host = IP همان VPS.







بله، روی VPS داخلی باید relay اجرا بشه.

حداقل چیزهایی که لازم داری:

Python 3.10+
فایل starbridge.py
باز بودن پورت (مثلا 9443) در فایروال
اجرای سریع:

python3 starbridge.py relay --host 0.0.0.0 --port 9443 --token "YOUR_TOKEN"
بعد در برنامه ویندوز:

Relay Host = IP همان VPS
Relay Port = 9443
Token = همان توکن بالا





عالی، این راه‌اندازی کامل relay روی Ubuntu VPS (کپی/پیست آماده):

1. وارد VPS شو:
ssh root@<VPS_IP>

2. پیش‌نیازها:
apt update
apt install -y python3 curl ufw

3. فایل starbridge.py را بگیر:
mkdir -p /opt/starbridge
cd /opt/starbridge
curl -L -o starbridge.py https://raw.githubusercontent.com/Morteza1x/StarBridge/main/starbridge.py

4. یک توکن قوی انتخاب کن (نمونه):
TOKEN='SB_2026_x9Kp!7mQ#A2'
PORT='9443'

5. تست دستی (موقت):
python3 /opt/starbridge/starbridge.py relay --host 0.0.0.0 --port "$PORT" --token "$TOKEN"
اگر بدون خطا بالا آمد، با Ctrl+C خارج شو.

6. سرویس دائمی بساز:
cat >/etc/systemd/system/starbridge-relay.service <<EOF
[Unit]
Description=StarBridge Relay
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/starbridge
ExecStart=/usr/bin/python3 /opt/starbridge/starbridge.py relay --host 0.0.0.0 --port 9443 --token ${TOKEN}
Restart=always
RestartSec=3
User=root

[Install]
WantedBy=multi-user.target
EOF

7. فعال‌سازی سرویس:
systemctl daemon-reload
systemctl enable --now starbridge-relay
systemctl status starbridge-relay --no-pager

8. باز کردن فایروال:
ufw allow 22/tcp
ufw allow 9443/tcp
ufw --force enable
ufw status

9. تست از ویندوز:
Test-NetConnection <VPS_IP> -Port 9443

10. در StarBridge.exe:
- Relay Host = <VPS_IP>
- Relay Port = 9443
- Token = همان TOKEN

نکته مهم: فعلا برای تست می‌تونی Disable TLS روشن باشد؛ برای استفاده واقعی بعدش TLS را فعال کن.





## Donate

- ERC20: `0x014b7603D81869Cb95200E3a5274d00ac4d0d765`

## Telegram

- https://t.me/StarBridgex
