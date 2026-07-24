# 工作流目录与包协议 v1

## 仓库目录

公开仓库默认分支根目录必须包含 `workflow-catalog.json`，并符合 [`schemas/workflow-catalog.schema.json`](../schemas/workflow-catalog.schema.json)。完整合法样例见 [`examples/valid/workflow-catalog.json`](../examples/valid/workflow-catalog.json)。

版本只接受 `major.minor` 或 `major.minor.patch`。比较和重复检测时 `1.12` 等价于 `1.12.0`，显示和文件名仍保留作者输入的 `1.12`。同一工作流产品不得发布规范化后重复的版本。

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
preview.png/webp    可选，最多一个
```

不得包含子目录、模型、第三方节点代码、脚本、可执行文件、符号链接或额外文件。`manifest.json` 的示例见 [`examples/package/manifest.json`](../examples/package/manifest.json)。

## 不可变性

已发布的版本号、Release tag 和 Release assets 不得覆盖或删除。工作流产品的名称、简介、说明、标签和归档状态可以通过目录提交修改。归档不会使历史版本失效。

## URL

目录和包内资源必须使用 HTTPS。插件只接受由 GitHub API 返回或属于受信任 GitHub 主机的地址，不接受目录作者指定的任意下载主机。
