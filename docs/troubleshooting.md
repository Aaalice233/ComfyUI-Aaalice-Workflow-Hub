# 故障排查

## 顶栏没有“工作流中心”

确认 ComfyUI Frontend 为 `1.33.9+`，重启 ComfyUI，并在启动日志中检查插件 Python 导入错误。插件使用 `WEB_DIRECTORY` 加载 `web/comfyui/workflow_hub.js`。

## 发布页无法读取当前画布

发布器只读取当前 ComfyUI 画布。请从 ComfyUI 顶栏打开工作流中心，不要直接访问 `/workflow-hub` 页面；打开后核对发布页顶部显示的工作流文件名。

## GitHub 登录无法开始

检查 GitHub App Client ID 是否已配置。可使用环境变量 `WORKFLOW_HUB_GITHUB_CLIENT_ID` 覆盖内置值，修改后重启 ComfyUI。Device Flow 授权过期时重新开始。

## 提示“请求无效： Unknown user: default”

ComfyUI 以 `--multi-user` 多用户模式运行时，请求必须携带当前用户身份。插件面板和宿主扩展会自动透传 ComfyUI 前端已登录的用户；早期版本缺少该透传时会报此错误，升级插件即可。若仍未解决，请确认已在 ComfyUI 界面中选择用户，或移除 `--multi-user` 参数使用单用户模式。

## 提示“GitHub 登录已失效，请重新登录”

已存储的 token 过期或被撤销（例如在 GitHub 设置中取消了授权）。插件在 GitHub 返回 401 时会自动清除失效凭据并按未登录处理，重新登录即可。订阅清单读取会在登录后使用该凭据提高配额，凭据失效时自动回退匿名/raw 路径，功能不受登录态影响。

## 通过 HTTP 代理访问 GitHub

插件启动时会自动继承 Windows 系统代理（“设置 → 网络 → 代理”中启用的代理服务器，Clash/v2ray 等工具开启“系统代理”即属于此类），Git 克隆、pip 依赖安装、GitHub 请求（登录、发布、订阅刷新、下载）和 ComfyUI-Manager 请求都会经过该代理，无需开启 TUN 模式。注入的 `NO_PROXY` 始终包含本机回环地址，本机请求不受影响。

如需使用与系统代理不同的配置，可在启动 ComfyUI 前设置 `HTTP_PROXY` / `HTTPS_PROXY` / `NO_PROXY` 环境变量；只要任一代理环境变量已存在，插件就不会读取系统代理，完全遵循环境变量。启动日志中的 `System proxy applied: ...` 可确认系统代理是否生效（凭据会被打码）。

注意：暂不支持 PAC 自动配置脚本；系统代理关闭时插件不会注入任何代理。代理指向的加速工具必须正在运行，否则连接会失败。

## 订阅源刷新失败

订阅清单读取不依赖匿名 API 配额：已登录 GitHub 时使用用户 token 走 Contents API，未登录时优先走 GitHub Raw CDN 只读地址（带强制刷新参数绕开缓存），两条路径互为其失败时的回退。已有订阅会保留本地缓存作为失败回退，但网页打开和手动刷新都会强制重新校验远端。新订阅或刷新仍失败时，请确认仓库公开、根目录存在 `workflow-catalog.json`，并检查网络、VPN 或 TUN 模式。订阅无需 GitHub 登录。

## 新仓库无法发布

仓库必须公开，并且 GitHub App installation 必须包含该仓库。授权后刷新仓库列表。插件不支持 Personal Access Token 或私有仓库绕过此限制。

## Manager 不可用

工作流仍可下载。GitHub 依赖使用 ComfyUI 环境中的 Git；历史 Registry 依赖才需要 ComfyUI-Manager `3.0+`（legacy API）或 `4.2.1+`（v2 API）。补全开始前会检查下载端点；如果提示无法连接，请检查网络、VPN 或 TUN 模式。Git 任务可并行，Python requirements 日志和 Manager post-install 结果都会进入同一安装详情；操作记录按用户持久化，安装或升级后重启 ComfyUI 即可。Manager 3.x 下如果队列任务被拒绝并返回 403，需把 Manager 的 `security_level` 调整为 `middle` 或更低（默认 `normal` 即可）。

## 同版本下载失败

如果目标版本文件已存在但内容与安装记录不一致，插件会拒绝覆盖。保留修改版，或在界面明确删除该已记录版本后重新下载。

## 文件已经删除但仍显示已下载

插件会在读取工作流目录时核对 `installed.json` 与真实文件。通过 ComfyUI 或资源管理器删除工作流后，重新打开工作流中心即可自动清除失效的已下载状态。

## 发布停在待同步

这表示 Release 已发布，但包含版本目录、产品资料、README 和根清单的仓库提交失败。修复仓库权限或网络后从待同步发布重试；恢复会读取已生成的 ZIP，不要删除本地草稿包或手动创建同 tag Release。
