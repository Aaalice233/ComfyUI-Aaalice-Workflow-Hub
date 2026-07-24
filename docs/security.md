# 安全边界

- 订阅源必须是公开 `github.com/{owner}/{repo}`，资源访问限制在 GitHub 受信任 HTTPS 主机。
- 下载不自动跟随未知重定向；GitHub 对象存储重定向会再次校验主机。
- 包上限 256 MiB，单条目上限 64 MiB，解压总量上限 512 MiB，压缩比上限 200。
- ZIP 条目必须位于根目录且在协议白名单内；拒绝 `..`、绝对路径、反斜杠路径、符号链接和额外文件。
- 校验 SHA-256 和 JSON 后才原子写入工作流目录。
- 不执行包、仓库或清单中的任何代码。
- Token 只存系统 keyring；keyring 失败时只存当前 Python 进程内存。Token、设备码和 Authorization header 会从日志中脱敏。
- 所有写 API 要求同源、`application/json`、请求体不超过 2 MiB，并通过 ComfyUI 当前请求解析用户目录。
- 依赖计划默认只读。安装、升级或降级只有在请求明确携带确认后才提交给 Manager，且按顺序提交。
- 插件不收集遥测。

GitHub App 不携带 Client Secret 或 Private Key，不使用 webhook。所需仓库权限是 Metadata 只读、Contents 读写、Administration 读写。
