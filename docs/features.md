# 1.0 功能与状态

本文件描述仓库当前实现。规划外能力不会在界面中伪装成可用。

## 已实现

### 顶栏和独立页面

- Frontend `actionBarButtons` 注册顶栏按钮，最低 Frontend `1.33.9`。
- 普通点击使用固定窗口名打开或聚焦 `/workflow-hub`；`Shift+点击` 打开独立窗口。
- 独立页面通过 `BroadcastChannel` 按需读取当前画布，不写浏览器持久存储。
- Vue 3、TypeScript、Vite 源码和生产构建产物同时交付。

### 订阅和下载

- 添加、刷新和移除公共 GitHub 订阅源。
- ETag 缓存；页面启动检查一次，也支持手动刷新，不常驻轮询。
- 聚合目录、搜索、下载/更新/归档筛选、详情和历史版本。
- 下载 GitHub Release 包并验证 HTTPS 主机、大小、SHA-256、ZIP 条目、路径、符号链接、压缩比和解压总量。
- 每个版本写入独立文件；同版本文件内容不一致时报完整性错误。
- 移除订阅不删除已下载文件；本地版本只能由用户明确删除。

### 发布

- GitHub App Device Flow 登录，keyring/session 降级存储。
- 选择当前画布或当前用户目录下的已保存工作流。
- 校验版本、稳定 ID、Release tag、清单和依赖声明。
- 创建 Draft Release、上传 ZIP、发布 Release，再以文件 SHA 条件更新目录。
- 目录并发冲突重新获取并合并一次；Release 已发布而目录同步失败时记录待同步数据，续传不重复创建 Release。

### 依赖与安全

- Registry 依赖与手动依赖分开声明。
- 依赖计划状态：`keep/install/upgrade/newer/conflict/unknown/manual`。
- `newer` 默认保留；手动依赖和冲突不会自动执行。
- 节点环境变更必须二次确认，并串行提交给 Manager。
- Manager 不可用时仍允许下载工作流。
- 模型只允许作者手动声明，不自动下载。
- 写接口限制同源、JSON Content-Type、2 MiB 请求体和当前 ComfyUI 用户。
- 操作日志脱敏，不包含遥测。

## 不在 1.0 范围

- 私有 GitHub 仓库、GitLab、Gitee 或任意资源主机。
- 覆盖/删除已发布 Release 资产。
- 自动下载模型。
- 执行工作流仓库脚本。
- 自动安装、升级、降级、启用节点。
- Comfy Registry 发布或自动发布流程。
