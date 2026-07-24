import { computed, ref } from "vue";

export const locale = ref<"zh" | "en">((localStorage.getItem("workflow-hub-locale") as "zh" | "en") || "zh");

const messages = {
  zh: {
    title: "工作流中心", subscribe: "订阅工作流", publish: "发布工作流", addSource: "添加订阅源",
    sourcePlaceholder: "https://github.com/owner/repo", add: "添加", refresh: "刷新", remove: "移除",
    search: "搜索名称、说明或标签", downloaded: "已下载", updates: "有更新", archived: "已归档",
    all: "全部", noWorkflows: "还没有工作流。先添加一个公共 GitHub 订阅源。",
    versions: "历史版本", changelog: "更新日志", dependencies: "自定义节点依赖", models: "模型声明",
    download: "下载此版本", downloadedTag: "已下载", source: "发布来源", currentCanvas: "当前画布",
    savedWorkflow: "已保存工作流", requestCanvas: "读取当前画布", selectFile: "选择已保存工作流",
    repository: "发布仓库", repositoryName: "目录名称", author: "作者", repositoryDescription: "目录说明", workflowInfo: "工作流资料",
    workflowId: "稳定 ID", name: "名称", summary: "简介", description: "详细说明", tags: "标签（逗号分隔）",
    version: "版本", minComfy: "最低 ComfyUI", maxComfy: "最高 ComfyUI", releaseNotes: "更新日志",
    nodeDeps: "节点依赖 JSON", modelDeps: "模型声明 JSON", validate: "校验", publishNow: "发布",
    login: "登录 GitHub", signedIn: "GitHub 已登录", logout: "退出", githubNotConfigured: "GitHub App Client ID 尚未配置",
    activities: "活动", noActivities: "暂无活动", settings: "设置", close: "关闭",
    confirmEnvironment: "我确认让 ComfyUI-Manager 串行执行所选节点变更", execute: "执行依赖计划",
    managerUnavailable: "Manager 不可用；工作流仍可下载，依赖请手动处理。",
    canvasUnavailable: "当前画布不可用，请保持原 ComfyUI 页面打开或选择已保存工作流。",
    publicOnly: "仅支持公共 GitHub 仓库。已发布版本资产不可覆盖或删除。",
  },
  en: {
    title: "Workflow Hub", subscribe: "Subscribe", publish: "Publish", addSource: "Add subscription",
    sourcePlaceholder: "https://github.com/owner/repo", add: "Add", refresh: "Refresh", remove: "Remove",
    search: "Search names, descriptions, or tags", downloaded: "Downloaded", updates: "Updates", archived: "Archived",
    all: "All", noWorkflows: "No workflows yet. Add a public GitHub subscription.",
    versions: "Versions", changelog: "Changelog", dependencies: "Custom node dependencies", models: "Model declarations",
    download: "Download version", downloadedTag: "Downloaded", source: "Publish source", currentCanvas: "Current canvas",
    savedWorkflow: "Saved workflow", requestCanvas: "Read current canvas", selectFile: "Select saved workflow",
    repository: "Repository", repositoryName: "Catalog name", author: "Author", repositoryDescription: "Catalog description", workflowInfo: "Workflow details",
    workflowId: "Stable ID", name: "Name", summary: "Summary", description: "Description", tags: "Tags (comma-separated)",
    version: "Version", minComfy: "Minimum ComfyUI", maxComfy: "Maximum ComfyUI", releaseNotes: "Release notes",
    nodeDeps: "Node dependencies JSON", modelDeps: "Model declarations JSON", validate: "Validate", publishNow: "Publish",
    login: "Sign in to GitHub", signedIn: "GitHub signed in", logout: "Sign out", githubNotConfigured: "GitHub App Client ID is not configured",
    activities: "Activity", noActivities: "No activity", settings: "Settings", close: "Close",
    confirmEnvironment: "I confirm ComfyUI-Manager may apply selected node changes serially", execute: "Apply dependency plan",
    managerUnavailable: "Manager is unavailable. You can still download; handle dependencies manually.",
    canvasUnavailable: "Current canvas is unavailable. Keep the ComfyUI tab open or choose a saved workflow.",
    publicOnly: "Public GitHub repositories only. Published version assets cannot be overwritten or deleted.",
  },
} as const;

export type MessageKey = keyof typeof messages.zh;
export const t = computed(() => (key: MessageKey) => messages[locale.value][key]);
export function toggleLocale() {
  locale.value = locale.value === "zh" ? "en" : "zh";
  localStorage.setItem("workflow-hub-locale", locale.value);
  document.documentElement.lang = locale.value === "zh" ? "zh-CN" : "en";
}
