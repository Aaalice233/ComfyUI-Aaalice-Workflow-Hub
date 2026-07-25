from __future__ import annotations

import asyncio
import base64
import json
import os
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import aiohttp

from .security import require_github_https

API = "https://api.github.com"
DEVICE_URL = "https://github.com/login/device/code"
TOKEN_URL = "https://github.com/login/oauth/access_token"
CLIENT_ID = os.getenv("WORKFLOW_HUB_GITHUB_CLIENT_ID", "Iv23likAV8HgkxJ6f6Rz")
KEYRING_SERVICE = "ComfyUI-Aaalice-Workflow-Hub"


class GitHubError(RuntimeError):
    def __init__(self, message: str, status: int = 0, data: Any = None):
        super().__init__(message)
        self.status = status
        self.data = data


class TokenStore:
    def __init__(self) -> None:
        self._session_tokens: dict[str, str] = {}
        try:
            import keyring

            self._keyring = keyring
        except Exception:
            self._keyring = None

    @property
    def persistent(self) -> bool:
        return self._keyring is not None

    async def get_record(self, user_key: str) -> dict[str, Any] | None:
        raw: str | None = None
        if self._keyring:
            try:
                raw = await asyncio.to_thread(self._keyring.get_password, KEYRING_SERVICE, user_key)
            except Exception:
                self._keyring = None
        raw = raw or self._session_tokens.get(user_key)
        if not raw:
            return None
        try:
            value = json.loads(raw)
            return value if isinstance(value, dict) else None
        except json.JSONDecodeError:
            return {"access_token": raw}

    async def get(self, user_key: str) -> str | None:
        record = await self.get_record(user_key)
        return str(record["access_token"]) if record and record.get("access_token") else None

    async def set(self, user_key: str, credential: str | dict[str, Any]) -> None:
        value = {"access_token": credential} if isinstance(credential, str) else dict(credential)
        raw = json.dumps(value)
        # Keep the active session usable even if the platform keyring becomes
        # temporarily unavailable after a successful write.
        self._session_tokens[user_key] = raw
        if self._keyring:
            try:
                await asyncio.to_thread(self._keyring.set_password, KEYRING_SERVICE, user_key, raw)
                return
            except Exception:
                self._keyring = None

    async def delete(self, user_key: str) -> None:
        self._session_tokens.pop(user_key, None)
        if self._keyring:
            try:
                await asyncio.to_thread(self._keyring.delete_password, KEYRING_SERVICE, user_key)
            except Exception:
                pass


tokens = TokenStore()


@dataclass
class ContentFile:
    content: bytes
    sha: str
    etag: str | None


@dataclass(frozen=True)
class GitTreeFile:
    path: str
    mode: str
    sha: str


@dataclass(frozen=True)
class BranchState:
    branch: str
    commit_sha: str
    tree_sha: str
    files: dict[str, GitTreeFile]


class GitHubClient:
    def __init__(self, token: str | None = None, session: aiohttp.ClientSession | None = None):
        self.token = token
        self._session = session

    def headers(self, **extra: str) -> dict[str, str]:
        result = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "ComfyUI-Aaalice-Workflow-Hub/1.0.0",
            **extra,
        }
        if self.token:
            result["Authorization"] = f"Bearer {self.token}"
        return result

    async def request(
        self,
        method: str,
        url: str,
        *,
        expected: tuple[int, ...] = (200,),
        allow_redirects: bool = False,
        **kwargs: Any,
    ) -> tuple[Any, aiohttp.typedefs.LooseHeaders]:
        require_github_https(url)
        own = self._session is None
        session = self._session or aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60))
        try:
            headers = self.headers(**kwargs.pop("headers", {}))
            for attempt in range(3):
                try:
                    async with session.request(
                        method,
                        url,
                        headers=headers,
                        allow_redirects=allow_redirects,
                        **kwargs,
                    ) as response:
                        if response.status in expected and response.status in {204, 304}:
                            return None, response.headers
                        if 300 <= response.status < 400 and response.status not in expected:
                            location = response.headers.get("Location", "")
                            require_github_https(location)
                            raise GitHubError("GitHub 返回了未允许的重定向", response.status)
                        data: Any
                        if response.content_type == "application/json" or response.content_type.endswith("+json"):
                            data = await response.json()
                        else:
                            data = await response.read()
                        if response.status not in expected:
                            message = data.get("message", "GitHub 请求失败") if isinstance(data, dict) else "GitHub 请求失败"
                            raise GitHubError(message, response.status, data)
                        return data, response.headers
                except (aiohttp.ClientConnectionError, asyncio.TimeoutError) as exc:
                    safe_retry = method.upper() in {"GET", "HEAD"} or isinstance(exc, aiohttp.ClientConnectorError)
                    if attempt == 2 or not safe_retry:
                        raise
                    # Windows 上的 GitHub TLS 建连偶发失败；请求尚未建立时可安全重试，
                    # GET/HEAD 可在连接中断或超时后重试，结果不明的写请求不能自动重放。
                    await asyncio.sleep(2**attempt)
            raise RuntimeError("GitHub 请求重试状态异常")
        finally:
            if own:
                await session.close()

    async def get_catalog(self, owner: str, repo: str, etag: str | None = None) -> ContentFile | None:
        headers = {"If-None-Match": etag} if etag else {}
        try:
            data, response_headers = await self.request(
                "GET", f"{API}/repos/{owner}/{repo}/contents/workflow-catalog.json", expected=(200, 304), headers=headers
            )
        except GitHubError as exc:
            if exc.status == 404:
                return None
            raise
        if not data:
            return None
        content = base64.b64decode(data["content"])
        return ContentFile(content=content, sha=data["sha"], etag=response_headers.get("ETag"))

    async def put_catalog(self, owner: str, repo: str, catalog: bytes, sha: str | None, message: str) -> str:
        payload: dict[str, Any] = {"message": message, "content": base64.b64encode(catalog).decode("ascii")}
        if sha:
            payload["sha"] = sha
        data, _ = await self.request(
            "PUT", f"{API}/repos/{owner}/{repo}/contents/workflow-catalog.json", expected=(200, 201), json=payload
        )
        return data["content"]["sha"]

    async def get_branch_state(self, owner: str, repo: str) -> BranchState:
        repository, _ = await self.request("GET", f"{API}/repos/{owner}/{repo}")
        branch = str(repository.get("default_branch") or "")
        if not branch:
            raise GitHubError("发布仓库尚未初始化，请先创建首个提交", 409)
        encoded_branch = quote(branch, safe="")
        reference, _ = await self.request("GET", f"{API}/repos/{owner}/{repo}/git/ref/heads/{encoded_branch}")
        commit_sha = str(reference["object"]["sha"])
        commit, _ = await self.request("GET", f"{API}/repos/{owner}/{repo}/git/commits/{commit_sha}")
        tree_sha = str(commit["tree"]["sha"])
        tree, _ = await self.request("GET", f"{API}/repos/{owner}/{repo}/git/trees/{tree_sha}?recursive=1")
        if tree.get("truncated"):
            raise GitHubError("发布仓库文件树过大，无法安全更新", 409)
        files = {
            str(item["path"]): GitTreeFile(
                path=str(item["path"]),
                mode=str(item.get("mode") or "100644"),
                sha=str(item["sha"]),
            )
            for item in tree.get("tree", [])
            if item.get("type") == "blob"
        }
        return BranchState(branch=branch, commit_sha=commit_sha, tree_sha=tree_sha, files=files)

    async def read_file_from_state(
        self,
        owner: str,
        repo: str,
        state: BranchState,
        path: str,
    ) -> bytes | None:
        entry = state.files.get(path)
        if entry is None:
            return None
        blob, _ = await self.request("GET", f"{API}/repos/{owner}/{repo}/git/blobs/{entry.sha}")
        if blob.get("encoding") != "base64":
            raise GitHubError(f"无法读取仓库文件: {path}")
        return base64.b64decode(str(blob["content"]))

    async def commit_files(
        self,
        owner: str,
        repo: str,
        state: BranchState,
        files: dict[str, bytes],
        message: str,
        *,
        delete_paths: set[str] | None = None,
        copy_blobs: dict[str, GitTreeFile] | None = None,
    ) -> str:
        entries: list[dict[str, Any]] = []
        for path, source in sorted((copy_blobs or {}).items()):
            entries.append({"path": path, "mode": source.mode, "type": "blob", "sha": source.sha})
        for path, content in sorted(files.items()):
            blob, _ = await self.request(
                "POST",
                f"{API}/repos/{owner}/{repo}/git/blobs",
                expected=(201,),
                json={"content": base64.b64encode(content).decode("ascii"), "encoding": "base64"},
            )
            entries.append({"path": path, "mode": "100644", "type": "blob", "sha": blob["sha"]})
        for path in sorted(delete_paths or set()):
            entries.append({"path": path, "mode": "100644", "type": "blob", "sha": None})
        tree, _ = await self.request(
            "POST",
            f"{API}/repos/{owner}/{repo}/git/trees",
            expected=(201,),
            json={"base_tree": state.tree_sha, "tree": entries},
        )
        commit, _ = await self.request(
            "POST",
            f"{API}/repos/{owner}/{repo}/git/commits",
            expected=(201,),
            json={"message": message, "tree": tree["sha"], "parents": [state.commit_sha]},
        )
        encoded_branch = quote(state.branch, safe="")
        await self.request(
            "PATCH",
            f"{API}/repos/{owner}/{repo}/git/refs/heads/{encoded_branch}",
            json={"sha": commit["sha"], "force": False},
        )
        return str(commit["sha"])

    async def list_repositories(self) -> list[dict[str, Any]]:
        installations, _ = await self.request("GET", f"{API}/user/installations?per_page=100")
        repositories: dict[int, dict[str, Any]] = {}
        for installation in installations.get("installations", []):
            data, _ = await self.request(
                "GET",
                f"{API}/user/installations/{installation['id']}/repositories?per_page=100",
            )
            for item in data.get("repositories", []):
                if not item["private"]:
                    repositories[item["id"]] = {
                        "id": item["id"],
                        "full_name": item["full_name"],
                        "name": item["name"],
                        "owner": item["owner"]["login"],
                        "description": item.get("description") or "",
                        "default_branch": item["default_branch"],
                    }
        return sorted(repositories.values(), key=lambda item: item["full_name"].casefold())

    async def create_repository(self, name: str, description: str = "") -> dict[str, Any]:
        data, _ = await self.request(
            "POST",
            f"{API}/user/repos",
            expected=(201,),
            json={"name": name, "description": description, "private": False, "auto_init": True},
        )
        return {"id": data["id"], "full_name": data["full_name"], "html_url": data["html_url"]}

    async def create_draft_release(self, owner: str, repo: str, tag: str, name: str, body: str) -> dict[str, Any]:
        data, _ = await self.request(
            "POST",
            f"{API}/repos/{owner}/{repo}/releases",
            expected=(201,),
            json={"tag_name": tag, "name": name, "body": body, "draft": True, "prerelease": False},
        )
        return data

    async def get_release_by_tag(self, owner: str, repo: str, tag: str) -> dict[str, Any] | None:
        try:
            data, _ = await self.request("GET", f"{API}/repos/{owner}/{repo}/releases/tags/{tag}")
            return data
        except GitHubError as exc:
            if exc.status == 404:
                # GitHub 的按 tag 查询不会返回草稿；失败续传必须从 release 列表恢复草稿。
                releases, _ = await self.request("GET", f"{API}/repos/{owner}/{repo}/releases?per_page=100")
                return next((item for item in releases if item.get("tag_name") == tag), None)
            raise

    async def upload_asset(self, upload_url: str, name: str, content: bytes, content_type: str) -> dict[str, Any]:
        url = upload_url.split("{", 1)[0] + f"?name={name}"
        data, _ = await self.request(
            "POST", url, expected=(201,), data=content, headers={"Content-Type": content_type}
        )
        return data

    async def publish_release(self, owner: str, repo: str, release_id: int) -> dict[str, Any]:
        data, _ = await self.request(
            "PATCH", f"{API}/repos/{owner}/{repo}/releases/{release_id}", json={"draft": False}
        )
        return data

    async def update_release_notes(self, owner: str, repo: str, release_id: int, body: str) -> None:
        await self.request("PATCH", f"{API}/repos/{owner}/{repo}/releases/{release_id}", json={"body": body})

    async def delete_release(self, owner: str, repo: str, release_id: int) -> None:
        await self.request("DELETE", f"{API}/repos/{owner}/{repo}/releases/{release_id}", expected=(204,))

    async def delete_tag(self, owner: str, repo: str, tag: str) -> None:
        try:
            await self.request(
                "DELETE", f"{API}/repos/{owner}/{repo}/git/refs/tags/{quote(tag, safe='')}", expected=(204,)
            )
        except GitHubError as exc:
            # 删除是幂等目标：tag 已不存在时直接视为完成。
            if exc.status != 422:
                raise

    async def download(self, url: str, destination: Any, operation: Any | None = None) -> None:
        require_github_https(url)
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=300)) as session:
            async with session.get(url, headers=self.headers(), allow_redirects=False) as response:
                if 300 <= response.status < 400:
                    location = response.headers.get("Location", "")
                    require_github_https(location)
                    async with session.get(location, allow_redirects=False) as redirected:
                        await self._stream(redirected, destination, operation)
                else:
                    await self._stream(response, destination, operation)

    async def _stream(self, response: aiohttp.ClientResponse, destination: Any, operation: Any | None) -> None:
        if response.status != 200:
            raise GitHubError("下载 Release 资源失败", response.status)
        total = int(response.headers.get("Content-Length", "0"))
        received = 0
        with open(destination, "wb") as stream:
            async for chunk in response.content.iter_chunked(1024 * 256):
                received += len(chunk)
                if received > 256 * 1024 * 1024:
                    raise GitHubError("Release 资源超过 256 MiB")
                stream.write(chunk)
                if operation and total:
                    operation.progress = {"received": received, "total": total}


async def start_device_flow() -> dict[str, Any]:
    if not CLIENT_ID:
        raise GitHubError("GitHub App Client ID 尚未配置")
    async with aiohttp.ClientSession() as session:
        async with session.post(
            DEVICE_URL,
            headers={"Accept": "application/json"},
            data={"client_id": CLIENT_ID},
        ) as response:
            data = await response.json()
            if response.status != 200:
                raise GitHubError(data.get("error_description", "无法启动 GitHub 登录"), response.status, data)
            return data


async def poll_device_flow(device_code: str) -> dict[str, Any]:
    if not CLIENT_ID:
        raise GitHubError("GitHub App Client ID 尚未配置")
    async with aiohttp.ClientSession() as session:
        async with session.post(
            TOKEN_URL,
            headers={"Accept": "application/json"},
            data={
                "client_id": CLIENT_ID,
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
        ) as response:
            data = await response.json()
            if response.status != 200:
                raise GitHubError("GitHub 登录轮询失败", response.status, data)
            return data


async def refresh_access_token(refresh_token: str) -> dict[str, Any]:
    if not CLIENT_ID:
        raise GitHubError("GitHub App Client ID 尚未配置")
    async with aiohttp.ClientSession() as session:
        async with session.post(
            TOKEN_URL,
            headers={"Accept": "application/json"},
            data={
                "client_id": CLIENT_ID,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
        ) as response:
            data = await response.json()
            if response.status != 200 or "error" in data:
                raise GitHubError(data.get("error_description", "GitHub 凭据刷新失败"), response.status, data)
            data["created_at"] = int(time.time())
            return data
