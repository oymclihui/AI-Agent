"""Persistent WeCom bot connection. One process receives chat and can also send."""
from __future__ import annotations

import asyncio
import json
import os
import uuid
from typing import Any

import structlog
import websockets

from app.core.data_ask.credentials import decrypt_secret
from app.core.wecom.push import WS_URL, load_wecom_config
from app.db.session import AsyncSessionLocal

logger = structlog.get_logger(__name__)


class WecomLink:
    def __init__(self) -> None:
        self.status = "disconnected"
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._reconnect = asyncio.Event()
        self._ws: Any = None
        self._send_lock = asyncio.Lock()
        self._pending: dict[str, asyncio.Future] = {}

    def start(self) -> None:
        if os.getenv("RUN_WECOM_LINK", "1") == "0":
            self.status = "relay"
            return
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="wecom-link")

    def request_reconnect(self) -> None:
        self._reconnect.set()

    async def stop(self) -> None:
        self._stop.set()
        self._reconnect.set()
        ws = self._ws
        if ws is not None:
            try:
                await ws.close()
            except Exception:
                pass
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=5)
            except Exception:
                self._task.cancel()
        self.status = "disconnected"

    async def send_markdown(self, chat_ids: list[str], content: str) -> dict[str, Any]:
        sent: list[str] = []
        errors: list[dict[str, str]] = []
        for chat_id in chat_ids:
            ack = await self._request({
                "cmd": "aibot_send_msg",
                "headers": {"req_id": f"aibot_send_msg_{uuid.uuid4().hex}"},
                "body": {
                    "chatid": chat_id,
                    "msgtype": "markdown",
                    "markdown": {"content": content},
                },
            })
            if int(ack.get("errcode") or 0) != 0:
                errors.append({"chat_id": chat_id, "error": str(ack.get("errmsg") or "发送失败")[:200]})
            else:
                sent.append(chat_id)
        return {"ok": not errors and bool(sent), "sent": sent, "errors": errors}

    async def reply_stream(self, req_id: str, stream_id: str, content: str, *, finish: bool) -> None:
        await self._request({
            "cmd": "aibot_respond_msg",
            "headers": {"req_id": req_id},
            "body": {
                "msgtype": "stream",
                "stream": {"id": stream_id, "finish": finish, "content": content},
            },
        })

    async def reply_welcome(self, req_id: str, content: str) -> None:
        await self._request({
            "cmd": "aibot_respond_welcome_msg",
            "headers": {"req_id": req_id},
            "body": {"msgtype": "text", "text": {"content": content}},
        })

    async def _request(self, payload: dict[str, Any], timeout: float = 12) -> dict[str, Any]:
        ws = self._ws
        if ws is None:
            raise RuntimeError("企业微信长连接未建立")
        req_id = str((payload.get("headers") or {}).get("req_id") or "")
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        if req_id:
            self._pending[req_id] = future
        try:
            async with self._send_lock:
                await ws.send(json.dumps(payload, ensure_ascii=False))
            if not req_id:
                return {}
            return await asyncio.wait_for(future, timeout)
        finally:
            if req_id:
                self._pending.pop(req_id, None)

    async def _run(self) -> None:
        while not self._stop.is_set():
            self._reconnect.clear()
            try:
                await self._connect_once()
            except Exception as exc:
                if self.status != "disabled":
                    self.status = "disconnected"
                logger.warning("wecom_link_down", error=str(exc)[:300])
            if self._stop.is_set():
                break
            try:
                await asyncio.wait_for(self._reconnect.wait(), timeout=8)
            except asyncio.TimeoutError:
                pass
        self.status = "disconnected"

    async def _connect_once(self) -> None:
        async with AsyncSessionLocal() as db:
            config = await load_wecom_config(db)
        bot_id = str(config.get("bot_id") or "").strip()
        secret = decrypt_secret(str(config.get("secret_enc") or "")) if config.get("secret_enc") else ""
        if not config.get("enabled") or not bot_id or not secret:
            self.status = "disabled"
            await asyncio.sleep(10)
            return
        async with websockets.connect(WS_URL, open_timeout=8, close_timeout=3, ping_interval=None, max_size=2**20) as ws:
            self._ws = ws
            reader = asyncio.create_task(self._read_loop(ws))
            try:
                ack = await self._request({
                    "cmd": "aibot_subscribe",
                    "headers": {"req_id": f"aibot_subscribe_{uuid.uuid4().hex}"},
                    "body": {"bot_id": bot_id, "secret": secret},
                })
                if int(ack.get("errcode") or 0) != 0:
                    raise RuntimeError(ack.get("errmsg") or "企业微信认证失败")
                self.status = "connected"
                logger.info("wecom_link_connected")
                heartbeat = asyncio.create_task(self._heartbeat())
                stop_wait = asyncio.create_task(self._stop.wait())
                reconnect_wait = asyncio.create_task(self._reconnect.wait())
                await asyncio.wait(
                    {reader, stop_wait, reconnect_wait},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                heartbeat.cancel()
                if not reader.done():
                    await ws.close()
                    await asyncio.wait({reader}, timeout=3)
            finally:
                self._ws = None
                if not reader.done():
                    reader.cancel()

    async def _heartbeat(self) -> None:
        while True:
            await asyncio.sleep(30)
            try:
                ack = await self._request({
                    "cmd": "ping",
                    "headers": {"req_id": f"ping_{uuid.uuid4().hex}"},
                })
                if int(ack.get("errcode") or 0) != 0:
                    raise RuntimeError(ack.get("errmsg") or "heartbeat failed")
            except Exception as exc:
                logger.warning("wecom_heartbeat_failed", error=str(exc)[:200])
                self.request_reconnect()
                return

    async def _read_loop(self, ws: Any) -> None:
        async for raw in ws:
            try:
                frame = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(frame, dict):
                continue
            cmd = str(frame.get("cmd") or "")
            req_id = str((frame.get("headers") or {}).get("req_id") or "")
            if cmd in ("aibot_msg_callback", "aibot_event_callback"):
                asyncio.create_task(self._dispatch(frame))
                continue
            future = self._pending.get(req_id) if req_id else None
            if future is None and not cmd and len(self._pending) == 1:
                future = next(iter(self._pending.values()))
            if future and not future.done():
                future.set_result(frame)

    async def _dispatch(self, frame: dict[str, Any]) -> None:
        try:
            from app.core.wecom.inbound import handle_frame

            await handle_frame(self, frame)
        except Exception:
            logger.exception("wecom_inbound_failed")


wecom_link = WecomLink()
