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

插件会在 GitHub App 的 8 小时 access token 临近过期时自动刷新并保存新的凭据，正常使用不需要反复登录。只有 6 个月 refresh token 已过期、用户在 GitHub 撤销了授权、系统 keyring 中的凭据被清除，或 GitHub 明确拒绝凭据时才会重新显示登录页。重新登录一次即可；若每次重启 ComfyUI 都丢失登录，请确认 `keyring` 依赖可用且系统凭据管理器允许保存 `ComfyUI-Aaalice-Workflow-Hub` 凭据。订阅清单在未登录时仍会回退匿名/raw 路径。

## 通过 HTTP 代理访问 GitHub

插件启动时会自动继承 Windows 系统代理（“设置 → 网络 → 代理”中启用的代理服务器，Clash/v2ray 等工具开启“系统代理”即属于此类），Git 克隆、pip 依赖安装、GitHub 请求（登录、发布、订阅刷新、下载）和 ComfyUI-Manager 请求都会经过该代理，无需开启 TUN 模式。注入的 `NO_PROXY` 始终包含本机回环地址，本机请求不受影响。

如需使用与系统代理不同的配置，可在启动 ComfyUI 前设置 `HTTP_PROXY` / `HTTPS_PROXY` / `NO_PROXY` 环境变量；只要任一代理环境变量已存在，插件就不会读取系统代理，完全遵循环境变量。启动日志中的 `System proxy applied: ...` 可确认系统代理是否生效（凭据会被打码）。

注意：暂不支持 PAC 自动配置脚本；系统代理关闭时插件不会注入任何代理。代理指向的加速工具必须正在运行，否则连接会失败。

## 秋叶（绘世）启动器镜像

使用秋叶整合包时，插件会自动读取启动器「设置 → 网络设置」中的镜像开关并保持一致行为，无需在插件中重复配置：

- **Git 国内镜像**：开启后，插件补全的克隆与拉取优先使用启动器镜像清单中的国内源（覆盖内核等已知仓库），失败时自动回退 GitHub 源站；安装前的网络检查也按镜像端点判定，不会误报“GitHub 不可达”。
- **PyPI 国内镜像**：开启后，安装插件 `requirements.txt` 时自动选择可用的国内 PyPI 镜像；全部镜像不可达时回退 pip 默认源（并遵循上述代理）。
- 启动器中切换开关后无需重启 ComfyUI，下一次补全即生效。
- 通过镜像地址克隆的插件（jihulab、gitee 或 ghproxy 前缀的 remote）会被正确识别为其 GitHub 源仓库，版本检测、去重与脏检查不受影响。
- 内核版本检测读取 ComfyUI 本地的 `comfyui_version` 模块，不访问网络，与镜像开关无关。

## 提示“找不到 Git”

插件会依次检查 ComfyUI Python 环境、整合包工具目录和进程 `PATH`。comfyui-xiao 自带的 Git 位于 `<整合包根>/.xiaoziya/PortableGit/`，其中 `cmd/git.exe`、`bin/git.exe` 和 `mingw64/bin/git.exe` 均可自动识别，不需要另外安装系统 Git。

如果仍提示找不到 Git，请确认 `.xiaoziya/PortableGit` 没有被杀毒软件隔离且安装包工具下载完整，然后彻底退出并重启 ComfyUI。修复前仍可下载工作流，但无法扫描发布依赖或自动补全 Git 插件。

## 提示“检测到同名非 Git 安装，需要手动移除”

工作流要求的是锁定到完整 commit 的 Git 插件，但 `custom_nodes` 中已存在同名的非 Git 安装（通常来自 Registry 压缩包或其他安装器）。Workflow Hub 无法验证该目录的准确 commit，也不会覆盖或自动删除其中的文件。确认没有需要保留的本地内容后，通过原安装器卸载该插件或手动移除对应目录，再返回下载前检查并点击“重新检查”。

## 订阅源刷新失败

订阅清单读取不依赖匿名 API 配额：已登录 GitHub 时使用用户 token 走 Contents API，未登录时优先走 GitHub Raw CDN 只读地址（带强制刷新参数绕开缓存），两条路径互为其失败时的回退。已有订阅会保留本地缓存作为失败回退，但网页打开和手动刷新都会强制重新校验远端。新订阅或刷新仍失败时，请确认仓库公开、根目录存在 `workflow-catalog.json`，并检查网络、VPN 或 TUN 模式。订阅无需 GitHub 登录。

## 新仓库无法发布

仓库必须公开，并且 GitHub App installation 必须包含该仓库。授权后刷新仓库列表。插件不支持 Personal Access Token 或私有仓库绕过此限制。

## Manager 不可用

工作流仍可下载。GitHub 依赖使用 ComfyUI 环境中的 Git；历史 Registry 依赖才需要 ComfyUI-Manager `3.0+`（legacy API）或 `4.2.1+`（v2 API）。补全开始前会检查下载端点；如果提示无法连接，请检查网络、VPN 或 TUN 模式。Git、Python requirements 与 Manager 环境变更会按插件串行执行，日志和 Manager post-install 结果都会进入同一安装详情；操作记录按用户持久化，安装或升级后重启 ComfyUI 即可。Manager 3.x 下如果队列任务被拒绝并返回 403，需把 Manager 的 `security_level` 调整为 `middle` 或更低（默认 `normal` 即可）。

## 本地插件存在未提交改动或本地独有提交

更新 Workflow Hub 后重新点击同步即可自动修复旧版本遗留的这两类状态。同步会先把 tracked/untracked 未提交改动保存到 `refs/workflow-hub/backups/*`，再刷新插件远端分支；远端引用过期但提交其实已经公开的情况会直接继续。若刷新后仍存在真正仅存于本地的 commit，还会创建 `workflow-hub-backup/<短提交>-<时间>` 备份分支。Python `requirements.txt` 若在仓库内生成文件或修改，也会保存到独立备份引用并恢复干净工作副本。

活动详情会列出所有备份引用。完成后当前工作副本位于干净的远端跟踪分支，不会停在备份分支或游离态，因此启动器和 ComfyUI-Manager 仍可正常识别并更新。需要恢复未提交内容时，可在对应插件目录执行 `git stash apply <活动详情中的 refs/workflow-hub/backups/...>`；备份引用会继续保留，不会因应用而删除。

## 同版本下载失败

如果目标版本文件已存在但内容与安装记录不一致，插件会拒绝覆盖。保留修改版，或在界面明确删除该已记录版本后重新下载。

## 文件已经删除但仍显示已下载

插件会在读取工作流目录时核对 `installed.json` 与真实文件。通过 ComfyUI 或资源管理器删除工作流后，重新打开工作流中心即可自动清除失效的已下载状态。

## 发布停在待同步

这表示 Release 已发布，但包含版本目录、产品资料、README 和根清单的仓库提交失败。修复仓库权限或网络后从待同步发布重试；恢复会读取已生成的 ZIP，不要删除本地草稿包或手动创建同 tag Release。
