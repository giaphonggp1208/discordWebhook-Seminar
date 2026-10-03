# Cấu hình Discord thật

## 1. Server và Incoming Webhooks

1. Dùng một server thử nghiệm; bạn cần quyền quản lý channel và `Manage Webhooks` để tạo webhook.
2. Tạo text channels `deployments`, `alerts`, `activity`, `leave-approvals`.
3. Với ba channel thông báo: Edit Channel → Integrations → Webhooks → New Webhook. Copy URL tương ứng vào `.env`.
4. Không chụp hoặc chiếu URL đầy đủ. Ai có webhook URL có thể dùng token trong URL để thao tác trên webhook.
5. `leave-approvals` là channel riêng; chỉ manager demo, người trình bày và bot được xem. Tắt View Channel của `@everyone` theo nhu cầu demo.

## 2. Discord Application và bot

1. Mở [Developer Portal](https://discord.com/developers/applications), tạo application.
2. General Information: copy Application ID và Public Key vào `.env`.
3. Bot: tạo/reset bot token theo giao diện Portal, lưu riêng vào `DISCORD_BOT_TOKEN`.
4. Installation/Guild Install: tạo install link có scope `bot`; cấp quyền **View Channels, Send Messages** cho bot trong `leave-approvals`. Thêm **Embed Links** nếu bạn mở rộng message thành embed. Không cấp Administrator.
5. Cài application vào server thử nghiệm. Không cần bật Message Content Intent; demo không đọc tin nhắn và không duy trì Gateway.
6. Bật Developer Mode trong Discord → Advanced. Copy server ID, channel ID `leave-approvals`, user ID manager. Điền `DISCORD_GUILD_ID`, `DISCORD_APPROVAL_CHANNEL_ID`, `DISCORD_MANAGER_ID`.
7. Demo không yêu cầu đăng nhập web. Chỉ dùng server/channel thử nghiệm vì URL ngrok sẽ công khai ứng dụng local trong lúc chạy.

## 3. Endpoint nhận callback

1. Cài [ngrok cho Windows](https://ngrok.com/download/windows/), tạo tài khoản miễn phí và chạy `ngrok config add-authtoken "<YOUR_AUTHTOKEN>"` một lần.
2. Copy assigned development domain trong ngrok Dashboard vào `.env`: `NGROK_DOMAIN=example.ngrok-free.app`.
3. Chạy app và xác nhận `http://localhost:8080/health` trả `{"status":"UP"}`.
4. Mở terminal khác và chạy `.\scripts\run-ngrok.ps1` để chuyển tiếp HTTPS tới `http://localhost:8080`.
5. Trong General Information → Interactions Endpoint URL, điền `https://<NGROK_DOMAIN>/discord/interactions`.
6. Discord gửi PING đã ký. Ứng dụng xác minh public key và trả `200 {"type":1}`. Sau khi Discord xác thực, lưu endpoint.

Ngrok chuyển tiếp toàn bộ app, dù chỉ route `/discord/interactions` cần public cho nghiệp vụ. Web/API được mở để demo nhanh, vì vậy chỉ bật ngrok trong lúc thử nghiệm và không dùng dữ liệu thật. Public key và ngrok domain không phải secret; authtoken ngrok, bot token và webhook URL là secret.

## 4. Chạy một vòng đầy đủ

- Tạo đơn trên web → chờ message có hai nút xuất hiện.
- Đăng nhập Discord bằng đúng manager ID → bấm Approve.
- Web hiển thị `APPROVED`; message có trạng thái mới và hai nút disabled.
- Tạo đơn thứ hai → Reject → `REJECTED`.
- Channel activity hiển thị các sự kiện; database giữ actor/time chính thức.

Nếu mở Discord bằng tài khoản khác manager, callback được xác thực nguồn nhưng ứng dụng vẫn từ chối quyền nghiệp vụ. Đây là hành vi cần trình bày.

## 5. Troubleshooting

| Hiện tượng | Kiểm tra |
|---|---|
| Portal không lưu endpoint | FastAPI và ngrok có cùng đang chạy? URL có kết thúc bằng `/discord/interactions`? Public Key có đúng application? |
| Chữ ký trả 401 | Key có đúng application? body có bị parse/serialize trước verify? đồng hồ máy có lệch quá 5 phút? |
| `NOT_CONFIGURED` | Biến môi trường thực sự tới process FastAPI chưa? |
| Bot không gửi được | Bot token, channel ID, bot đã install, quyền View/Send trong private channel |
| “Bạn không có quyền” | Application/server/channel/user ID trong `.env` có khớp sự kiện? |
| “Tin nhắn không khớp” | Callback từ message cũ/trùng; xem message đang gắn với đơn |
| Web không cập nhật | API/worker đang chạy? bấm Làm mới; xem delivery và activity |
| `HTTP_401` / `HTTP_404` | Token bị thu hồi hoặc channel/webhook/message đã bị xóa |
| `RATE_LIMIT_DEFERRED` | Chờ theo Discord, kiểm tra channel trước khi retry thủ công |
| App khỏe nhưng script exit 2 | Triển khai thành công; riêng thông báo deployment thất bại |

Nguồn: [Webhook Resource](https://docs.discord.com/developers/resources/webhook), [Interactions Overview](https://docs.discord.com/developers/interactions/overview), [Message Resource](https://docs.discord.com/developers/resources/message).
