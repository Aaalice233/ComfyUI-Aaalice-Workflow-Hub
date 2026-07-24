# 作者发布指南

1. 在“发布工作流”上传不超过 10 MiB 的本地 JSON 工作流文件，并按需扫描节点依赖。
2. 进入下一步，登录 GitHub 并选择已授权的公共仓库；也可创建公共仓库。新仓库需要先安装公开的 [Aaalice Workflow Hub Publisher](https://github.com/apps/aaalice-workflow-hub-publisher) 并将仓库加入 installation。
3. 填写稳定 ID 和展示资料。
4. 填写 `1.12` 或 `1.12.3` 形式的版本和更新日志，并复核节点依赖。能映射到 Comfy Registry 的依赖填写 `registry_id` 和作者测试版本；其余依赖标记 `manual: true`。
5. 按需声明模型名称、类型、文件名、来源链接和可选 SHA-256。
6. 在最后一步先校验，再发布。发布顺序为 Draft Release、ZIP 上传、Release 发布、目录条件更新。

发布版本不可覆盖或删除。目录并发修改会自动合并重试一次；若 Release 已发布但目录更新失败，“待同步发布”会保留恢复信息。

包和目录细节见[协议](protocol.md)，安全限制见[安全边界](security.md)。
