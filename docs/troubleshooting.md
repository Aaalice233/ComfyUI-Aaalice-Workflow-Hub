# 故障排查

## 顶栏没有“工作流中心”

确认 ComfyUI Frontend 为 `1.33.9+`，重启 ComfyUI，并在启动日志中检查插件 Python 导入错误。插件使用 `WEB_DIRECTORY` 加载 `web/comfyui/workflow_hub.js`。

## 工作流文件无法上传

发布入口只接受不超过 10 MiB 的 JSON 文件。确认文件扩展名为 `.json`、内容是合法 JSON 对象，并且文件没有被其他程序占用。

## GitHub 登录无法开始

检查 GitHub App Client ID 是否已配置。可使用环境变量 `WORKFLOW_HUB_GITHUB_CLIENT_ID` 覆盖内置值，修改后重启 ComfyUI。Device Flow 授权过期时重新开始。

## 新仓库无法发布

仓库必须公开，并且 GitHub App installation 必须包含该仓库。授权后刷新仓库列表。插件不支持 Personal Access Token 或私有仓库绕过此限制。

## Manager 不可用

工作流仍可下载。节点依赖计划会降级为说明，不会尝试自行安装。安装或升级 ComfyUI-Manager `4.2.1+` 后重启。

## 同版本下载失败

如果目标版本文件已存在但内容与安装记录不一致，插件会拒绝覆盖。保留修改版，或在界面明确删除该已记录版本后重新下载。

## 发布停在待同步

这表示 Release 已发布但 `workflow-catalog.json` 更新失败。修复仓库权限或网络后从待同步发布重试；不要手动创建同 tag Release。
