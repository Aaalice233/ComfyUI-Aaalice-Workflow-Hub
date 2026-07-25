import { computed, ref } from "vue";

export type Locale = "zh" | "en";

export function resolveLocale(value?: string | null): Locale {
  return value?.toLowerCase().startsWith("zh") ? "zh" : "en";
}

export const locale = ref<Locale>(resolveLocale(navigator.language));

const messages = {
  zh: {
    title: "工作流中心", subscribe: "订阅工作流", publish: "发布工作流", addSource: "添加订阅源",
    sourcesLabel: "订阅源", emptyTitle: "暂无工作流", emptyFiltered: "没有符合当前搜索或筛选条件的工作流。",
    sourcePlaceholder: "https://github.com/owner/repo", add: "添加", refresh: "刷新", refreshAll: "刷新全部", allSourcesRefreshed: "全部订阅源已刷新。", remove: "移除",
    search: "搜索名称、说明或标签", downloaded: "已下载", updates: "有更新", archived: "已归档",
    all: "全部", noWorkflows: "添加公共 GitHub 仓库后，工作流会显示在这里。",
    versions: "历史版本", changelog: "更新日志", dependencies: "插件依赖", models: "模型声明",
    repositoryPage: "打开 GitHub 仓库", releasePage: "打开 Release 页面", viewChangelog: "查看变更记录", hideChangelog: "收起变更记录",
    download: "下载此版本", downloadedTag: "已下载", source: "工作流文件",
    revealLocal: "在资源管理器中打开", deleteLocal: "删除本地版本",
    repository: "发布仓库", repositoryName: "目录名称", author: "作者", repositoryDescription: "目录说明", workflowInfo: "工作流资料",
    workflowId: "稳定 ID", name: "名称", summary: "简介", description: "详细说明", tags: "标签（逗号分隔）",
    version: "版本", minComfy: "最低 ComfyUI", maxComfy: "最高 ComfyUI", releaseNotes: "更新日志",
    nodeDeps: "插件依赖 JSON", validate: "校验", publishNow: "发布",
    login: "登录 GitHub", signedIn: "GitHub 已登录", logout: "退出", githubNotConfigured: "GitHub App Client ID 尚未配置",
    activities: "活动", noActivities: "暂无活动", settings: "设置", close: "关闭",
    stageQueued: "等待处理", stageDownloading: "正在下载", stageVerifying: "正在校验",
    stageValidating: "正在检查", stageCreatingRelease: "正在创建 Release", stageUploading: "正在上传",
    stagePublishingRelease: "正在发布 Release", stageUpdatingRepository: "正在写入仓库",
    stageComplete: "已完成", stageFailed: "失败", stageUnknown: "{stage}",
    confirmEnvironment: "我确认让 ComfyUI-Manager 串行执行所选插件变更", execute: "执行依赖计划",
    managerUnavailable: "Manager 不可用；工作流仍可下载，依赖请手动处理。",
    workflowUnavailable: "无法读取当前画布工作流，请从 ComfyUI 顶栏重新打开工作流中心。",
    publicOnly: "仅支持公共 GitHub 仓库。已发布版本资产不可覆盖或删除。",
    primaryNavigation: "主要导航", loginPurpose: "用于发布和管理", workflowFilters: "工作流筛选",
    waitingGithubAuthorization: "等待 GitHub 授权", completeSignInTwoSteps: "两步完成登录",
    deviceFlowHint: "先复制验证码，再打开 GitHub 授权页面。授权完成后这里会自动进入发布界面。",
    copyVerificationCode: "复制验证码", copied: "已复制", copy: "复制",
    openGithubAndPasteCode: "前往 GitHub 并粘贴验证码", openGithubAuthorization: "打开 GitHub 授权页面",
    waitingAuthorization: "正在等待授权结果，无需刷新页面", githubAuthorization: "GitHub 授权",
    signInToPublish: "登录后发布工作流",
    signInPublishHint: "发布会创建 GitHub Release 并更新工作流目录。登录前不会读取仓库，也不会展示发布表单。",
    pendingPublications: "待同步发布", publishing: "即将发布", readingCanvas: "正在读取当前画布…",
    comfyCoreVersion: "ComfyUI 内核版本", detecting: "检测中", scanningCanvasResources: "正在扫描当前画布资源…",
    requiredPlugins: "所需插件", pluginDetectionHint: "按当前画布映射 Manager 插件",
    managerPluginFallbackHint: "来自当前已安装的 Manager 插件",
    managerPluginFallbackTitle: "无法完整识别工作流依赖",
    managerPluginFallbackDescription: "有 {count} 个节点无法映射到插件包，已列出当前启用的 Manager 插件。请取消勾选与此工作流无关的插件。",
    gitDevelopmentVersion: "Git 开发版 · {version}", unknownRevision: "未知提交",
    registryDevelopmentSource: "{id} · 用户通过 Manager 安装",
    githubDevelopmentSource: "{url} · 需要手动安装",
    registryNotMatched: "未匹配 Registry", registryNotMatchedComfy: "未匹配到 Comfy Registry",
    manualInstall: "手动安装", manual: "手动", anyVersion: "任意版本",
    noExtraPlugins: "无需额外插件", environmentReady: "当前环境可直接使用",
    imageReferences: "图像引用", imageReferenceHint: "随工作流打包并自动改写引用",
    referenceCount: "{count} 个节点引用", noImageReferences: "没有图像引用",
    noBundledImagesHint: "工作流不会携带额外图片", includedImages: "随包图片",
    loraReferences: "LoRA 引用", clearReferences: "清空引用", noLoraReferences: "没有 LoRA 引用",
    nothingElseToReview: "无需额外处理",
    destination: "发布位置", repositoryRemembered: "仓库选择会自动记住", newRepository: "新建仓库",
    noAuthorizedRepositories: "没有已授权的仓库",
    repositoryNamePlaceholder: "仓库名称", create: "创建", releaseInformation: "版本资料",
    completeFieldsInOrder: "所有字段按顺序填写",
    category: "类别", categoryPlaceholder: "选择或输入新类别",
    publishedVersions: "已有版本 {versions}", none: "无", listSeparator: "、",
    versionAlreadyPublished: "这个版本已经发布，请填写新的版本号。",
    publishId: "发布标识", automatic: "自动生成", unnamedWorkflow: "未命名工作流",
    coverImage: "封面", optional: "可选", chooseCoverImage: "选择封面图",
    coverImageHint: "PNG、WebP 或 JPEG，不超过 10 MiB，将作为工作流卡片封面",
    coverImageInvalidType: "封面图必须是 PNG、WebP 或 JPEG。",
    coverImageTooLarge: "封面图不能超过 10 MiB。",
    coverImageReadFailed: "无法读取所选封面图。",
    repositoryLabel: "发布仓库", workflowLabel: "工作流",
    releaseVersion: "发布版本", comfyCore: "ComfyUI 内核", plugins: "插件", images: "图像",
    lorasIncluded: "发布 LoRA", immutableReleaseWarning: "发布后版本号和 Release 资源不可覆盖或删除。",
    resourcesReady: "资源检查完成", scanningResources: "正在检查资源", resourceReviewFailed: "资源检查未通过",
    releaseDetailsComplete: "发布信息已完整", completeReleaseFields: "请补全仓库、类别、名称、版本和更新日志",
    publishReviewReady: "确认无误后开始发布", back: "上一步", confirmResourcesNext: "确认资源，下一步",
    confirmDetailsNext: "确认信息，下一步",
    noWorkflowDescription: "暂无工作流说明", edit: "编辑资料", unarchive: "取消归档", archive: "归档",
    selectedVersion: "当前版本", coreVersionMismatch: "ComfyUI 内核版本不一致",
    coreVersionMismatchDetail: "此工作流使用 {required} 打包，你当前使用 ComfyUI {current}。下载后可能无法正常加载或运行。",
    checkPluginDependencies: "检查插件依赖", optionalLoras: "可选 LoRA", downloadIndividually: "按需下载",
    confirmRemoveSource: "移除订阅源？已下载的工作流会保留。",
    confirmDeleteLocalVersion: "删除本地版本 v{version}？远程 Release 不受影响。",
    confirmPluginChanges: "确认让 ComfyUI-Manager 串行修改插件环境？",
    managerTasksQueued: "已向 Manager 提交 {count} 个串行任务。",
    openFromToolbar: "请从 ComfyUI 顶栏打开工作流中心，以读取当前画布。",
    currentCanvasUnavailable: "无法读取当前画布工作流。", untitledWorkflowFile: "未命名工作流.json",
    confirmClearLoras: "清空此工作流中 Lora Manager 的 LoRA 引用？仅修改当前待发布副本。",
    loraReferencesCleared: "已清空当前待发布工作流中的 LoRA 引用。",
    repositoryCreated: "仓库已创建。请在 GitHub App 设置中授权该仓库，然后重新加载本页。",
    validationPassed: "校验通过，可以发布。",
    confirmArchive: "确认归档“{name}”？历史版本不会删除。",
    confirmUnarchive: "确认取消归档“{name}”？历史版本不会删除。",
  },
  en: {
    title: "Workflow Hub", subscribe: "Subscribe", publish: "Publish", addSource: "Add subscription",
    sourcesLabel: "Sources", emptyTitle: "No workflows yet", emptyFiltered: "No workflows match the current search or filter.",
    sourcePlaceholder: "https://github.com/owner/repo", add: "Add", refresh: "Refresh", refreshAll: "Refresh all", allSourcesRefreshed: "All sources refreshed.", remove: "Remove",
    search: "Search names, descriptions, or tags", downloaded: "Downloaded", updates: "Updates", archived: "Archived",
    all: "All", noWorkflows: "Add a public GitHub repository and its workflows will appear here.",
    versions: "Versions", changelog: "Changelog", dependencies: "Plugin dependencies", models: "Model declarations",
    repositoryPage: "Open GitHub repository", releasePage: "Open Release page", viewChangelog: "View changelog", hideChangelog: "Hide changelog",
    download: "Download version", downloadedTag: "Downloaded", source: "Workflow file",
    revealLocal: "Show in file manager", deleteLocal: "Delete local version",
    repository: "Repository", repositoryName: "Catalog name", author: "Author", repositoryDescription: "Catalog description", workflowInfo: "Workflow details",
    workflowId: "Stable ID", name: "Name", summary: "Summary", description: "Description", tags: "Tags (comma-separated)",
    version: "Version", minComfy: "Minimum ComfyUI", maxComfy: "Maximum ComfyUI", releaseNotes: "Release notes",
    nodeDeps: "Plugin dependencies JSON", validate: "Validate", publishNow: "Publish",
    login: "Sign in to GitHub", signedIn: "GitHub signed in", logout: "Sign out", githubNotConfigured: "GitHub App Client ID is not configured",
    activities: "Activity", noActivities: "No activity", settings: "Settings", close: "Close",
    stageQueued: "Queued", stageDownloading: "Downloading", stageVerifying: "Verifying",
    stageValidating: "Validating", stageCreatingRelease: "Creating Release", stageUploading: "Uploading",
    stagePublishingRelease: "Publishing Release", stageUpdatingRepository: "Updating repository",
    stageComplete: "Complete", stageFailed: "Failed", stageUnknown: "{stage}",
    confirmEnvironment: "I confirm ComfyUI-Manager may apply selected plugin changes serially", execute: "Apply dependency plan",
    managerUnavailable: "Manager is unavailable. You can still download; handle dependencies manually.",
    workflowUnavailable: "Unable to read the current canvas workflow. Reopen Workflow Hub from the ComfyUI top bar.",
    publicOnly: "Public GitHub repositories only. Published version assets cannot be overwritten or deleted.",
    primaryNavigation: "Primary navigation", loginPurpose: "Publish and manage", workflowFilters: "Workflow filters",
    waitingGithubAuthorization: "Waiting for GitHub authorization", completeSignInTwoSteps: "Complete sign-in in two steps",
    deviceFlowHint: "Copy the verification code, then open GitHub authorization. This page continues automatically when authorization completes.",
    copyVerificationCode: "Copy verification code", copied: "Copied", copy: "Copy",
    openGithubAndPasteCode: "Open GitHub and paste the code", openGithubAuthorization: "Open GitHub authorization",
    waitingAuthorization: "Waiting for authorization — no refresh needed", githubAuthorization: "GitHub authorization",
    signInToPublish: "Sign in to publish workflows",
    signInPublishHint: "Publishing creates a GitHub Release and updates the workflow catalog. Repositories and the publish form stay unavailable until you sign in.",
    pendingPublications: "Pending publications", publishing: "Publishing", readingCanvas: "Reading current canvas…",
    comfyCoreVersion: "ComfyUI core version", detecting: "Detecting", scanningCanvasResources: "Scanning current canvas resources…",
    requiredPlugins: "Required plugins", pluginDetectionHint: "Mapped to Manager plugins from the current canvas",
    managerPluginFallbackHint: "Current installed Manager plugins",
    managerPluginFallbackTitle: "Workflow dependencies could not be fully identified",
    managerPluginFallbackDescription: "{count} node types could not be mapped to plugin packages. Enabled Manager plugins are listed instead; deselect plugins unrelated to this workflow.",
    gitDevelopmentVersion: "Git development · {version}", unknownRevision: "unknown revision",
    registryDevelopmentSource: "{id} · users install through Manager",
    githubDevelopmentSource: "{url} · manual installation required",
    registryNotMatched: "Not matched in Registry", registryNotMatchedComfy: "Not matched in Comfy Registry",
    manualInstall: "Manual installation", manual: "Manual", anyVersion: "Any version",
    noExtraPlugins: "No extra plugins", environmentReady: "Ready for the current environment",
    imageReferences: "Image references", imageReferenceHint: "Bundled and rewritten on installation",
    referenceCount: "{count} references", noImageReferences: "No image references",
    noBundledImagesHint: "No images will be bundled", includedImages: "Included images",
    loraReferences: "LoRA references", clearReferences: "Clear references", noLoraReferences: "No LoRA references",
    nothingElseToReview: "Nothing else to review",
    destination: "Destination", repositoryRemembered: "Repository choice is remembered", newRepository: "New repository",
    noAuthorizedRepositories: "No authorized repositories",
    repositoryNamePlaceholder: "Repository name", create: "Create", releaseInformation: "Release information",
    completeFieldsInOrder: "Complete each field in order",
    category: "Category", categoryPlaceholder: "Choose or create",
    publishedVersions: "Published {versions}", none: "none", listSeparator: ", ",
    versionAlreadyPublished: "This version is already published.",
    publishId: "Publish ID", automatic: "Automatic", unnamedWorkflow: "Untitled workflow",
    coverImage: "Cover", optional: "Optional", chooseCoverImage: "Choose cover image",
    coverImageHint: "PNG, WebP, or JPEG up to 10 MiB; shown as the workflow card cover",
    coverImageInvalidType: "Cover image must be PNG, WebP, or JPEG.",
    coverImageTooLarge: "Cover image must be 10 MiB or smaller.",
    coverImageReadFailed: "Unable to read the selected cover image.",
    repositoryLabel: "Repository", workflowLabel: "Workflow",
    releaseVersion: "Release version", comfyCore: "ComfyUI core", plugins: "Plugins", images: "Images",
    lorasIncluded: "LoRAs included", immutableReleaseWarning: "Published version numbers and Release assets cannot be overwritten or deleted.",
    resourcesReady: "Resources are ready", scanningResources: "Scanning resources", resourceReviewFailed: "Resource review failed",
    releaseDetailsComplete: "Release details are complete", completeReleaseFields: "Complete the repository, category, name, version, and release notes",
    publishReviewReady: "Publish when the review is complete", back: "Back", confirmResourcesNext: "Confirm resources",
    confirmDetailsNext: "Review release",
    noWorkflowDescription: "No workflow description", edit: "Edit", unarchive: "Unarchive", archive: "Archive",
    selectedVersion: "Selected version", coreVersionMismatch: "ComfyUI core version mismatch",
    coreVersionMismatchDetail: "This workflow was packaged with {required}; you are running ComfyUI {current}. It may not load or run correctly after download.",
    checkPluginDependencies: "Check plugin dependencies", optionalLoras: "Optional LoRAs", downloadIndividually: "Download individually",
    confirmRemoveSource: "Remove subscription? Downloads are kept.",
    confirmDeleteLocalVersion: "Delete local version v{version}? The remote release is unchanged.",
    confirmPluginChanges: "Confirm serial plugin changes through ComfyUI-Manager?",
    managerTasksQueued: "Queued {count} serial Manager tasks.",
    openFromToolbar: "Open Workflow Hub from the ComfyUI top bar to read the current canvas.",
    currentCanvasUnavailable: "Unable to read the current canvas workflow.", untitledWorkflowFile: "Unsaved Workflow.json",
    confirmClearLoras: "Clear Lora Manager references from this workflow? Only the pending publish copy is changed.",
    loraReferencesCleared: "LoRA references cleared from the pending workflow.",
    repositoryCreated: "Repository created. Authorize it in the GitHub App installation, then reload this page.",
    validationPassed: "Validation passed. Ready to publish.",
    confirmArchive: "Confirm archive “{name}”? Historical versions are kept.",
    confirmUnarchive: "Confirm unarchive “{name}”? Historical versions are kept.",
  },
} as const;

export type MessageKey = keyof typeof messages.zh;
export type MessageParams = Record<string, string | number>;

function interpolate(message: string, params: MessageParams = {}): string {
  return message.replace(/\{(\w+)\}/g, (_, key: string) => String(params[key] ?? `{${key}}`));
}

export const t = computed(() => (key: MessageKey, params?: MessageParams) =>
  interpolate(messages[locale.value][key], params)
);

export function setLocale(value?: string | null) {
  locale.value = resolveLocale(value);
  document.documentElement.lang = locale.value === "zh" ? "zh-CN" : "en";
}

export async function syncLocaleFromComfy() {
  const queryLocale = new URLSearchParams(window.location.search).get("locale");
  if (queryLocale) setLocale(queryLocale);

  try {
    const response = await fetch("/api/settings/Comfy.Locale");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const comfyLocale: unknown = await response.json();
    if (typeof comfyLocale === "string" && comfyLocale) setLocale(comfyLocale);
  } catch (error) {
    console.warn("Unable to read ComfyUI locale; using the browser locale.", error);
  }
}
