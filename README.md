# Discord Webhooks trong SOA

Demo seminar 45 phút: **deployment notifications, system alerts, activity logging** và **xin nghỉ phép hai chiều** với FastAPI.

## Mục tiêu

1. Hiểu 3 cách giao tiếp với Discord: Incoming Webhook, Bot REST API, Discord Interactions
2. Demo gửi notification đến Discord channels
3. Demo tạo đơn nghỉ phép và approve/reject trực tiếp từ Discord

## Cấu trúc source

```
discord_integration/   Package Python: HTTP client, DTO, Ed25519 signature, retry
leave_demo/            FastAPI: endpoints, database, worker, web UI
docs/                  Hướng dẫn cấu hình Discord
```

## Bắt đầu ở đâu?

### 1. Cài Python

Yêu cầu: Python 3.10+

```bash
# Kiểm tra Python
python --version
```

### 2. Cài ngrok

1. Tải từ https://ngrok.com/download
2. Giải nén vào `C:\tools\ngrok.exe`
3. Thêm vào PATH:

```powershell
[Environment]::SetEnvironmentVariable("PATH", $env:PATH + ";C:\tools", "User")
```

4. Đăng ký authtoken:

```bash
ngrok config add-authtoken YOUR_AUTHTOKEN
```

### 3. Cài đặt

```bash
cd D:/SOA-Final

# Tạo virtual environment
py -3 -m venv .venv

# Cài dependencies
.venv\Scripts\python.exe -m pip install -e .

# Copy và sửa .env
copy .env.example .env
# Điền các biến theo docs/discord-setup.md
```

### 4. Cấu hình Discord

Xem [docs/discord-setup.md](docs/discord-setup.md) để:
- Tạo Discord server và channels
- Tạo Incoming Webhooks
- Tạo Discord Application và Bot
- Cấu hình Interactions Endpoint

### 5. Chạy demo

#### Terminal 1: FastAPI server

```bash
.venv\Scripts\python.exe -m uvicorn leave_demo.main:app --host 127.0.0.1 --port 8080
```

#### Terminal 2: ngrok (để Discord callback)

```bash
ngrok http 8080 --url=https://YOUR-DOMAIN.ngrok-free.app
```

#### Mở giao diện

- **Swagger UI:** http://localhost:8080/docs
- **Web UI:** http://localhost:8080

## Demo trên Swagger UI

### Lab: Test Incoming Webhook riêng

**Endpoint:** `POST /api/lab/webhook`

Nhập webhook URL của bạn và gửi notification:

```json
{
  "webhookUrl": "https://discord.com/api/webhooks/YOUR/WEBHOOK_TOKEN",
  "content": "Test message",
  "title": "My Title",
  "description": "My description",
  "fields": {
    "Environment": "demo",
    "Version": "v1.0"
  }
}
```

### Demo: Notification có sẵn

**Endpoint:** `POST /api/demo/notify/{kind}`

```bash
# Deployment notification
POST /api/demo/notify/deployment

# Alert notification
POST /api/demo/notify/alert

# Activity notification
POST /api/demo/notify/activity
```

### Demo: Tạo đơn nghỉ phép

**Endpoint:** `POST /api/leave-requests`

```json
{
  "fromDate": "2026-10-01",
  "toDate": "2026-10-02",
  "reason": "Việc cá nhân"
}
```

## Các endpoints chính

| Endpoint | Mục đích |
|----------|-----------|
| `GET /health` | Kiểm tra server sống |
| `POST /api/lab/webhook` | Test webhook riêng |
| `POST /api/demo/notify/{kind}` | Demo notification |
| `POST /api/leave-requests` | Tạo đơn nghỉ phép |
| `GET /api/activity` | Xem log hoạt động |
| `GET /api/deliveries` | Xem delivery queue |
| `POST /discord/interactions` | Nhận callback từ Discord |

## Giới hạn

- Một instance, SQLite, một nhân viên và một manager mẫu
- Web không yêu cầu đăng nhập
- Notifications qua Incoming Webhook có thể bị trùng nếu timeout
- Callback Discord cần HTTPS (dùng ngrok)

## Nguồn

- [Discord Webhooks](https://docs.discord.com/developers/platform/webhooks)
- [Discord Interactions](https://docs.discord.com/developers/interactions/receiving-and-responding)
- [FastAPI](https://fastapi.tiangolo.com/)

---

**Không commit `.env`, database hoặc log.** Chia sẻ source và tài liệu; tự chọn nơi upload cho lớp.
