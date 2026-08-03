# 安全边界

- 订阅源必须是公开 `github.com/{owner}/{repo}`，资源访问限制在 GitHub 受信任 HTTPS 主机。
- 下载不自动跟随未知重定向；GitHub 对象存储重定向会再次校验主机。
- 包上限 256 MiB，单条目上限 64 MiB，解压总量上限 512 MiB，压缩比上限 200。
- ZIP 条目必须位于根目录协议白名单或 `inputs/` 图像白名单内；拒绝 `..`、绝对路径、反斜杠路径、符号链接和额外文件。
- 校验 SHA-256 和 JSON 后，工作流文件使用临时文件和独占链接原子写入，绝不覆盖同版本的不同内容。
- 输入图像逐项校验清单声明、大小和 SHA-256，并以临时文件和独占链接写入当前用户专属的 ComfyUI input 子目录；输入图像与工作流文件是两个独立的本地提交阶段，下载失败不会覆盖已有不同内容。历史版本 LoRA 不进入主包，只有用户主动选择时才从清单中的 GitHub Release URL 下载；目标路径按原引用置于 ComfyUI LoRA 根目录内，并拒绝越界和覆盖不同内容的同名文件。新发布版本不允许声明 LoRA。
- 不执行包、仓库或清单中的任何代码。
- Token 只存系统 keyring；keyring 失败时只存当前 Python 进程内存。Token、设备码和 Authorization header 会从日志中脱敏。GitHub 对受信请求返回 401 时自动删除已存凭据并按未登录处理。
- 所有写 API 要求同源、请求体不超过 20 MiB，并通过 ComfyUI 当前请求解析用户目录；携带 JSON 请求体时必须使用 `application/json`，无参数写操作允许空请求体。
- 依赖计划默认只读。安装、升级或降级只有在请求明确携带确认后才执行；执行前检查 GitHub/Comfy Registry 网络，Git clone/fetch/checkout 可并行但 Python `requirements.txt` 安装串行，历史 Registry 依赖提交给 ComfyUI-Manager。统一操作记录按用户目录持久化进度、日志和结果。
- 删除已发布版本或工作流同样要求请求明确确认；删除会连同对应 Release 与 tag 一并移除，且不可恢复。
- 插件不收集遥测。

GitHub App 不携带 Client Secret 或 Private Key，不使用 webhook。所需仓库权限是 Metadata 只读、Contents 读写、Administration 读写。
