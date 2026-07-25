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

版本只接受 `major.minor` 或 `major.minor.patch`。`1.12` 与 `1.12.0` 在重复检测时相等，目录和界面保留作者填写的形式。每个版本目录一经发布不得修改、覆盖或删除。

`product.json` 保存稳定 ID、展示资料、仓库路径和版本索引。名称或类别变化不改变 ID，发布器必须在一次提交中移动完整产品目录并更新根清单和 README。产品封面（`cover`）取自最近一次随版本发布的预览图；发布新版本不带预览时保留已有封面。

## Release 分发

默认分支是可浏览、可备份的正式来源；GitHub Release 是由同一份版本内容生成的分发层：

```text
Release tag: {workflow-id}-v{version}
Release title: {类别} / {工作流名称} v{version}
ZIP asset: {工作流名称}-v{version}.zip
```

ZIP 与对应版本目录中的文件字节一致。Release 还可保存作者选择发布的 LoRA 和预览资源。Release 成功而仓库提交失败时，发布进入“待同步发布”，恢复操作直接读取已经生成并校验的 ZIP，不重新扫描作者的本地资源。

## 版本内容

版本目录和 ZIP 只允许：

```text
manifest.json       必需
workflow.json       必需
README.md           可选
CHANGELOG.md        必需
preview.*           可选且最多一个
inputs/*            可选，仅限 Load Image 引用的受支持图像
```

不得包含模型、第三方节点代码、脚本、可执行文件、符号链接或其它子目录。`manifest.inputs` 必须声明原引用、包内路径、大小、SHA-256 和节点 ID；安装时图像写入 `input/Workflow Hub/{owner-repo}/{workflow-id}/` 并改写工作流引用。

`custom_nodes` 声明 ComfyUI-Manager 插件包，而不是节点类型。带 `registry_id` 的依赖由 Manager 安装；`manual: true` 的依赖必须没有 `registry_id`，并可通过 `source_url` 指向公开 GitHub 仓库。本地 Git clone 若有 `cnr_id`，只发布 Registry ID；commit SHA 不得作为可安装版本。

LoRA 不进入 ZIP 或仓库历史，由 Release asset 分发，并在 `models` 中以 `type: "loras"` 声明。订阅者只能主动逐项下载。

## 发布一致性与安全

发布器使用 GitHub Git Data API，将新版本目录、`product.json`、README 和根清单写入同一个提交。提交基于默认分支 HEAD；并发变化时重新读取一次，同版本或同目录冲突必须拒绝。

所有目录和包内资源使用 HTTPS。插件只接受 GitHub API 返回或属于受信任 GitHub 主机的地址。包安装继续执行大小、哈希、路径穿越、压缩比、重复文件和符号链接检查。
