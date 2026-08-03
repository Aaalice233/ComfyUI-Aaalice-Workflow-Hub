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
    owner_key: str | None = field(default=None, repr=False)
    metadata: dict[str, Any] = field(default_factory=dict)

    def public(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("owner_key", None)
        data["logs"] = [redact(line) for line in self.logs[-200:]]
        return data

    def record(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("owner_key", None)
        return data


class OperationStore:
    def __init__(self) -> None:
        self._items: dict[str, Operation] = {}
        self._orders: dict[str, deque[str]] = {}
        self._loaded: set[str] = set()
        self._storages: dict[str, Any] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def _owner_key(storage: Any | None) -> str:
        return storage.key if storage is not None else ""

    async def _load(self, storage: Any | None) -> None:
        owner_key = self._owner_key(storage)
        if owner_key in self._loaded:
            return
        self._loaded.add(owner_key)
        if storage is None:
            return
        self._storages[owner_key] = storage
        records = await storage.read_json("operations.json", [])
        if not isinstance(records, list):
            return
        order = self._orders.setdefault(owner_key, deque(maxlen=100))
        for record in records:
            if not isinstance(record, dict) or not record.get("id") or record["id"] in self._items:
                continue
            operation = Operation(
                id=str(record["id"]),
                kind=str(record.get("kind") or "unknown"),
                stage=str(record.get("stage") or "complete"),
                status=str(record.get("status") or "failed"),
                logs=[str(line) for line in record.get("logs", []) if isinstance(line, str)],
                error_code=record.get("error_code"),
                error_params=record.get("error_params") if isinstance(record.get("error_params"), dict) else None,
                progress=record.get("progress") if isinstance(record.get("progress"), dict) else None,
                progress_mode=str(record.get("progress_mode") or "bytes"),
                result=record.get("result") if isinstance(record.get("result"), dict) else None,
                created_at=str(record.get("created_at") or datetime.now(timezone.utc).isoformat()),
                owner_key=owner_key,
                metadata=record.get("metadata") if isinstance(record.get("metadata"), dict) else {},
            )
            if operation.status == "running":
                operation.status = "failed"
                operation.stage = "failed"
                operation.error_code = "operation.interrupted"
                operation.error_params = {}
                operation.logs.append("Operation was interrupted before the ComfyUI process restarted.")
            self._items[operation.id] = operation
            order.append(operation.id)
        await self._persist_owner(storage, owner_key)

    async def _persist_owner(self, storage: Any, owner_key: str) -> None:
        order = self._orders.setdefault(owner_key, deque(maxlen=100))
        records = [self._items[item].record() for item in order if item in self._items]
        await storage.write_json("operations.json", records)

    async def persist(self, operation: Operation) -> None:
        if operation.owner_key is None:
            return
        storage = self._storages.get(operation.owner_key)
        if storage is None:
            return
        async with self._lock:
            await self._persist_owner(storage, operation.owner_key)

    async def _monitor(self, operation: Operation) -> None:
        while operation.status == "running":
            await asyncio.sleep(0.5)
            await self.persist(operation)
        await self.persist(operation)

    async def create(self, kind: str, storage: Any | None = None, metadata: dict[str, Any] | None = None) -> Operation:
        owner_key = self._owner_key(storage)
        async with self._lock:
            await self._load(storage)
            item = Operation(
                id=uuid.uuid4().hex,
                kind=kind,
                owner_key=owner_key or None,
                metadata=metadata or {},
            )
            self._items[item.id] = item
            self._orders.setdefault(owner_key, deque(maxlen=100)).appendleft(item.id)
            if storage is not None:
                await self._persist_owner(storage, owner_key)
        asyncio.create_task(self._monitor(item))
        return item

    async def get(self, operation_id: str, storage: Any | None = None) -> Operation:
        owner_key = self._owner_key(storage)
        async with self._lock:
            await self._load(storage)
            try:
                item = self._items[operation_id]
            except KeyError as exc:
                raise KeyError("Operation does not exist or has expired") from exc
            if storage is not None and item.owner_key != owner_key:
                raise KeyError("Operation does not exist or has expired")
            return item

    async def list(self, storage: Any | None = None) -> list[dict[str, Any]]:
        owner_key = self._owner_key(storage)
        async with self._lock:
            await self._load(storage)
            order = self._orders.get(owner_key, deque())
            return [self._items[item].public() for item in order if item in self._items]


operations = OperationStore()
