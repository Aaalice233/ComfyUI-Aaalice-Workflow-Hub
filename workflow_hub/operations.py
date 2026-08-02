from __future__ import annotations

import asyncio
import uuid
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from .security import redact


@dataclass
class Operation:
    id: str
    kind: str
    stage: str = "queued"
    status: str = "running"
    logs: list[str] = field(default_factory=list)
    error_code: str | None = None
    error_params: dict[str, str | int] | None = None
    progress: dict[str, int] | None = None
    progress_mode: str = "bytes"
    result: dict[str, Any] | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def public(self) -> dict[str, Any]:
        data = asdict(self)
        data["logs"] = [redact(line) for line in self.logs[-200:]]
        return data


class OperationStore:
    def __init__(self) -> None:
        self._items: dict[str, Operation] = {}
        self._order: deque[str] = deque(maxlen=100)
        self._lock = asyncio.Lock()

    async def create(self, kind: str) -> Operation:
        async with self._lock:
            item = Operation(id=uuid.uuid4().hex, kind=kind)
            self._items[item.id] = item
            self._order.appendleft(item.id)
            return item

    async def get(self, operation_id: str) -> Operation:
        try:
            return self._items[operation_id]
        except KeyError as exc:
            raise KeyError("操作不存在或已过期") from exc

    async def list(self) -> list[dict[str, Any]]:
        return [self._items[item].public() for item in self._order if item in self._items]


operations = OperationStore()
