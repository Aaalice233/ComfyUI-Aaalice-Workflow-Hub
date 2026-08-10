<p align="center">
  <img src="assets/banner.png" alt="ComfyUI-Aaalice-Workflow-Hub" width="100%">
</p>

<p align="center">
  <strong>简体中文</strong> · <a href="README.en.md">English</a>
</p>

# ComfyUI-Aaalice-Workflow-Hub

面向 ComfyUI 的公共工作流订阅、发布和版本管理插件。作者和订阅者使用同一个插件，入口是 ComfyUI 顶栏的“工作流中心”按钮。

## ✨ 功能

### 📥 订阅与下载

- 订阅含 `workflow-catalog.json` 的公共 GitHub 仓库，在聚合目录中搜索、筛选，浏览历史版本与更新日志。
- 按版本下载并校验工作流包：工作流写入当前用户的 `workflows/`，随包图片写入 `input/` 且引用保持不变；下载后可直接打开目录，也可按 ComfyUI 原生文件身份加载到当前画布并保留文件名。
- ComfyUI 原生更新通知（默认每 4 小时静默检查，可配置开关与 1–168 小时间隔），新版本弹一次原生 Toast，未下载的更新在顶栏按钮上持续显示角标。
- 下载前自动检查内核与插件依赖，发现差异先弹窗说明，可跳过检查或先同步插件再重新检查；内核不会被自动修改。
- 插件一键补全：Git 依赖按锁定 commit 安装并自动处理 `requirements.txt`，历史 Registry 依赖交给 ComfyUI-Manager；任务全局串行且重复请求复用同一操作，远端引用过期会自动刷新，未提交改动和真正的本地独有 commit 会先保存到独立 Git 备份引用，完成后工作副本保持干净的正常远端跟踪分支而非游离态；同一界面展示进度、逐插件日志和错误，补全不可用时仍可正常下载。

### 📤 发布与管理

- 从当前画布直接发布，按“资源确认、填写信息、确认、完成”四个阶段引导；自动识别文件名中的版本号。
- 自动扫描 `custom_nodes` 下的 Git 插件并锁定 GitHub 地址与完整 commit，可取消勾选无关插件；随包图片自动打包；检测到 LoRA 仅警告，不打包、不下载。
- 可选上传封面图（不超过 10 MiB），同时用作工作流封面和版本预览。
- 管理页支持编辑资料、归档、编辑更新日志、删除版本或整个工作流；更新日志可直接从本地 Markdown 文件导入；所有操作在活动面板中展示阶段进度、日志和结果，历史记录可清理。
- 使用 GitHub Device Flow 登录，凭据优先保存在系统 keyring。

### 🌐 通用

- 中英文界面自动跟随 ComfyUI 语言设置。
- 自动适配秋叶（绘世）启动器的 Git/PyPI 国内镜像，识别 comfyui-xiao 自带的 PortableGit，并继承 Windows 系统代理。
- 状态与缓存按 ComfyUI 用户隔离。

## 📦 安装

**方式一（推荐）**：在 ComfyUI-Manager 中搜索 `ComfyUI-Aaalice-Workflow-Hub` 安装，Python 依赖由 Manager 自动处理。

**方式二（手动）**：将本仓库放入 `ComfyUI/custom_nodes/`，执行 `pip install -r requirements.txt`。

要求 ComfyUI Frontend `1.33.9+`；支持 ComfyUI-Manager `3.0+`，推荐 `4.2.1+`。

## 🚀 使用

1. 重启 ComfyUI，点击顶栏“工作流中心”；普通点击在 ComfyUI 内打开面板，`Shift+点击` 打开独立窗口。
2. 订阅无需 GitHub 登录；发布时按页面提示使用 Device Flow 登录。
3. 作者首次发布前，需将公开的 [Aaalice Workflow Hub Publisher](https://github.com/apps/aaalice-workflow-hub-publisher) GitHub App 安装到目标仓库，详见[作者发布指南](docs/publisher-guide.zh-CN.md)。

下载产物位置：

```text
user/{当前用户}/workflows/{名称}-v{版本}.json
input/{工作流原图像引用}
```

## ⚠️ 边界

- 只支持公共 GitHub 仓库，不支持私有仓库、其他 Git 服务或任意下载主机。
- 不自动下载模型或 LoRA，不静默安装、升级或降级节点，不执行工作流仓库中的脚本。
- 已发布版本不可覆盖；本地已下载文件只能由用户明确删除。

## 📚 文档

- [作者发布指南（中文）](docs/publisher-guide.zh-CN.md) · [Publisher guide (English)](docs/publisher-guide.en.md)
- [故障排查](docs/troubleshooting.md)
- [工作流目录与包协议](docs/protocol.md)
- [安全边界](docs/security.md)

## 📄 License

[MIT](LICENSE)
