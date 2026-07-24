# 工作流目录与包协议 v1

## 仓库目录

公开仓库默认分支根目录必须包含 `workflow-catalog.json`，并符合 [`schemas/workflow-catalog.schema.json`](../schemas/workflow-catalog.schema.json)。完整合法样例见 [`examples/valid/workflow-catalog.json`](../examples/valid/workflow-catalog.json)。

版本只接受 `major.minor` 或 `major.minor.patch`。比较和重复检测时 `1.12` 等价于 `1.12.0`，显示和文件名仍保留作者输入的 `1.12`。同一工作流产品不得发布规范化后重复的版本。

工作流产品可声明一个可选的 `category` 字符串。类别只有一层，不使用父子关系或树形路径；客户端从仓库中已有工作流的 `category` 聚合可选项，新类别在首个工作流发布后随目录写入。

固定命名：

```text
Release tag: {workflow-id}-v{version}
ZIP asset:   {workflow-id}-v{version}.zip
```

## 包内容

ZIP 根目录只允许：

```text
manifest.json       必需
workflow.json       必需
README.md           可选
CHANGELOG.md        必需
preview.png/webp    旧版兼容，可选且最多一个
inputs/*             可选，仅限 Load Image 引用的受支持图像
```

除 `inputs/` 外不得包含子目录；不得包含模型、第三方节点代码、脚本、可执行文件、符号链接或额外文件。`manifest.inputs` 必须逐项声明原工作流引用、包内路径、大小、SHA-256 和节点 ID；版本目录中的 `versions[].inputs` 保存相同的公开元数据，供订阅详情在下载前展示。安装时图像写入 `input/Workflow Hub/{owner-repo}/{workflow-id}/`，已安装工作流中的引用同步改写。旧目录可以省略 `versions[].inputs`，客户端按空清单处理。

作者选择发布的 LoRA 使用独立 GitHub Release asset，并以版本 `models` 中 `type: "loras"` 的条目声明。发布端与订阅端都逐项展示 `custom_nodes`、`inputs` 和 LoRA 条目。LoRA 不属于 ZIP，订阅端只能由用户逐项主动下载。`manifest.json` 的示例见 [`examples/package/manifest.json`](../examples/package/manifest.json)。

旧目录可在产品层保留 `cover`，旧版本也可保留 `preview`。客户端继续读取这些字段以兼容既有内容，但当前发布器不再提供封面上传，也不会为新工作流创建封面资源。

## 不可变性

已发布的版本号、Release tag 和 Release assets 不得覆盖或删除。工作流产品的名称、简介、说明、标签和归档状态可以通过目录提交修改。归档不会使历史版本失效。

## URL

目录和包内资源必须使用 HTTPS。插件只接受由 GitHub API 返回或属于受信任 GitHub 主机的地址，不接受目录作者指定的任意下载主机。
