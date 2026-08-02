from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

GITHUB_HOSTS = {
    "github.com",
    "api.github.com",
    "uploads.github.com",
    "raw.githubusercontent.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
}
SECRET_PATTERNS = (
    re.compile(r"(?i)(authorization\s*[:=]\s*(?:bearer|token)\s+)[^\s\"']+"),
    re.compile(r"(?i)(access_token|refresh_token|device_code|user_code)([\"']?\s*[:=]\s*[\"']?)[^\"'\s,}]+"),
)


def require_github_https(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or (parsed.hostname or "").lower() not in GITHUB_HOSTS:
        raise ValueError("只允许受信任的 GitHub HTTPS 地址")
    if parsed.username or parsed.password:
        raise ValueError("URL 不得包含凭据")
    return url


def parse_public_repository(value: str) -> tuple[str, str]:
    value = value.strip()
    parsed = urlparse(value if "://" in value else f"https://github.com/{value}")
    if parsed.scheme != "https" or parsed.hostname != "github.com":
        raise ValueError("请输入公开 GitHub 仓库地址")
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if len(parts) != 2:
        raise ValueError("仓库地址必须是 https://github.com/owner/repo")
    owner, repo = parts
    if repo.endswith(".git"):
        repo = repo[:-4]
    allowed = re.compile(r"^[A-Za-z0-9_.-]+$")
    if not allowed.fullmatch(owner) or not allowed.fullmatch(repo):
        raise ValueError("无效的 GitHub 仓库地址")
    return owner, repo


def safe_filename(value: str, fallback: str = "workflow") -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")
    return (cleaned[:120] or fallback)


def validate_zip_name(name: str) -> str:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or len(path.parts) != 1 or "\\" in name:
        raise ValueError(f"包内存在非法路径: {name}")
    return name


def ensure_within(root: Path, target: Path) -> Path:
    root_resolved = root.resolve()
    target_resolved = target.resolve()
    if target_resolved != root_resolved and root_resolved not in target_resolved.parents:
        raise ValueError("目标路径超出允许目录")
    return target_resolved


def redact(value: str) -> str:
    result = value
    for pattern in SECRET_PATTERNS:
        result = pattern.sub(lambda match: f"{match.group(1)}{match.group(2) if match.lastindex and match.lastindex > 1 else ''}[REDACTED]", result)
    return result
