from __future__ import annotations

import asyncio
import json
import re
import threading
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator

from discord_integration import DiscordClient, SignatureVerifier, NotificationMessage

from .config import Settings
from .database import create_database, initialize_database
from .security import issue_csrf, require_csrf
from .store import LeaveStore, NotFoundError
from .worker import DeliveryWorker

CUSTOM_ID = re.compile(r"^leave:(LR-[A-Za-z0-9-]{1,40}):(approve|reject)$")
NUMERIC_ID = re.compile(r"^[0-9]+$")
INTERACTION_TOKEN = re.compile(r"^[A-Za-z0-9._-]{1,500}$")


class CreateLeave(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    from_date: date = Field(alias="fromDate")
    to_date: date = Field(alias="toDate")
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("reason")
    @classmethod
    def reason_is_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("reason must not be blank")
        return value


# Models cho Lab Webhook
WEBHOOK_PATH = re.compile(r"^/api(?:/v\d+)?/webhooks/\d+/[^/]+/?$")


class LabWebhookRequest(BaseModel):
    webhookUrl: str = Field(description="Discord Incoming Webhook URL")
    content: str = Field(default="", max_length=1000, description="Message content (optional)")
    title: str = Field(default="", max_length=256, description="Embed title (optional)")
    description: str = Field(default="", max_length=2000, description="Embed description (optional)")
    fields: dict[str, str] = Field(
        default_factory=dict,
        description="Key-value pairs for embed fields (optional)",
    )

    @field_validator("webhookUrl")
    @classmethod
    def validate_webhook_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "discord.com"
            or parsed.port not in (None, 443)
            or parsed.fragment
            or not WEBHOOK_PATH.fullmatch(parsed.path)
        ):
            raise ValueError("Phải dùng URL Incoming Webhook HTTPS hợp lệ của discord.com")
        return value


class LabWebhookResponse(BaseModel):
    success: bool
    httpStatus: int
    messageId: str | None = None


def create_app(*, settings: Settings | None = None, discord: DiscordClient | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    engine = create_database(settings.database_url)
    store = LeaveStore(engine)
    discord = discord or DiscordClient(
        {
            "deployments": settings.discord_webhook_deployments,
            "alerts": settings.discord_webhook_alerts,
            "activity": settings.discord_webhook_activity,
        },
        settings.discord_bot_token,
        api_base=settings.discord_api_base,
    )
    worker = DeliveryWorker(store, discord, settings)
    verifier = SignatureVerifier(settings.discord_public_key) if settings.discord_public_key else None
    interaction_capacity = threading.BoundedSemaphore(64)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        initialize_database(engine)
        store.recover_interrupted()
        stop = asyncio.Event()

        async def run_worker() -> None:
            while not stop.is_set():
                await asyncio.to_thread(worker.tick)
                try:
                    await asyncio.wait_for(stop.wait(), timeout=0.5)
                except asyncio.TimeoutError:
                    pass

        task = asyncio.create_task(run_worker()) if settings.worker_enabled else None
        try:
            yield
        finally:
            stop.set()
            if task:
                await task
            discord.close()
            engine.dispose()

    app = FastAPI(title="Leave Demo", version=settings.app_version, lifespan=lifespan)
    app.state.settings = settings
    app.state.store = store
    app.state.worker = worker
    app.state.discord = discord

    def csrf(request: Request) -> None:
        require_csrf(request)

    @app.exception_handler(NotFoundError)
    async def not_found(_request: Request, _exc: NotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"error": "Không tìm thấy đơn."})

    @app.exception_handler(HTTPException)
    async def api_error(_request: Request, exc: HTTPException) -> JSONResponse:
        if isinstance(exc.detail, str):
            return JSONResponse(status_code=exc.status_code, content={"error": exc.detail}, headers=exc.headers)
        return JSONResponse(status_code=exc.status_code, content={"error": "Request rejected"}, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def invalid_input(_request: Request, _exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"error": "Kiểm tra ngày nghỉ, lý do (1-500 ký tự) và JSON đầu vào."})

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "UP"}

    @app.get("/api/csrf")
    def get_csrf(response: Response) -> dict[str, str]:
        return issue_csrf(response)

    @app.get("/api/config")
    def config() -> dict[str, str | bool]:
        return {"discordConfigured": settings.discord_configured, "employee": "Nhân viên mẫu"}

    @app.get("/api/leave-requests")
    def list_requests() -> list[dict[str, str | None]]:
        return [request.api() for request in store.list_requests()]

    @app.get("/api/leave-requests/{request_id}")
    def get_request(request_id: str) -> dict[str, str | None]:
        return store.get(request_id).api()

    @app.post("/api/leave-requests", status_code=201)
    def create_request(input: CreateLeave, response: Response, _csrf: None = Depends(csrf)) -> dict[str, str | None]:
        if input.to_date <= input.from_date:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ngày kết thúc phải sau ngày bắt đầu.")
        request = store.create(input.from_date, input.to_date, input.reason)
        response.headers["Location"] = f"/api/leave-requests/{request.id}"
        return request.api()

    @app.get("/api/activity")
    def activity() -> list[dict[str, str | None]]:
        return store.activities()

    @app.get("/api/deliveries")
    def list_deliveries() -> list[dict[str, str | int | None]]:
        return [delivery.api() for delivery in store.deliveries()]

    @app.post("/api/deliveries/{delivery_id}/retry", status_code=202)
    def retry_delivery(delivery_id: str, _csrf: None = Depends(csrf)) -> dict[str, str]:
        if not store.retry(delivery_id):
            raise HTTPException(status.HTTP_409_CONFLICT, "Chỉ gửi lại thông báo FAILED.")
        return {"status": "PENDING"}

    @app.post("/api/demo/alert")
    def demo_alert(_csrf: None = Depends(csrf)) -> JSONResponse:
        correlation_id = str(uuid4())
        store.enqueue("ALERT", correlation_id)
        return JSONResponse(status_code=500, content={
            "error": "DEMO_FAILURE",
            "correlationId": correlation_id,
            "message": "Lỗi có kiểm soát; cảnh báo đã được đưa vào hàng gửi.",
        })

    # === Lab Endpoints ===

    @app.post("/api/lab/webhook", response_model=LabWebhookResponse)
    async def lab_webhook(request: LabWebhookRequest) -> LabWebhookResponse:
        """Gửi notification trực tiếp đến webhook URL (không qua queue)."""
        payload: dict = {"allowed_mentions": {"parse": []}}
        if request.content:
            payload["content"] = request.content
        # Chỉ thêm embed nếu có title, description hoặc fields
        if request.title or request.description or request.fields:
            embed: dict = {}
            if request.title:
                embed["title"] = request.title
            if request.description:
                embed["description"] = request.description
            if request.fields:
                embed["fields"] = [
                    {"name": k, "value": v, "inline": True}
                    for k, v in request.fields.items()
                ]
            payload["embeds"] = [embed]
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
                response = await client.post(
                    request.webhookUrl,
                    params={"wait": "true"},
                    json=payload,
                )
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="Discord phản hồi quá thời gian")
        except httpx.HTTPError:
            raise HTTPException(status_code=502, detail="Không thể kết nối tới Discord")
        if not response.is_success:
            raise HTTPException(status_code=502, detail=f"Discord từ chối request (HTTP {response.status_code})")
        try:
            message_id = response.json().get("id")
        except (TypeError, ValueError):
            message_id = None
        return LabWebhookResponse(success=True, httpStatus=response.status_code, messageId=message_id)

    @app.post("/api/demo/notify/{kind}")
    def demo_notify(kind: str, _csrf: None = Depends(csrf)) -> dict:
        """Gửi notification qua queue sử dụng webhook từ .env."""
        if kind not in {"deployment", "alert", "activity"}:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Chỉ hỗ trợ: deployment, alert, activity")
        correlation_id = str(uuid4())
        if kind == "alert":
            store.enqueue("ALERT", correlation_id)
        elif kind == "deployment":
            store.enqueue("DEPLOYMENT", correlation_id)
        else:
            store.enqueue("ACTIVITY_DEMO", correlation_id)
        return {"status": "queued", "kind": kind, "correlationId": correlation_id}

    def immediate(message: str) -> JSONResponse:
        return JSONResponse({"type": 4, "data": {"content": message, "flags": 64}})

    def process_interaction(request_id: str, action: str, message_id: str, interaction_id: str, token: str) -> None:
        try:
            try:
                result = store.decide(request_id, action, settings.discord_manager_id, message_id, interaction_id)
            except NotFoundError:
                result = "Không tìm thấy đơn."
            except Exception:
                result = "Chưa xử lý được. Vui lòng kiểm tra trạng thái đơn và thử lại."
            # This result is deliberately the only payload used after the ACK; never expose tokens or raw bodies.
            discord.finish_interaction(settings.discord_application_id, token, result)
        finally:
            interaction_capacity.release()

    @app.post("/discord/interactions")
    async def discord_interactions(request: Request, background_tasks: BackgroundTasks) -> JSONResponse:
        raw_body = await request.body()
        if verifier is None:
            return JSONResponse(status_code=503, content={"error": "Discord is not configured"})
        if not verifier.verify(request.headers.get("X-Signature-Ed25519"), request.headers.get("X-Signature-Timestamp"), raw_body):
            return JSONResponse(status_code=401, content={"error": "Invalid signature"})
        try:
            event = json.loads(raw_body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return JSONResponse(status_code=400, content={"error": "Invalid JSON"})
        if not isinstance(event, dict):
            return JSONResponse(status_code=400, content={"error": "Invalid JSON"})
        if event.get("type") == 1:
            return JSONResponse({"type": 1})
        if event.get("type") != 3:
            return immediate("Loại tương tác chưa được hỗ trợ.")
        member = event.get("member") if isinstance(event.get("member"), dict) else {}
        user = member.get("user") if isinstance(member.get("user"), dict) else {}
        if (
            not settings.discord_configured
            or event.get("application_id") != settings.discord_application_id
            or event.get("guild_id") != settings.discord_guild_id
            or event.get("channel_id") != settings.discord_approval_channel_id
            or user.get("id") != settings.discord_manager_id
        ):
            return immediate("Bạn không có quyền duyệt đơn tại đây.")
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        message = event.get("message") if isinstance(event.get("message"), dict) else {}
        match = CUSTOM_ID.fullmatch(str(data.get("custom_id", "")))
        interaction_id, message_id, token = str(event.get("id", "")), str(message.get("id", "")), str(event.get("token", ""))
        if not match or not NUMERIC_ID.fullmatch(interaction_id) or not NUMERIC_ID.fullmatch(message_id) or not INTERACTION_TOKEN.fullmatch(token):
            return immediate("Dữ liệu thao tác không hợp lệ.")
        if not interaction_capacity.acquire(blocking=False):
            return immediate("Ứng dụng đang bận. Vui lòng thử lại.")
        background_tasks.add_task(process_interaction, match.group(1), match.group(2), message_id, interaction_id, token)
        return JSONResponse({"type": 5, "data": {"flags": 64}})

    static_dir = Path(__file__).resolve().parent / "static"
    if static_dir.is_dir():
        @app.get("/", include_in_schema=False)
        @app.get("/index.html", include_in_schema=False)
        def index() -> FileResponse:
            return FileResponse(static_dir / "index.html", headers={"Cache-Control": "no-store"})

        app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
    return app


app = create_app()
