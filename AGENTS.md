# AGENTS.md

本文件适用于仓库内的全部目录。

## 项目定位

- 本项目是面向 ComfyUI 的通用工作流订阅、分发与版本管理插件。
- 当前 `1.0.0` 已完成可用闭环；文档只能把代码和真实验收已经覆盖的能力描述为已实现。
- 在用户明确决定前，不得发布到 Comfy Registry，也不得添加自动发布 Registry 的流程。

## 文档同步规范

- `docs/` 是项目设计、范围和行为约定的事实来源，必须随项目实现同步更新。
- 任何会改变功能范围、用户流程、界面行为、仓库协议、清单格式、版本规则、依赖处理、安全边界或兼容策略的修改，都必须在同一次提交中更新对应的 `docs/` 文档。
- 新增、删除或重命名功能时，必须同步检查 `README.md`、`docs/vision.md` 和 `docs/features.md`。
- 文档必须明确区分“已实现”“开发中”“计划中”和“不在当前范围”，不得让规划内容看起来已经可用。
- 如果代码行为与文档不一致，应在合入前同时修正，不能只改一侧。
- 新增独立设计主题时，应在 `docs/` 中新增文档，并从现有文档或 `README.md` 建立入口。

## 开发原则

- 修改前先确认 ComfyUI、ComfyUI-Manager 的当前接口和真实行为，不凭印象实现。
- 优先使用 ComfyUI 与 ComfyUI-Manager 提供的公开接口；不要复制它们的内部安装逻辑。
- 插件不得静默安装、升级、降级、启用或禁用第三方节点。改变环境前必须展示计划并取得用户确认。
- 不执行工作流仓库中的任意脚本，不允许压缩包路径穿越，不把模型下载混入首个版本。
- 节点安装任务默认串行执行；只有下载、校验等不会同时修改环境的步骤才可受控并行。
- 真实进度无法获得时展示阶段、任务状态和日志，不伪造百分比。
- 保持实现简单，优先完成最小可用闭环，不为尚未确定的需求提前建立复杂抽象。
- 仅修改当前任务涉及的内容，不覆盖或清理用户已有改动。

## 代码与界面

- Python 代码保持清晰类型与职责边界，错误应保留原始原因和可定位上下文。
- 前端状态变化不得导致列表宽度或组件尺寸抖动。
- 弹窗、卡片、输入框和按钮优先使用低对比度、无高对比描边的样式，通过间距和柔和阴影表达层级。
- 重要操作、选中、聚焦、加载、失败和重试状态必须清晰可见。

## 验证

- 提交前至少检查 Python 导入、清单/配置格式、文档链接和资源文件。
- 行为变化应执行与风险相匹配的最小测试；无法验证的部分必须在交付说明中明确指出。
- 用户通常已在 `127.0.0.1:8188` 运行日常 ComfyUI。自动验收不得停止、复用、重启或修改该实例。
- 独立测试实例默认使用 `127.0.0.1:8189`；若端口已占用，依次选择其它空闲端口。
- 测试实例必须同时隔离 `user-directory`、数据库和日志；只设置 `--user-directory` 不足以保证隔离。
- 临时目录统一放在 `../../../logs/codex-e2e-<timestamp>/`，验收结束后只清理本轮创建的资源。
- 启动前记录命令、PID、端口和日志路径；以日志中的 `To see the GUI go to:` 与 `web root:` 判断是否就绪，不凭启动命令猜测。
- 停止前必须再次核对 PID、命令行和监听端口确属本轮测试实例，禁止误停用户实例。
- GUI 自动验收只使用 Codex 内置浏览器，并在独立实例的空白工作流中进行；不得覆盖用户未保存的工作流。

独立测试实例示例（端口按实际空闲值替换）：

```powershell
$ErrorActionPreference = 'Stop'

$comfyRoot = (Resolve-Path '../..').Path
$python = (Resolve-Path '../../.venv/Scripts/python.exe').Path
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$runRoot = Join-Path (Resolve-Path '../../../logs').Path "codex-e2e-$stamp"
$userDir = Join-Path $runRoot 'user'
$dbPath = (Join-Path $runRoot 'comfyui.db').Replace('\', '/')
$stdoutPath = Join-Path $runRoot 'stdout.log'
$stderrPath = Join-Path $runRoot 'stderr.log'
$port = 8189

New-Item -ItemType Directory -Force -Path $userDir | Out-Null

$arguments = @(
    'main.py',
    '--listen', '127.0.0.1',
    '--port', "$port",
    '--user-directory', $userDir,
    '--database-url', "sqlite:///$dbPath"
)

$process = Start-Process -FilePath $python `
    -ArgumentList $arguments `
    -WorkingDirectory $comfyRoot `
    -RedirectStandardOutput $stdoutPath `
    -RedirectStandardError $stderrPath `
    -WindowStyle Hidden `
    -PassThru

"PID=$($process.Id) URL=http://127.0.0.1:$port STDOUT=$stdoutPath STDERR=$stderrPath"
```

停止测试实例前核对：

```powershell
$candidate = Get-CimInstance Win32_Process -Filter "ProcessId = $($process.Id)"
$candidate | Select-Object ProcessId, ExecutablePath, CommandLine
Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
```

确认命令行、PID 和端口属于本轮实例后，才可执行 `Stop-Process -Id $process.Id`。

- 提交信息使用 `type(scope): 中文描述`，标题不超过 72 个字符。
