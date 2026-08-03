# 工作流仓库与包协议

## 仓库结构

公开仓库默认分支必须包含符合 [`schemas/workflow-catalog.schema.json`](../schemas/workflow-catalog.schema.json) 的 `workflow-catalog.json`。它是供插件读取的生成索引，工作流的正式记录保存在可浏览目录中：

```text
workflow-catalog.json
workflows/
  README.md
  {类别}/
    {工作流名称}/
      README.md
      product.json
      versions/
        v{版本}/
          manifest.json
          workflow.json
          CHANGELOG.md
          preview.png/webp/jpg/jpeg
          inputs/*
```

类别、名称和版本均为必填。类别和名称直接作为目录名，保留中文和空格，但不得包含 `<>:"/\|?*`、控制字符、尾随句点或空格，也不得使用系统保留名称。同一类别下的名称必须唯一。

版本只接受 `major.minor` 或 `major.minor.patch`。`1.12` 与 `1.12.0` 在重复检测时相等，目录和界面保留作者填写的形式。已发布版本不可覆盖或复用版本号；仅可由对仓库有写权限的作者通过管理功能删除，删除版本会同时移除对应 Release、tag 和版本目录，删除最后一个版本时整个工作流一并移除。版本的更新日志可以编辑，并同步改写对应 Release notes。

`product.json` 保存稳定 ID、展示资料、仓库路径和版本索引。名称或类别变化不改变 ID，发布器必须在一次提交中移动完整产品目录并更新根清单和 README。产品封面（`cover`）取自最近一次随版本发布的预览图；发布新版本不带预览时保留已有封面。管理页的资料编辑、归档、更新日志和删除以持久化异步操作执行，活动记录使用 `publisher-manage` 类型和与实际动作匹配的阶段；完成后刷新管理列表和订阅缓存，失败时保留阶段、日志和错误。

## Release 分发

默认分支是可浏览、可备份的正式来源；GitHub Release 是由同一份版本内容生成的分发层：

```text
Release tag: {workflow-id}-v{version}
Release title: {类别} / {工作流名称} v{version}
ZIP asset: {工作流名称}-v{version}.zip
```

ZIP 与对应版本目录中的文件字节一致。历史 Release 可保存已发布的 LoRA 和预览资源；新的工作流版本不再上传 LoRA。Release 成功而仓库提交失败时，发布进入“待同步发布”，恢复操作直接读取已经生成并校验的 ZIP，不重新扫描作者的本地资源。

## 版本内容

版本目录和 ZIP 只允许：

```text
manifest.json       必需
workflow.json       必需
README.md           可选
CHANGELOG.md        必需
preview.*           可选且最多一个
inputs/*            可选，仅限画布、子图和侧边栏图像控件引用的受支持图像
```

不得包含模型、第三方节点代码、脚本、可执行文件、符号链接或其它子目录。`manifest.inputs` 必须声明原引用、包内路径、大小、SHA-256 和节点 ID；安装时图像写入当前 ComfyUI 用户专属的 `input/Workflow Hub/{user-hash}/{owner-repo}-{source-hash}/{workflow-id}/` 并改写工作流引用；`user-hash` 来自当前用户目录，`source-hash` 是 owner/repo 小写规范化后的 SHA-256 前 20 位，用于避免不同用户或订阅源目录碰撞。`manifest.filename_separator` 可选为 `-` 或 `_`，用于让安装后的文件名沿用发布者的 `名称-v{版本}.json` 或 `名称_v{版本}.json` 格式；旧包缺少该字段时使用 `-`。

`custom_nodes` 声明插件仓库，而不是节点类型。Git 依赖使用 `manual: true`、`source_url` 和完整 40 位 `commit` 锁定 GitHub 工作副本；历史 Registry 依赖使用 `registry_id` 和语义版本。ComfyUI-Manager 与 ComfyUI-Aaalice-Workflow-Hub 属于宿主基础插件，不写入 `custom_nodes` 依赖声明，也不进入补全计划。发布扫描只读取 `custom_nodes` 下的 Git 工作副本；Git clone/fetch/checkout 可并行执行，随后使用 ComfyUI 环境的 Python 串行处理各插件 `requirements.txt`；历史 Registry 依赖由 Manager 队列负责 post-install。补全开始前会检查 GitHub/Comfy Registry 网络连通性。两种安装方式通过统一且持久化的异步操作报告插件级进度、安装日志、错误结果和重启提示。

新版本发布不得在 ZIP、仓库历史或 `models` 中声明 LoRA。历史版本的 LoRA 由 Release asset 分发，并在 `models` 中以 `type: "loras"` 声明；订阅者只能主动逐项下载。

## API 错误与多语言

需要用户采取行动的后端错误返回稳定的 `error_code` 和可插值的 `error_params`，前端根据当前语言词典显示提示；后端不直接拼接中文或英文操作文案。第三方原始错误和调试诊断信息可以作为 `error` 或操作日志原样保留。

## 发布一致性与安全

发布器使用 GitHub Git Data API，将新版本目录、`product.json`、README 和根清单写入同一个提交。提交基于默认分支 HEAD；并发变化时重新读取一次，同版本或同目录冲突必须拒绝。

所有目录和包内资源使用 HTTPS。插件只接受 GitHub API 返回或属于受信任 GitHub 主机的地址。包安装继续执行大小、哈希、路径穿越、压缩比、重复文件和符号链接检查。
