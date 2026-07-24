from __future__ import annotations

import asyncio
import json
import os
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


class UserStorage:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.state_dir = self.root / "workflow_hub"
        self.state_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_request(cls, request: Any) -> "UserStorage":
        from server import PromptServer

        manager = PromptServer.instance.user_manager
        marker = Path(manager.get_request_user_filepath(request, "workflow_hub/.root"))
        return cls(marker.parent.parent)

    @property
    def key(self) -> str:
        return str(self.root).casefold()

    async def read_json(self, name: str, default: Any) -> Any:
        path = self.state_dir / name
        async with _locks[self.key]:
            if not path.exists():
                return default
            return json.loads(path.read_text(encoding="utf-8"))

    async def write_json(self, name: str, value: Any) -> None:
        path = self.state_dir / name
        payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
        async with _locks[self.key]:
            descriptor, temp_name = tempfile.mkstemp(prefix=f".{name}.", suffix=".tmp", dir=self.state_dir)
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temp_name, path)
            finally:
                if os.path.exists(temp_name):
                    os.unlink(temp_name)

    async def update_json(self, name: str, default: Any, mutator: Any) -> Any:
        path = self.state_dir / name
        async with _locks[self.key]:
            value = json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
            result = mutator(value)
            payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
            descriptor, temp_name = tempfile.mkstemp(prefix=f".{name}.", suffix=".tmp", dir=self.state_dir)
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temp_name, path)
            finally:
                if os.path.exists(temp_name):
                    os.unlink(temp_name)
            return result

    @property
    def workflows_root(self) -> Path:
        path = self.root / "workflows" / "Workflow Hub"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def cache_dir(self) -> Path:
        path = self.state_dir / "cache"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def drafts_dir(self) -> Path:
        path = self.state_dir / "drafts"
        path.mkdir(parents=True, exist_ok=True)
        return path
