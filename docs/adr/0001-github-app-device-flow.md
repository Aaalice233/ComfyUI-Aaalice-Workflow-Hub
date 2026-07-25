# ADR-0001：使用 GitHub App Device Flow 直接发布

- 状态：已接受
- 日期：2026-07-24

## 背景

作者需要从本地 ComfyUI 插件创建公开仓库、上传 Release 和更新目录。插件不能打包 Client Secret、Private Key 或长期明文 Token，也不能要求作者手工复制 Personal Access Token。

## 决策

使用公开可安装的 GitHub App 和 Device Flow。插件只包含公开 Client ID，环境变量可以覆盖。Token 优先存入系统 keyring，keyring 不可用时仅保留在当前进程。

GitHub App 权限为 Metadata 只读、Contents 读写、Administration 读写；不启用 webhook。发布采用 Draft Release → 上传 assets → 发布 Release → Git Data 原子提交仓库存档的事务。分支并发冲突合并重试一次，Release 成功而仓库存档失败时记录待同步状态。

## 结果

- 本地客户端无需保存 GitHub App 私钥或 Client Secret。
- 用户能在 GitHub 页面查看授权范围并撤销。
- 新仓库仍需被加入 GitHub App installation。
- 发布依赖 GitHub 服务和安装授权；离线时只能编辑本地资料，不能模拟发布成功。
