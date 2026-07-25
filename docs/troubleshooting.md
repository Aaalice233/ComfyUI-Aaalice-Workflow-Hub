# 故障排查

## 顶栏没有“工作流中心”

确认 ComfyUI Frontend 为 `1.33.9+`，重启 ComfyUI，并在启动日志中检查插件 Python 导入错误。插件使用 `WEB_DIRECTORY` 加载 `web/comfyui/workflow_hub.js`。

## 发布页无法读取当前画布

发布器只读取当前 ComfyUI 画布。请从 ComfyUI 顶栏打开工作流中心，不要直接访问 `/workflow-hub` 页面；打开后核对发布页顶部显示的工作流文件名。

## GitHub 登录无法开始

检查 GitHub App Client ID 是否已配置。可使用环境变量 `WORKFLOW_HUB_GITHUB_CLIENT_ID` 覆盖内置值，修改后重启 ComfyUI。Device Flow 授权过期时重新开始。

## 提示“GitHub 登录已失效，请重新登录”

已存储的 token 过期或被撤销（例如在 GitHub 设置中取消了授权）。插件在 GitHub 返回 401 时会自动清除失效凭据并按未登录处理，重新登录即可。订阅与下载不使用该凭据，不受登录态影响。

## 新仓库无法发布

仓库必须公开，并且 GitHub App installation 必须包含该仓库。授权后刷新仓库列表。插件不支持 Personal Access Token 或私有仓库绕过此限制。

## Manager 不可用

工作流仍可下载。插件依赖计划会降级为说明，不会尝试自行安装。安装或升级 ComfyUI-Manager `4.2.1+` 后重启。

## 同版本下载失败

如果目标版本文件已存在但内容与安装记录不一致，插件会拒绝覆盖。保留修改版，或在界面明确删除该已记录版本后重新下载。

## 文件已经删除但仍显示已下载

插件会在读取工作流目录时核对 `installed.json` 与真实文件。通过 ComfyUI 或资源管理器删除工作流后，重新打开工作流中心即可自动清除失效的已下载状态。

## 发布停在待同步

这表示 Release 已发布，但包含版本目录、产品资料、README 和根清单的仓库提交失败。修复仓库权限或网络后从待同步发布重试；恢复会读取已生成的 ZIP，不要删除本地草稿包或手动创建同 tag Release。
