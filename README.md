<p align="center">
  <img src="assets/banner.png" alt="ComfyUI-Aaalice-Workflow-Hub" width="100%">
</p>

# ComfyUI-Aaalice-Workflow-Hub

面向 ComfyUI 的公共工作流订阅、发布和版本管理插件。作者和订阅者使用同一个插件；入口是 ComfyUI 顶栏的“工作流中心”按钮，不创建侧边栏。

## 1.0 能力

- 订阅带 `workflow-catalog.json` 的公共 GitHub 仓库，浏览历史版本、更新日志、节点依赖和模型声明。
- 按版本下载并校验 Release 包；每个版本保存为独立工作流文件，绝不覆盖旧版本。
- 从当前画布或用户目录中的已保存工作流直接发布 GitHub Release。
- 使用 GitHub App Device Flow 登录；凭据优先保存在系统 keyring，keyring 不可用时仅保留在当前进程。
- 生成自定义节点依赖计划，并在用户二次确认后将安装、升级或明确选择的降级任务串行交给 ComfyUI-Manager。
- 中英文界面、真实下载字节进度、轻量活动抽屉、按 ComfyUI 用户隔离的状态和缓存。

模型只做声明和查看，不自动下载。插件只支持公共 GitHub 仓库，不支持私有仓库、其他 Git 服务或任意下载主机。项目不会静默修改节点环境，也未发布到 Comfy Registry。

## 安装和使用

1. 将本仓库放入 `ComfyUI/custom_nodes/`，安装 `pyproject.toml` 中的 Python 依赖。
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
