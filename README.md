<p align="center">
  <img src="assets/banner.png" alt="ComfyUI-Aaalice-Workflow-Hub" width="100%">
</p>

<p align="center">
  <strong>简体中文</strong> · <a href="README.en.md">English</a>
</p>

# ComfyUI-Aaalice-Workflow-Hub

面向 ComfyUI 的公共工作流订阅、发布和版本管理插件。作者和订阅者使用同一个插件；入口是 ComfyUI 顶栏的“工作流中心”按钮，不创建侧边栏。

## 当前能力

- 订阅带 `workflow-catalog.json` 的公共 GitHub 仓库，浏览历史版本、更新日志，以及每个版本的插件依赖、随包图片和可选 LoRA 清单。
- 默认分支按“类别 / 名称 / 版本”保存全部工作流文件，访问仓库即可浏览、备份或直接下载，不必逐个翻找 Release。
- 按版本下载并校验 Release ZIP；Release 只作为安装包和 LoRA 等分发产物，每个本地版本保存为独立工作流文件。
- 直接读取当前 ComfyUI 画布，通过“确认资源、填写信息、确认发布”三个阶段完成发布；版本目录、产品资料、README 和根清单在一次 Git 提交中更新。
- 发布时自动记录作者当前的 ComfyUI 内核版本；订阅者内核不匹配时，下载详情页会显示兼容性警告，但不阻止下载。
- `加载图像` 节点引用的本地图像会自动随包发布；发布时可选上传一张不超过 10 MiB 的封面图，同时作为工作流封面和该版本预览。
- 管理页面向有写权限的作者：编辑资料、归档、编辑版本更新日志，以及删除版本或整个工作流（连同对应 Release 与仓库目录）；订阅侧只提供下载与查看。
- 使用 GitHub App Device Flow 登录；凭据优先保存在系统 keyring，keyring 不可用时仅保留在当前进程。
- 生成 ComfyUI 插件依赖计划，并在用户二次确认后将安装、升级或明确选择的降级任务串行交给 ComfyUI-Manager。
- 中英文界面、启动时工作流更新 Toast、真实下载字节进度、轻量活动抽屉、按 ComfyUI 用户隔离的状态和缓存。

发布页会把实际的 ComfyUI-Manager 插件包、随包图片和 LoRA 逐项列出；节点无法完整映射时，改为列出当前启用的 Manager 插件供作者勾选，不把节点类型冒充插件。Git clone 开发版若有 Registry ID，普通用户仍通过 Manager 安装可用版本，本地 commit 不会被当作版本锁定。作者可选择将 Lora Manager 引用的 LoRA 作为独立 Release 资源发布，也可一键清空当前待发布副本中的引用。LoRA 不进入工作流主包，订阅用户必须自行点击选择是否下载，插件不会自动下载。插件只支持公共 GitHub 仓库，不支持私有仓库、其他 Git 服务或任意下载主机。项目不会静默修改插件环境，也未发布到 Comfy Registry。

## 安装和使用

1. 将本仓库放入 `ComfyUI/custom_nodes/`，执行 `pip install -r requirements.txt` 安装 Python 依赖；通过 ComfyUI-Manager 安装时会自动处理。
2. 重启 ComfyUI，确认 Frontend 为 `1.33.9+`，推荐使用 Manager `4.2.1+`。
3. 点击顶栏“工作流中心”；普通点击在 ComfyUI 内打开非全屏面板，`Shift+点击` 打开独立窗口。
4. 订阅无需 GitHub 登录；发布时按页面提示使用 Device Flow 登录。

运行时数据写入当前 ComfyUI 用户数据目录的 `workflow_hub/`，下载文件位于：

```text
workflows/Workflow Hub/{owner}-{repo}/{workflow-id}/{名称}-v{版本}.json
```

## 文档

- [术语与领域上下文](CONTEXT.md)
- [项目愿景](docs/vision.md)
- [已实现功能](docs/features.md)
- [工作流目录与包协议](docs/protocol.md)
- [作者发布指南（中文）](docs/publisher-guide.zh-CN.md)
- [Publisher guide (English)](docs/publisher-guide.en.md)
- [安全边界](docs/security.md)
- [故障排查](docs/troubleshooting.md)
- [GitHub Device Flow 与直接发布 ADR](docs/adr/0001-github-app-device-flow.md)
- [仓库存档与 Release 分发 ADR](docs/adr/0002-repository-archive-and-release-distribution.md)

开发验证：

```powershell
python -m unittest discover -s tests -v
Set-Location frontend
npm ci
npm test
npm run build
```

## License

[MIT](LICENSE)
