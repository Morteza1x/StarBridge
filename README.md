# StarBridge

StarBridge یک ابزار تونل شخصی است برای زمانی که می‌خواهید ترافیک از مسیر خانه عبور کند.

معماری پروژه:

`Client -> Relay -> Home Agent -> Internet`

## این پروژه به چه درد می‌خورد؟

- ساخت مسیر خروجی شخصی از طریق سیستم خانه
- استفاده از مسیر دوگانه شبکه:
  - مسیر اتصال به Relay از یک کارت شبکه (مثلا سیم‌کارت داخلی)
  - مسیر خروجی اینترنت از کارت شبکه دیگر (مثلا Starlink)

## فایل‌های مهم پروژه

- `starbridge.py` هسته پروژه و CLI
- `starbridge_gui.py` رابط گرافیکی اصلی
- `dist/StarBridge.exe` برنامه اصلی برای کاربر
- `dist/StarBridgeCli.exe` ابزار خط فرمان

## شروع سریع برای کاربر (فقط GUI)

1. برنامه را اجرا کنید:

```powershell
.\dist\StarBridge.exe
```

2. در بخش `Home Agent` این‌ها را پر کنید:
- `Relay Host` آی‌پی یا دامنه سرور Relay
- `Relay Port` پورت Relay (معمولا `9443`)
- `Token` رمز مشترک بین Relay و Agent/Client

3. اگر تست اولیه است:
- `Disable TLS` را روشن کنید

4. روی `Start Agent` بزنید.

5. در بخش `Network Status` روی `Test Paths` بزنید تا مسیرها بررسی شوند.

## توضیح کامل فیلدها و دکمه‌های GUI

### بخش Home Agent

- `Relay Host`: آدرس سروری که حالت `relay` روی آن اجرا شده
- `Relay Port`: پورت اتصال Relay
- `Token`: رمز مشترک امنیتی
- `Retry (sec)`: فاصله تلاش مجدد بعد از قطع اتصال
- `CA File`: مسیر فایل CA برای TLS
- `Disable TLS`: خاموش کردن TLS (فقط تست)
- `Verbose logs`: نمایش لاگ‌های کامل‌تر
- `Relay Bind IP`: آی‌پی محلی کارت شبکه‌ای که اتصال به Relay از آن انجام شود
- `Egress Bind IP`: آی‌پی محلی کارت شبکه‌ای که خروجی اینترنت از آن انجام شود

دکمه‌ها:

- `Start Agent`: شروع Home Agent
- `Stop Agent`: توقف Home Agent
- `Add Active Config To List`: با Start شدن Agent، کانفیگ فعال را وارد لیست می‌کند

### بخش Network Status

دکمه‌ها:

- `Refresh Adapters`: لیست کارت‌های شبکه فعال و Route را به‌روز می‌کند
- `Test Paths`: مسیر Relay و مسیر خروجی اینترنت را تست می‌کند

خروجی این بخش به شما نشان می‌دهد:

- آداپتورهای فعال IPv4
- Default Route
- نتیجه تست مسیر Relay و Egress

### بخش Config Generator

فیلدها:

- `Count`: تعداد کانفیگ
- `Start Port`: شروع بازه پورت
- `Prefix`: پیشوند نام کانفیگ‌ها (مثل `sb-01`)
- `Token Bytes`: طول توکن تصادفی
- `Output Dir`: پوشه خروجی
- `Listen Host`: آدرس لوکال SOCKS
- `Listen Port`: پورت لوکال SOCKS

دکمه‌ها:

- `Generate Configs`: تولید فایل‌های کانفیگ
- `Clear List`: پاک کردن لیست نمایش
- `Copy Selected URI`: کپی URI کانفیگ انتخابی

## خروجی تولید کانفیگ

پس از `Generate Configs`:

- `generated-configs/profiles.json`
- `generated-configs/sb-01.json` ... `sb-20.json`

## راه‌اندازی Relay روی VPS داخلی (Ubuntu)

```bash
apt update
apt install -y python3 curl ufw
mkdir -p /opt/starbridge
cd /opt/starbridge
curl -L -o starbridge.py https://raw.githubusercontent.com/Morteza1x/StarBridge/main/starbridge.py
python3 /opt/starbridge/starbridge.py relay --host 0.0.0.0 --port 9443 --token "YOUR_TOKEN"
```

باز کردن پورت:

```bash
ufw allow 9443/tcp
ufw --force enable
```

## دستورات CLI

### Relay

```powershell
py starbridge.py relay --host 0.0.0.0 --port 9443 --token "YOUR_TOKEN"
```

### Home Agent

```powershell
py starbridge.py home-agent --relay-host "YOUR_RELAY_HOST" --relay-port 9443 --token "YOUR_TOKEN" --no-tls
```

### Socks Client

```powershell
py starbridge.py socks-client --relay-host "YOUR_RELAY_HOST" --relay-port 9443 --token "YOUR_TOKEN" --listen-host 127.0.0.1 --listen-port 1080 --no-tls
```

### Generate Configs

```powershell
py starbridge.py generate-configs --relay-host "relay.example.ir" --count 20 --no-tls --output-dir generated-configs
```

## خطاهای رایج

- `اتصال برقرار نمی‌شود`: اول `Relay Host/Port/Token` را چک کنید
- `Path FAIL`: آی‌پی‌های `Relay Bind IP` و `Egress Bind IP` اشتباه یا غیرقابل دسترس هستند
- اتصال ناپایدار: `Retry` را افزایش دهید و کیفیت مسیر شبکه را بررسی کنید

## نکات امنیتی

- `--no-tls` فقط برای تست اولیه است
- برای استفاده واقعی TLS را فعال کنید (`--certfile`, `--keyfile`, `CA File`)
- توکن واقعی را عمومی منتشر نکنید

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










## Donate

- ERC20: `0x014b7603D81869Cb95200E3a5274d00ac4d0d765`

## Telegram

- https://t.me/StarBridgex
