# AGENTS.md

本文件适用于仓库内的全部目录，是开发与协作规范；用户文档见 `README.md`，设计与行为约定见 `docs/`。

## 项目定位

- 本项目是面向 ComfyUI 的通用工作流订阅、分发与版本管理插件。
- 当前 `1.0.1` 已完成可用闭环；文档只能把代码和真实验收已经覆盖的能力描述为已实现。
- 插件本体已发布到 Comfy Registry（发布者 `aaalice`）。发布只能由用户明确要求后，手动执行 `comfy node publish`；不得在代码库中添加自动发布 Registry 的流程。

## 仓库结构

- `workflow_hub/`：Python 后端（aiohttp 路由、GitHub 交互、目录与包处理、依赖计划、存储）。
- `web/comfyui/`：ComfyUI 宿主扩展桥接层（顶栏按钮、面板加载、宿主词典），随 `WEB_DIRECTORY` 加载。
- `web/app/`：Vue 前端的生产构建产物，由 `npm run build` 生成，禁止手工修改。
- `frontend/`：Vue 3 + TypeScript + Vite 前端源码与测试。
- `docs/`：设计、范围和行为约定的事实来源；`docs/adr/` 保存架构决策记录。
- `schemas/`：`workflow-catalog.json` 的 JSON Schema。
- `examples/`：协议示例（含合法与非法样例），供文档和测试引用。
- `tests/`：Python 后端测试（`python -m unittest`）。

## 文档同步规范

- `docs/` 是项目设计、范围和行为约定的事实来源，必须随项目实现同步更新。
- 任何会改变功能范围、用户流程、界面行为、仓库协议、清单格式、版本规则、依赖处理、安全边界或兼容策略的修改，都必须在同一次提交中更新对应的 `docs/` 文档。
- 新增、删除或重命名功能时，必须同步检查 `README.md`、`docs/vision.md` 和 `docs/features.md`。
- 文档必须明确区分“已实现”“开发中”“计划中”和“不在当前范围”，不得让规划内容看起来已经可用。
- 如果代码行为与文档不一致，应在合入前同时修正，不能只改一侧。
- 新增独立设计主题时，应在 `docs/` 中新增文档，并从现有文档或 `README.md` 建立入口。
- 文档职责区分：`README.md`/`README.en.md` 只面向用户（功能、安装、使用、边界、文档入口）；`AGENTS.md` 只写长期有效的开发规范，不记录具体问题的排障笔记；`docs/troubleshooting.md` 面向用户的故障排查；`docs/adr/` 记录不可轻易推翻的架构决策及其背景。

## 开发原则

- 修改前先确认 ComfyUI、ComfyUI-Manager 的当前接口和真实行为，不凭印象实现。
- 优先使用 ComfyUI 与 ComfyUI-Manager 提供的公开接口；不要复制它们的内部安装逻辑。
- 插件不得静默安装、升级、降级、启用或禁用第三方节点。改变环境前必须展示计划并取得用户确认。
- 不执行工作流仓库中的任意脚本，不允许压缩包路径穿越，不自动下载模型或 LoRA。
- 节点安装任务默认串行执行；只有下载、校验等不会同时修改环境的步骤才可受控并行。
- 真实进度无法获得时展示阶段、任务状态和日志，不伪造百分比。
- 保持实现简单，优先完成最小可用闭环，不为尚未确定的需求提前建立复杂抽象。
- 仅修改当前任务涉及的内容，不覆盖或清理用户已有改动。

## 代码与界面

- Python 代码保持清晰类型与职责边界，错误应保留原始原因和可定位上下文。
- 发布页的插件依赖必须展示 ComfyUI-Manager 插件包，不得把未解析的工作流节点类型伪装成插件。发布页直接列出当前用户已安装的全部 Manager 插件，并要求作者取消勾选无关项目后确认发布清单。
- 本地 Git clone 插件若有 `cnr_id`，发布 Registry ID 且不得把 commit SHA 当作可安装版本；无 `cnr_id` 时按 GitHub 手动依赖声明。
- 有限高度的发布面板不得同时堆叠步骤导航、阶段编号、阶段标题和说明；底部前进/返回操作足以表达流程时，正文直接展示当前阶段内容。
- 用户可见辅助文字不得小于 12px，正文、表单与操作文字不得小于 14px；文字须有足够对比度、行高和层级，禁止靠缩小字号或降低透明度换取“紧凑”。
- 前端状态变化不得导致列表宽度或组件尺寸抖动。
- 弹窗、卡片、输入框和按钮优先采用无边框设计；分段控件滑块、Tab 选中层、筛选高亮层等状态指示层同样不得使用 `border` 或 1px `inset` 描边。优先通过背景明度、留白、轻微内侧高光和柔和阴影表达边缘、层级与选中状态。
- 重要操作、选中、聚焦、加载、失败和重试状态必须清晰可见。

## 前端国际化

- 用户可见文案只能存在于对应运行面的词典：内置 Vue 页面使用 `frontend/src/i18n.ts`，ComfyUI 宿主扩展桥接层使用 `web/comfyui/i18n.js`。新增或修改文案时，必须同时补齐中文和英文词典项。
- Vue 组件和普通 TypeScript 业务代码中禁止硬编码中文文案，也禁止使用 `locale === "zh" ? ... : ...`、`locale.value` 分支或其它方式内联维护双语文案；统一通过 `t("key")` 获取。
- `web/comfyui/workflow_hub.js` 同样禁止硬编码中文、双语拼接和 `isChinese` 文案分支；统一通过宿主词典的 `translateHost()` 获取。HTML `<title>` 使用不需翻译的产品专名。
- 包含名称、数量、版本等动态内容的文案必须使用词典命名参数，例如 `t("managerTasksQueued", { count })`；不得在组件中分别拼接中英文句子。
- 专有名词、协议字段、文件名、版本号、单位和后端返回的原始诊断错误可以按原值显示；其周围的说明、标签和操作文案仍必须进入词典。
- 后端新增的可操作用户错误不得拼接中文或英文提示；应返回稳定的 `error_code` 和 `error_params`，由前端通过 `frontend/src/i18n.ts` 映射并插值。异步操作也必须传递同一错误码，不能把本地化文案写入日志协议。
- 只有第三方原始错误、文件名和调试诊断信息可以原样展示；如果错误需要用户采取行动，行动说明、按钮和数量等动态内容必须进入中英文词典。
- 修改词典或用户文案后，必须运行 `frontend` 的 i18n 测试和生产构建。`i18n.test.ts` 必须持续检查参数插值，并阻止 `App.vue`、`workflow_hub.js` 和入口 HTML 重新出现词典外中文或语言条件分支。

## 开发命令

```powershell
# Python 后端测试（仓库根目录）
python -m unittest discover -s tests -v

# 前端依赖、测试与生产构建（产物写入 web/app/）
Set-Location frontend
npm ci
npm test
npm run build
```

## 验证

- 提交前至少检查 Python 导入、清单/配置格式、文档链接和资源文件。
- 行为变化应执行与风险相匹配的最小测试；无法验证的部分必须在交付说明中明确指出。
- 前端修改无论是小型视觉调整，还是涉及多个组件、交互、响应式布局或运行时状态的中等规模改动，默认只做静态检查、必要构建和相关自动化测试，不启动 ComfyUI 测试实例或浏览器自动验收。只有用户明确要求进行 GUI 验证时，才启动独立实例和浏览器。
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

## 提交规范

- 提交信息使用 `type(scope): 中文描述`，标题不超过 72 个字符；`type` 取 `feat`/`fix`/`refactor`/`perf`/`style`/`docs`/`test`/`chore`。
