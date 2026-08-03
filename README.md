<p align="center">
  <img src="assets/banner.png" alt="ComfyUI-Aaalice-Workflow-Hub" width="100%">
</p>

<p align="center">
  <strong>简体中文</strong> · <a href="README.en.md">English</a>
</p>

# ComfyUI-Aaalice-Workflow-Hub

面向 ComfyUI 的公共工作流订阅、发布和版本管理插件。作者和订阅者使用同一个插件；入口是 ComfyUI 顶栏的“工作流中心”按钮，不创建侧边栏。

## 功能

### 订阅与下载

- 订阅带 `workflow-catalog.json` 的公共 GitHub 仓库，在聚合目录中搜索、筛选并浏览历史版本和更新日志。
- 仓库默认分支按“类别 / 名称 / 版本”保存全部工作流文件，访问仓库即可浏览、备份或直接下载，不必逐个翻找 Release。
- 按版本下载并校验 Release ZIP；每个本地版本保存为独立工作流文件，可从详情页直接打开所在目录。
- 详情页保留已发布版本的插件依赖、随包图片和 LoRA 清单；历史 LoRA 必须逐项主动下载，绝不自动下载。
- 发布时记录打包所用的 ComfyUI 内核版本；内核不匹配时下载页显示兼容性警告，但不阻止下载。
- 插件依赖生成只读计划；补全前自动检查网络，新 Git 依赖由 ComfyUI 环境中的 Git 并行按锁定 commit 补全，插件 Python `requirements.txt` 安装计入同一进度和日志，历史 Registry 依赖交给 ComfyUI-Manager；两种来源使用不同徽章并在同一界面持久化展示进度、状态、日志和错误结果；补全不可用时仍可正常下载。

### 发布与管理

- 直接读取当前 ComfyUI 画布，按“确认资源、填写信息、确认发布”三个阶段完成发布；自动识别文件名末尾的 `-v{版本}` 或 `_v{版本}` 并填入名称和版本，下载后的不同版本使用带版本号的独立文件。
- 活动面板以五段进度条显示发布或待同步续传的当前阶段，并保留操作状态、日志和错误信息。
- 发布时同时扫描当前 `custom_nodes` 下的 Git 插件仓库和 ComfyUI-Manager 已安装插件，用不同徽章区分来源；作者可取消勾选与工作流无关的插件，Git 依赖锁定 GitHub 地址和完整 commit，Manager 依赖锁定 Registry ID 和版本；同时处理画布、子图和侧边栏图像控件的随包图片。检测到 LoRA 引用时仅显示警告，不阻止继续发布；LoRA 不会被自动打包或下载。
- 可选上传封面图（不超过 10 MiB），同时作为工作流封面和版本预览。
- 管理页面向有写权限的作者：直接打开所选 GitHub 仓库原址，编辑资料、归档、编辑版本更新日志、删除版本或整个工作流；订阅侧只提供下载与查看。
- 使用 GitHub App Device Flow 登录；凭据优先保存在系统 keyring，keyring 不可用时仅保留在当前进程。

### 通用

- 中英文界面自动跟随 ComfyUI 语言设置。
- 启动时工作流更新 Toast、真实下载字节进度、轻量活动抽屉。
- 状态和缓存按 ComfyUI 用户隔离。

## 安装

**方式一（推荐）**：在 ComfyUI-Manager 中搜索 `ComfyUI-Aaalice-Workflow-Hub` 安装。插件已发布到 Comfy Registry，Python 依赖由 Manager 自动处理。

**方式二（手动）**：将本仓库放入 `ComfyUI/custom_nodes/`，执行 `pip install -r requirements.txt`。

要求 ComfyUI Frontend `1.33.9+`；支持 ComfyUI-Manager `3.0+`，推荐 `4.2.1+`。

## 使用

1. 重启 ComfyUI，点击顶栏“工作流中心”；普通点击在 ComfyUI 内打开非全屏面板，`Shift+点击` 打开独立窗口。
2. 订阅无需 GitHub 登录；发布时按页面提示使用 Device Flow 登录。
3. 作者首次发布前，需将公开的 [Aaalice Workflow Hub Publisher](https://github.com/apps/aaalice-workflow-hub-publisher) GitHub App 安装到目标仓库，详见[作者发布指南](docs/publisher-guide.zh-CN.md)。

运行时数据写入当前 ComfyUI 用户数据目录的 `workflow_hub/`，下载文件位于：

```text
workflows/Workflow Hub/{owner}-{repo}-{source-hash}/{workflow-id}/{名称}-v{版本}.json
```

## 边界

- 只支持公共 GitHub 仓库，不支持私有仓库、其他 Git 服务或任意下载主机。
- 不自动下载模型或 LoRA，不静默安装、升级或降级节点，不执行工作流仓库中的脚本。
- 已发布版本不可覆盖；本地已下载文件只能由用户明确删除。

## 文档

- [作者发布指南（中文）](docs/publisher-guide.zh-CN.md) · [Publisher guide (English)](docs/publisher-guide.en.md)
- [故障排查](docs/troubleshooting.md)
- [工作流目录与包协议](docs/protocol.md)
- [安全边界](docs/security.md)
- 设计与决策：[项目愿景](docs/vision.md) · [已实现功能](docs/features.md) · [术语与领域上下文](docs/context.md) · [ADR 目录](docs/adr/)

## License

[MIT](LICENSE)
