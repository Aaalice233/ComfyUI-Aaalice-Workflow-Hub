"""系统代理由插件统一注入进程环境，让 Git/pip 子进程与 HTTP 客户端无需 TUN 也能走代理。

优先级：已存在的代理环境变量 > Windows 系统代理（注册表 Internet Settings）。
注入仅在变量缺失时用 setdefault 完成，绝不覆盖用户显式配置。
"""

from __future__ import annotations

import os
import sys
from typing import Any

_PROXY_SCHEMES = ("http", "https", "all")
_LOCAL_BYPASS = ("localhost", "127.0.0.1", "::1")

_status: dict[str, Any] | None = None


def _normalize_proxy_url(scheme: str, value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    if "://" in value:
        return value
    if scheme == "all":
        return f"socks5h://{value}"
    return f"http://{value}"


def _parse_proxy_server(value: str) -> dict[str, str]:
    """解析 Windows ProxyServer 字符串，支持单一地址和 scheme= 分组两种形态。"""
    value = (value or "").strip()
    if not value:
        return {}
    proxies: dict[str, str] = {}
    segments = [segment.strip() for segment in value.split(";") if segment.strip()]
    grouped = False
    for segment in segments:
        key, separator, address = segment.partition("=")
        if not separator:
            continue
        scheme = key.strip().lower()
        if scheme == "socks":
            scheme = "all"
        if scheme not in _PROXY_SCHEMES:
            continue
        url = _normalize_proxy_url(scheme, address)
        if url:
            proxies[scheme] = url
            grouped = True
    if grouped:
        if "all" in proxies:
            proxies.setdefault("http", proxies["all"])
            proxies.setdefault("https", proxies["all"])
        return proxies
    # 未分组的单一地址对所有协议生效
    for segment in segments:
        if "=" in segment:
            continue
        url = _normalize_proxy_url("http", segment)
        if url:
            return {"http": url, "https": url}
    return {}


def _parse_proxy_override(value: str) -> list[str]:
    """Windows ProxyOverride 使用分号分隔，可能包含 <local> 标记，转换为 no_proxy 列表。"""
    entries: list[str] = []
    for segment in (value or "").split(";"):
        entry = segment.strip().lower()
        if not entry or entry == "<local>":
            continue
        # Windows 的 * 通配转换为 no_proxy 的后缀匹配写法（*.local → .local、*example.com → example.com）
        if entry.startswith("*"):
            entry = entry[1:] or entry
        entries.append(entry)
    return entries


def _windows_system_proxy() -> dict[str, Any] | None:
    if sys.platform != "win32":
        return None
    try:
        import winreg
    except ImportError:
        return None
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
        ) as key:
            enabled, _ = winreg.QueryValueEx(key, "ProxyEnable")
            if not enabled:
                return None
            try:
                server, _ = winreg.QueryValueEx(key, "ProxyServer")
            except OSError:
                server = ""
            try:
                override, _ = winreg.QueryValueEx(key, "ProxyOverride")
            except OSError:
                override = ""
    except OSError:
        return None
    proxies = _parse_proxy_server(str(server))
    if not proxies:
        return None
    return {"proxies": proxies, "bypass": _parse_proxy_override(str(override))}


def _mask_proxy_url(url: str) -> str:
    """状态与日志中隐藏代理凭据。"""
    if "@" not in url:
        return url
    scheme, _, rest = url.partition("://")
    _, _, host = rest.rpartition("@")
    return f"{scheme}://***@{host}"


def _existing_env(name: str) -> str:
    return os.environ.get(name) or os.environ.get(name.lower()) or ""


def apply_system_proxy() -> dict[str, Any]:
    """把检测到的系统代理写入进程环境（仅补缺），返回可供诊断的状态摘要。

    幂等：重复调用返回缓存结果，不重复写环境变量。
    """
    global _status
    if _status is not None:
        return _status

    status: dict[str, Any] = {"enabled": False, "source": None, "proxies": {}, "bypass": []}

    existing = {scheme: _existing_env(f"{scheme.upper()}_PROXY") for scheme in _PROXY_SCHEMES}
    if any(existing.values()):
        status.update(
            enabled=True,
            source="environment",
            proxies={scheme: _mask_proxy_url(url) for scheme, url in existing.items() if url},
            bypass=[entry for entry in (_existing_env("NO_PROXY").split(",")) if entry.strip()],
        )
        _status = status
        return status

    detected = _windows_system_proxy()
    if not detected:
        _status = status
        return status

    proxies: dict[str, str] = detected["proxies"]
    bypass = list(dict.fromkeys([*detected["bypass"], *_LOCAL_BYPASS]))
    applied: dict[str, str] = {}
    for scheme in ("http", "https", "all"):
        url = proxies.get(scheme)
        if not url:
            continue
        os.environ.setdefault(f"{scheme.upper()}_PROXY", url)
        os.environ.setdefault(f"{scheme.lower()}_proxy", url)
        applied[scheme] = url
    if applied:
        os.environ.setdefault("NO_PROXY", ",".join(bypass))
        os.environ.setdefault("no_proxy", ",".join(bypass))
    status.update(
        enabled=bool(applied),
        source="system" if applied else None,
        proxies={scheme: _mask_proxy_url(url) for scheme, url in applied.items()},
        bypass=bypass,
    )
    _status = status
    return status


def proxy_status() -> dict[str, Any]:
    return apply_system_proxy()
