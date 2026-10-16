"""Celery 任务统一事件循环运行时。

Celery worker 默认用 asyncio.run() 为每个任务新建事件循环；进程中存在多个
模块级异步资源（OllamaEmbeddings / ChatOpenAI 缓存 / redis.asyncio 客户端等）
绑定各自创建时的事件循环，跨 loop 复用会抛 "Event loop is closed"，表现为
任务首轮调用失败、评估指标失真。

这里改为在每个 worker 子进程内复用一个持久事件循环（fork 后按 pid 重建），
从根本上消除跨 loop 复用。
"""
from __future__ import annotations

import asyncio
import os
from typing import Any, Coroutine

_LOOP: Any = None
_LOOP_PID: int | None = None


def run_in_persistent_loop(coro: Coroutine[Any, Any, Any]) -> Any:
    """在当前 worker 进程内复用同一事件循环执行协程。"""
    global _LOOP, _LOOP_PID
    pid = os.getpid()
    if _LOOP is None or _LOOP.is_closed() or _LOOP_PID != pid:
        _LOOP = asyncio.new_event_loop()
        asyncio.set_event_loop(_LOOP)
        _LOOP_PID = pid
    return _LOOP.run_until_complete(coro)
