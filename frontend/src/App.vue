<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import {
  Activity as ActivityIcon,
  AlertCircle,
  Archive as ArchiveIcon,
  ArrowLeft,
  ArrowRight,
  Check,
  CheckCircle2,
  ChevronDown,
  CircleUserRound,
  CircleX,
  Compass,
  Copy,
  Download as DownloadIcon,
  ExternalLink,
  FileJson,
  FileUp,
  FolderGit2,
  FolderCog,
  FolderOpen,
  GitBranch,
  ImagePlus,
  Info,
  LibraryBig,
  LoaderCircle,
  Clock,
  ListFilter,
  LogOut,
  PackageOpen,
  Plus,
  RefreshCw,
  Search as SearchIcon,
  Settings as SettingsIcon,
  ShieldCheck,
  SquarePen,
  Trash2,
  TriangleAlert,
  UploadCloud,
  X,
} from "@lucide/vue";
import { ApiError, api, post, remove } from "./api";
import {
  CatalogRequestCoordinator,
  clearCatalogCache,
  readCatalogCache,
  writeCatalogCache,
  type CatalogSnapshot,
} from "./catalog-cache";
import { renderMarkdown } from "./markdown";
import { locale, t, type MessageKey } from "./i18n";
import {
  publishRepositoryUrl,
  resolvePublishRepositoryUrl,
  type PublishRepository,
} from "./repository-selection";

type Source = { owner: string; repo: string; url: string; refreshed_at: string; error?: string };
type ManagedVersion = { version: string; published_at: string; changelog: string; package: { size: number }; custom_nodes?: NodeDependencyInfo[] };
type DependencyCommitOption = { sha: string; message: string; committed_at: string; url: string };
type DependencyPinEntry = {
  key: string; name: string; source_url: string; current: string; selected: string; latest: string;
  commits: DependencyCommitOption[]; error: string;
};
type ManagedProduct = {
  id: string; name: string; category: string; summary: string; description: string;
  tags: string[]; archived: boolean; cover?: { url: string } | null; versions: ManagedVersion[];
};
type ModelAsset = { name: string; type: string; filename: string; source_url: string; sha256?: string | null };
type AssetReference = {
  name: string; filename: string; node_ids: string[]; status: string; size?: number | null; sha256?: string | null;
};
type BundledInput = {
  source: string; archive: string; size: number; sha256: string; node_ids: string[];
};
type Version = {
  version: string; published_at: string; release_tag: string; changelog: string;
  comfyui?: { minimum?: string | null; maximum?: string | null };
  package: { url: string; size: number; sha256: string };
  preview?: { url: string; sha256: string } | null;
  custom_nodes: NodeDependencyInfo[]; inputs?: BundledInput[]; models: ModelAsset[];
  repository_path: string;
};
type Product = {
  id: string; name: string; category: string; summary: string; description: string; tags: string[]; archived: boolean;
  cover?: { url: string; sha256: string } | null;
  versions: Version[]; downloaded_versions: string[]; source: { owner: string; repo: string };
  repository_path: string;
};
type CatalogRefreshResult = CatalogSnapshot<Source, Product> & {
  changed: boolean;
  failed: { owner: string; repo: string }[];
};
type Status = {
  plugin_version: string;
  catalog_cache_scope?: string;
  comfyui_version: string;
  settings?: {
    auto_update_check: boolean;
    update_check_interval_hours: number;
    last_checked_at?: string | null;
  };
  git: { available: boolean; source?: string; launcher_mirrors?: { detected: boolean; git: boolean; pypi: boolean } };
  manager?: { available: boolean; compatible: boolean; version?: string; api?: string };
  github: { configured: boolean; authenticated: boolean; user?: { login: string; avatar_url: string }; persistent_credentials: boolean };
};
type Operation = {
  id: string; kind: string; stage: string; status: string; logs: string[]; created_at: string; metadata?: Record<string, unknown>;
  error_code?: string; error_params?: Record<string, string | number>;
  progress?: { received: number; total: number }; progress_mode?: "bytes" | "tasks";
  result?: Record<string, unknown>;
};
type PublishStep = 1 | 2 | 3 | 4;
type PublishDraft = {
  name: string;
  version: string;
  workflowId: string;
  repository: string;
};
type CoreVersionCheck = {
  state: "aligned" | "mismatch" | "not_declared" | "unavailable";
  tone: "ok" | "warn" | "muted";
  label: MessageKey;
  detail: MessageKey;
  params?: Record<string, string | number>;
};
type DownloadPreflight = {
  item: Product;
  version: Version;
  core: CoreVersionCheck;
  currentCoreVersion: string;
  environmentError: string;
  dependencies: DependencyPlan[];
  dependencyError: string;
  syncing: boolean;
  syncOperationId: string;
  syncError: string;
};
type DependencyPlan = {
  task_id?: string; registry_id?: string | null; source_url?: string | null; name: string; requested?: string | null; installed?: string | null;
  action: "keep" | "install" | "upgrade" | "downgrade" | "newer" | "conflict" | "unknown" | "manual";
  installer?: "git" | "manager";
  warning_code?: string | null; warning_params?: Record<string, string | number>;
};
type NodeDependencyInfo = {
  registry_id?: string | null; name: string; version?: string | null; commit?: string | null; required?: boolean; manual?: boolean; source_url?: string | null;
};
type ScannedNodeDependency = NodeDependencyInfo & {
  dirty?: boolean;
  installer?: "git" | "manager";
};
type DependencyResult = {
  task_id?: string; name: string; registry_id?: string | null; source_url?: string | null; requested?: string | null; action: string;
  installer?: "git" | "manager";
  state: "queued" | "installing" | "python_installing" | "success" | "failed" | "unknown";
  error_code?: string | null; error_params?: Record<string, string | number>;
};
type DependencyExecutionTask = DependencyResult & { registryId: string; version: string; message: string };
type PublishCatalogProduct = {
  id: string; name: string; category: string; summary: string; description: string; tags: string[]; versions: string[];
};
type DependencyTaskState = DependencyResult["state"];
type ResourceDialog = "core" | "plugins" | "images";
type PluginDependencyCheck = {
  state: "aligned" | "missing" | "mismatch" | "checking" | "unavailable";
  tone: "ok" | "warn" | "missing" | "muted";
  label: MessageKey;
  detail: MessageKey;
  params?: Record<string, string | number>;
};

const LAST_PUBLISH_REPOSITORY_KEY = "aaalice-workflow-hub:last-publish-repository";
const PUBLISH_OPERATION_KEY = "aaalice-workflow-hub:publish-operation";
const PUBLISH_SOURCE_KEY = "aaalice-workflow-hub:publish-source";
const tab = ref<"subscribe" | "publish" | "manage">("subscribe");
const status = ref<Status | null>(null);
const sources = ref<Source[]>([]);
const products = ref<Product[]>([]);
const selected = ref<Product | null>(null);
const selectedDetailVersion = ref("");
const resourceDialog = ref<ResourceDialog | null>(null);
const sourceUrl = ref("");
const sourceInput = ref<HTMLInputElement | null>(null);
const searchInput = ref<HTMLInputElement | null>(null);
const detailReleaseScroll = ref<HTMLElement | null>(null);
const sourceComposerOpen = ref(false);
const search = ref("");
const filter = ref<"all" | "downloaded" | "updates" | "archived">("all");
const busy = ref("");
const error = ref("");
const notice = ref("");
const drawer = ref(false);
const settingsOpen = ref(false);
const settingsSaving = ref(false);
const settingsSaved = ref(false);
const settingsError = ref("");
const settingsDraft = reactive({ auto_update_check: true, update_check_interval_hours: 24 });
const operations = ref<Operation[]>([]);
const repositories = ref<PublishRepository[]>([]);
const createRepositoryName = ref("");
const createRepositoryOpen = ref(false);
const pendingPublications = ref<{ tag: string }[]>([]);
const managedProducts = ref<ManagedProduct[]>([]);
const manageRepositoryUrl = ref("");
const manageLoading = ref(false);
const manageExpanded = ref<string[]>([]);
const editingProduct = ref<ManagedProduct | null>(null);
const editForm = reactive({ name: "", category: "", summary: "", description: "", tags: "" });
const editingChangelog = ref<{ product: ManagedProduct; version: ManagedVersion; text: string } | null>(null);
const dependencyPinEditor = ref<{
  product: ManagedProduct; version: ManagedVersion;
  entries: DependencyPinEntry[]; readonlyCount: number; loading: boolean;
} | null>(null);
const workflow = ref<Record<string, unknown> | null>(null);
const workflowSourceName = ref("");
const canvasWorkflowError = ref("");
const dependencyScanError = ref("");
const scannedPluginDependencies = ref<ScannedNodeDependency[]>([]);
const selectedPluginKeys = ref<string[]>([]);
const resourceScanPending = ref(false);
const publisherLoading = ref(false);
const publishCatalogProducts = ref<PublishCatalogProduct[]>([]);
const repositoryCategories = ref<string[]>([]);
const selectedCatalogProductId = ref("");
const imageReferences = ref<AssetReference[]>([]);
const loraReferences = ref<AssetReference[]>([]);
const coverImage = ref<{ name: string; filename: string; data_base64: string; previewUrl: string; size: number } | null>(null);
const publishChangelogFileInput = ref<HTMLInputElement | null>(null);
const manageChangelogFileInput = ref<HTMLInputElement | null>(null);
const publishStep = ref<PublishStep>(1);
const publishOperationId = ref("");
const publishSourceName = ref("");
const publishDraft = ref<PublishDraft | null>(null);
const publishCompletion = ref<Operation | null>(null);
const downloadCompletion = ref<Operation | null>(null);
const device = ref<{ user_code: string; verification_uri: string; interval: number } | null>(null);
const deviceCodeCopied = ref(false);
const dependencyPlans = reactive<Record<string, DependencyPlan[]>>({});
const selectedDependencyActions = reactive<Record<string, string[]>>({});
const dependencyAlignment = reactive<Record<string, boolean>>({});
const dependencyOperationIds = reactive<Record<string, string>>({});
const dependencyOperationSynced = reactive<Record<string, boolean>>({});
const publisherManagementOperationIds = reactive<Record<string, boolean>>({});
const publisherManagementOperationSynced = reactive<Record<string, boolean>>({});
const downloadOperationIds = reactive<Record<string, string>>({});
const deletingOperationIds = reactive<Record<string, boolean>>({});
const clearingOperations = ref(false);
const hiddenOperationIds = new Set<string>();
const managerTaskOverrides = reactive<Record<string, { state: "success" | "failed"; message: string }>>({});
const pendingManagerTaskOverrides = reactive<Record<string, { state: "success" | "failed"; message: string }>>({});
const managerResultSyncing = new Set<string>();
const dependencyPlanGeneration = reactive<Record<string, number>>({});
const dependencyPlanLoading = reactive<Record<string, boolean>>({});
const downloadPreflight = ref<DownloadPreflight | null>(null);
const loading = ref(true);
const catalogRefreshing = ref(false);
const catalogRequests = new CatalogRequestCoordinator<CatalogSnapshot<Source, Product>>(() =>
  api<CatalogSnapshot<Source, Product>>("/catalog")
);
let loadInFlight: Promise<void> | null = null;
let publisherLoadInFlight: Promise<void> | null = null;
let publisherLoaded = false;
let loadAttempted = false;
let operationPollInFlight = false;
let managerSocket: WebSocket | null = null;
let operationTimer = 0;
let loginTimer = 0;
let copiedTimer = 0;

const operationStageMessages: Record<string, MessageKey> = {
  queued: "stageQueued",
  checking_network: "stageCheckingNetwork",
  installing: "stageInstalling",
  installing_workflow: "stageInstallingWorkflow",
  downloading: "stageDownloading",
  verifying: "stageVerifying",
  validating: "stageValidating",
  creating_release: "stageCreatingRelease",
  uploading: "stageUploading",
  publishing_release: "stagePublishingRelease",
  updating_release: "stageUpdatingRelease",
  deleting_release: "stageDeletingRelease",
  updating_repository: "stageUpdatingRepository",
  complete: "stageComplete",
  failed: "stageFailed",
};
const publishProgressStages = [
  "validating",
  "creating_release",
  "uploading",
  "publishing_release",
  "updating_repository",
] as const;
const downloadProgressStages = ["queued", "downloading", "verifying", "installing_workflow"] as const;
const managementDefaultProgressStages = ["validating", "updating_repository"] as const;
const managementProgressStages: Record<string, readonly string[]> = {
  edit_metadata: managementDefaultProgressStages,
  archive: managementDefaultProgressStages,
  unarchive: managementDefaultProgressStages,
  edit_changelog: ["validating", "updating_release", "updating_repository"],
  update_dependencies: ["validating", "updating_release", "updating_repository"],
  delete_version: ["validating", "deleting_release", "updating_repository"],
  delete_workflow: ["validating", "deleting_release", "updating_repository"],
};
const backendErrorMessages: Record<string, MessageKey> = {
  "dependencies.network_unavailable": "dependenciesNetworkUnavailable",
  "dependencies.git_unavailable": "dependenciesGitUnavailable",
  "dependencies.github_source_invalid": "dependenciesGithubSourceInvalid",
  "dependencies.github_source_missing": "dependenciesGithubSourceMissing",
  "dependencies.commit_missing": "dependenciesCommitMissing",
  "dependencies.conflicting_commits": "dependenciesConflictingCommits",
  "dependencies.duplicate_git_source": "dependenciesDuplicateGitSource",
  "dependencies.local_changes": "dependenciesLocalChanges",
  "dependencies.unpushed_commits": "dependenciesUnpushedCommits",
  "dependencies.non_git_install": "dependenciesNonGitInstall",
  "dependencies.target_exists": "dependenciesTargetExists",
  "dependencies.git_command_failed": "dependenciesGitCommandFailed",
  "dependencies.manager_unavailable": "dependenciesManagerUnavailable",
  "dependencies.manager_incompatible": "dependenciesManagerIncompatible",
  "dependencies.manager_request_failed": "dependenciesManagerRequestFailed",
  "dependencies.manager_timeout": "dependenciesManagerTimeout",
  "dependencies.manager_task_failed": "dependenciesManagerTaskFailed",
  "dependencies.manager_version_unknown": "dependenciesManagerVersionUnknown",
  "dependencies.conflicting_registry_versions": "dependenciesConflictingRegistryVersions",
  "dependencies.version_alignment_disabled": "dependenciesVersionAlignmentDisabled",
  "dependencies.invalid_version_policy": "dependenciesInvalidVersionPolicy",
  "dependencies.python_requirements_failed": "dependenciesPythonRequirementsFailed",
  "dependencies.manager_result_unknown": "dependenciesManagerResultUnknown",
  "operation.interrupted": "operationInterrupted",
  "operation.not_found": "operationNotFound",
  "operation.active": "operationActive",
  "operation.failed": "operationFailedDetail",
  "operation.invalid_manager_result": "operationInvalidManagerResult",
  "dependencies.operation_failed": "operationFailedDetail",
  "request.invalid": "requestInvalid",
  "request.invalid_payload": "requestInvalidPayload",
  "request.origin_invalid": "requestOriginInvalid",
  "request.body_too_large": "requestBodyTooLarge",
  "request.content_type_invalid": "requestContentTypeInvalid",
  "request.json_invalid": "requestJsonInvalid",
  "request.object_required": "requestObjectRequired",
  "github.request_failed": "githubRequestFailed",
  "github.authentication_required": "githubAuthenticationRequired",
  "github.login_expired": "githubLoginExpired",
  "github.credential_unavailable": "githubCredentialUnavailable",
  "subscription.invalid_source": "subscriptionInvalidSource",
  "subscription.not_found": "subscriptionNotFound",
  "subscription.workflow_not_found": "subscriptionWorkflowNotFound",
  "subscription.version_not_found": "subscriptionVersionNotFound",
  "subscription.catalog_invalid": "subscriptionCatalogInvalid",
  "subscription.local_version_not_found": "subscriptionLocalVersionNotFound",
  "subscription.local_file_missing": "subscriptionLocalFileMissing",
  "subscription.workflow_file_conflict": "subscriptionWorkflowFileConflict",
  "subscription.input_file_conflict": "subscriptionInputFileConflict",
  "dependencies.invalid_plan": "dependenciesInvalidPlan",
  "dependencies.confirmation_required": "dependenciesConfirmationRequired",
  "dependencies.plan_changed": "dependenciesPlanChanged",
  "publisher.lora_forbidden": "loraPublishForbidden",
  "publisher.dependency_update_invalid": "publisherDependencyUpdateInvalid",
  "publisher.dependency_commit_missing": "publisherDependencyCommitMissing",
  "publisher.confirmation_required": "publisherConfirmationRequired",
  "publisher.product_invalid": "publisherProductInvalid",
  "publisher.repository_invalid": "publisherRepositoryInvalid",
  "publisher.workflow_invalid": "publisherWorkflowInvalid",
  "publisher.assets_invalid": "publisherAssetsInvalid",
  "publisher.pending_not_found": "publisherPendingNotFound",
  "subscription.catalog_missing": "subscriptionCatalogMissing",
  "subscription.refresh_failed": "subscriptionRefreshFailed",
  "subscription.cache_unavailable": "subscriptionCacheUnavailable",
  "subscription.cache_migration_conflict": "subscriptionCacheMigrationConflict",
  "settings.invalid": "settingsInvalid",
};

const form = reactive({
  repository_url: "",
  repository_name: "",
  author: "",
  repository_description: "",
  id: "",
  name: "",
  category: "",
  summary: "",
  description: "",
  tags: "",
  version: "1.0",
  changelog: "",
  custom_nodes: "[]",
});

const visibleProducts = computed(() => {
  const query = search.value.trim().toLocaleLowerCase();
  return products.value.filter((item) => {
    if (filter.value === "downloaded" && !item.downloaded_versions.length) return false;
    if (filter.value === "archived" && !item.archived) return false;
    if (filter.value === "updates") {
      const latest = [...item.versions].sort(compareVersions).at(-1)?.version;
      if (!latest || item.downloaded_versions.includes(latest)) return false;
    }
    if (!query) return true;
    return [item.name, item.category || "", item.summary, item.description, ...item.tags].join(" ").toLocaleLowerCase().includes(query);
  });
});
const filterIndex = computed(() => (["all", "downloaded", "updates", "archived"] as const).indexOf(filter.value));
const detailVersions = computed(() =>
  selected.value ? [...selected.value.versions].sort(compareVersions).reverse() : []
);
const activeDetailVersion = computed(() =>
  detailVersions.value.find((version) => version.version === selectedDetailVersion.value) || detailVersions.value[0] || null
);
const renderedActiveChangelog = computed(() => renderMarkdown(activeDetailVersion.value?.changelog || ""));
const preflightDependencyIssues = computed(() =>
  downloadPreflight.value?.dependencies.filter((entry) => entry.action !== "keep") || []
);
const preflightSyncableDependencies = computed(() =>
  preflightDependencyIssues.value.filter((entry) => !downloadPreflight.value?.environmentError
    && dependencyActionRequiresSelection(entry.action)
    && dependencyInstallerAvailable(entry))
);
const publishStepLabels = computed(() => [t.value("stepResources"), t.value("stepDetails"), t.value("stepReview"), t.value("stepComplete")]);
const publishOperation = computed(() =>
  publishOperationId.value ? operations.value.find((item) => item.id === publishOperationId.value) || null : null
);
const publishOperationRunning = computed(() => {
  const operation = publishOperation.value;
  return !!operation && isOperationActive(operation);
});
const activeDependencyOperation = computed(() => {
  if (!selected.value || !activeDetailVersion.value) return null;
  const operationId = dependencyOperationIds[dependencyKey(selected.value, activeDetailVersion.value)];
  return operations.value.find((item) => item.id === operationId) || null;
});
function operationTaskRows(operation: Operation): DependencyExecutionTask[] {
  const rawTasks = Array.isArray(operation.result?.tasks) ? operation.result.tasks as DependencyResult[] : [];
  return rawTasks.map((entry) => {
    const taskId = String(entry.task_id || entry.registry_id || entry.source_url || entry.name);
    const overrideKey = String(entry.registry_id || "");
    const override = overrideKey
      ? managerTaskOverrides[`${operation.id}:${overrideKey}`] || pendingManagerTaskOverrides[overrideKey]
      : undefined;
    return {
      ...entry,
      task_id: entry.task_id,
      registryId: taskId,
      state: override?.state || entry.state,
      version: entry.requested || "",
      message: override?.message || (entry.error_code ? localizedBackendError(entry.error_code, entry.error_params) : ""),
    };
  });
}
const activeDependencyExecution = computed(() => {
  const operation = activeDependencyOperation.value;
  if (!operation) return null;
  const tasks = operationTaskRows(operation);
  return {
    total: operation.progress?.total || tasks.length,
    done: operation.progress?.received || (operation.status === "running" ? 0 : tasks.length),
    finished: operation.status !== "running",
    failed: operation.status === "failed",
    tasks,
    logs: [...operation.logs, ...Object.entries(managerTaskOverrides)
      .filter(([key]) => key.startsWith(`${operation.id}:`))
      .map(([key, value]) => `${key.slice(operation.id.length + 1)}: ${value.message || value.state}`)],
  };
});
const dependencyExecutionFailures = computed(() => {
  const execution = activeDependencyExecution.value;
  if (!execution) return 0;
  const taskFailures = execution.tasks.filter((task) => task.state === "failed" || task.state === "unknown").length;
  return taskFailures || (execution.failed ? 1 : 0);
});
const dependencyOperationRunning = computed(() => operations.value.some((item) => item.kind === "dependencies" && isOperationActive(item)));
const publisherManagementOperationRunning = computed(() =>
  Object.keys(publisherManagementOperationIds).length > 0
  || operations.value.some((item) => item.kind === "publisher-manage" && item.status === "running"),
);
const completedOperationCount = computed(() => operations.value.filter((item) => !isOperationActive(item)).length);
const activityMutationBusy = computed(() => clearingOperations.value || Object.keys(deletingOperationIds).length > 0);
const operationTimeFormatter = computed(() => new Intl.DateTimeFormat(locale.value, {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
}));
const publishCompletionName = computed(() => publishResultText(publishCompletion.value, "name") || publishDraft.value?.name || t.value("publishedWorkflow"));
const publishCompletionVersion = computed(() => publishResultText(publishCompletion.value, "version") || publishDraft.value?.version || t.value("none"));
const publishCompletionRepository = computed(() => publishResultText(publishCompletion.value, "repository") || publishDraft.value?.repository || t.value("none"));
const publishCompletionWorkflowId = computed(() => publishResultText(publishCompletion.value, "workflow_id") || publishDraft.value?.workflowId || t.value("none"));
const publishCompletionRepositoryPath = computed(() => publishResultText(publishCompletion.value, "repository_path") || t.value("none"));
const publishCompletionReleaseUrl = computed(() => publishResultText(publishCompletion.value, "release_url"));
const publishCompletionTime = computed(() => publishCompletion.value ? operationTimeLabel(publishCompletion.value.created_at) : "");
const downloadCompletionName = computed(() => publishResultText(downloadCompletion.value, "name") || String(downloadCompletion.value?.metadata?.name || t.value("workflowLabel")));
const downloadCompletionVersion = computed(() => publishResultText(downloadCompletion.value, "version") || String(downloadCompletion.value?.metadata?.version || t.value("none")));
const dependencyTaskStateKeys: Record<DependencyTaskState, MessageKey> = {
  queued: "installTaskQueued",
  installing: "installTaskInstalling",
  python_installing: "installTaskPythonInstalling",
  success: "installTaskSuccess",
  failed: "installTaskFailed",
  unknown: "installTaskUnknown",
};
const canAdvancePublish = computed(() => {
  return !!form.repository_url.trim() && !!form.repository_name.trim() && !!form.author.trim();
});
const selectedCatalogProduct = computed(() =>
  publishCatalogProducts.value.find((item) => item.id === selectedCatalogProductId.value) || null
);
const existingVersionConflict = computed(() => {
  const product = selectedCatalogProduct.value;
  if (!product) return false;
  const candidate = normalizeVersion(form.version.trim()).join(".");
  return product.versions.some((version) => normalizeVersion(version).join(".") === candidate);
});
const canFinalizePublish = computed(() => {
  if (!workflow.value || !canAdvancePublish.value || !form.category.trim() || !form.name.trim() || existingVersionConflict.value
    || !/^(0|[1-9]\d*)\.(0|[1-9]\d*)(?:\.(0|[1-9]\d*))?$/.test(form.version.trim())
    || !form.changelog.trim()) {
    return false;
  }
  try {
    return Array.isArray(JSON.parse(form.custom_nodes));
  } catch {
    return false;
  }
});
const canConfirmPublishResources = computed(() =>
  !!workflow.value
  && !!status.value?.comfyui_version
  && !resourceScanPending.value
  && !canvasWorkflowError.value
  && !dependencyScanError.value
  && imageReferences.value.every((item) => item.status === "ready")
);
const customNodeDependencies = computed<NodeDependencyInfo[]>(() => {
  try {
    const items = JSON.parse(form.custom_nodes);
    return Array.isArray(items) ? items : [];
  } catch {
    return [];
  }
});
const customNodeCount = computed(() => customNodeDependencies.value.length);
function pluginKey(item: NodeDependencyInfo) {
  return item.registry_id || item.source_url || item.name;
}
function catalogDependency(item: ScannedNodeDependency): NodeDependencyInfo {
  return {
    registry_id: item.registry_id || null,
    name: item.name,
    version: item.installer === "manager" ? item.version || null : null,
    commit: item.installer === "git" ? item.commit || null : null,
    required: true,
    manual: item.installer !== "manager",
    source_url: item.installer === "git" ? item.source_url || null : null,
  };
}
function syncSelectedPlugins() {
  const selectedKeys = new Set(selectedPluginKeys.value);
  const selectedItems = scannedPluginDependencies.value
    .filter((item) => selectedKeys.has(pluginKey(item)))
    .map(catalogDependency);
  form.custom_nodes = JSON.stringify(selectedItems, null, 2);
}
function togglePlugin(item: ScannedNodeDependency, checked: boolean) {
  const key = pluginKey(item);
  selectedPluginKeys.value = checked
    ? [...new Set([...selectedPluginKeys.value, key])]
    : selectedPluginKeys.value.filter((itemKey) => itemKey !== key);
  syncSelectedPlugins();
}
function pluginVersionLabel(item: ScannedNodeDependency) {
  if (item.installer === "manager") return item.version || t.value("managerVersionUnavailable");
  return item.commit
    ? t.value("gitCommitVersion", { version: item.commit.slice(0, 8) })
    : t.value("gitRevisionUnavailable");
}
function pluginSourceLabel(item: ScannedNodeDependency) {
  const source = item.source_url || t.value("githubSourceUnavailable");
  return item.dirty ? t.value("gitSourceDirty", { source }) : source;
}
function shortDependencyVersion(value: string) {
  return value.length > 12 ? `${value.slice(0, 8)}…` : value;
}
function dependencyVersionLabel(node: NodeDependencyInfo, entry: DependencyPlan | null) {
  if (entry?.installed) {
    return t.value("dependencyVersionTransition", {
      installed: shortDependencyVersion(entry.installed),
      requested: shortDependencyVersion(entry.requested || t.value("gitRevisionUnavailable")),
    });
  }
  if (entry?.installer === "manager" && node.version) return t.value("managerVersion", { version: node.version });
  if (node.commit) return t.value("gitCommitVersion", { version: node.commit.slice(0, 8) });
  if (node.version) return t.value("managerVersion", { version: node.version });
  return t.value("gitRevisionUnavailable");
}
function dependencyVersionTitle(node: NodeDependencyInfo, entry: DependencyPlan | null) {
  if (entry?.installed || entry?.requested) return [entry.installed, entry.requested].filter(Boolean).join(" → ");
  return node.commit || node.version || undefined;
}
function normalizeVersion(value: string): number[] {
  const parts = value.split(".").map(Number);
  return [parts[0] || 0, parts[1] || 0, parts[2] || 0];
}
function parseWorkflowFilename(filename: string) {
  const stem = filename.replace(/\.json$/i, "");
  const match = stem.match(/^(.*?)[-_]v((?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:\.(?:0|[1-9]\d*))?)$/i);
  if (!match || !match[1].trim()) return { name: stem, version: null };
  return { name: match[1], version: match[2] };
}
function compareVersions(a: Version, b: Version) {
  const left = normalizeVersion(a.version), right = normalizeVersion(b.version);
  return left[0] - right[0] || left[1] - right[1] || left[2] - right[2];
}
function compareCoreVersions(leftValue: string, rightValue: string): number | null {
  const parse = (value: string) => {
    const match = value.trim().match(/^(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:[-+].*)?$/);
    return match ? [Number(match[1]), Number(match[2] || 0), Number(match[3] || 0)] : null;
  };
  const left = parse(leftValue);
  const right = parse(rightValue);
  if (!left || !right) return null;
  return left[0] - right[0] || left[1] - right[1] || left[2] - right[2];
}
function coreVersionState(current: string, version: Version | null): CoreVersionCheck["state"] {
  const compatibility = version?.comfyui;
  if (!compatibility?.minimum && !compatibility?.maximum) return "not_declared";
  if (!current) return "unavailable";
  const minimum = compatibility.minimum;
  const maximum = compatibility.maximum;
  const rangeOrder = minimum && maximum ? compareCoreVersions(minimum, maximum) : null;
  if (minimum && maximum && (rangeOrder === null || rangeOrder > 0)) return "unavailable";
  const belowMinimum = minimum ? compareCoreVersions(current, minimum) : null;
  const aboveMaximum = maximum ? compareCoreVersions(current, maximum) : null;
  if ((minimum && belowMinimum === null) || (maximum && aboveMaximum === null)) return "unavailable";
  return (belowMinimum !== null && belowMinimum < 0) || (aboveMaximum !== null && aboveMaximum > 0) ? "mismatch" : "aligned";
}
function comfyuiCompatibilityLabel(version: Version) {
  const minimum = version.comfyui?.minimum;
  const maximum = version.comfyui?.maximum;
  if (minimum && maximum && minimum === maximum) return t.value("coreVersionExactRequirement", { version: minimum });
  return t.value("coreVersionRangeRequirement", { minimum: minimum || "—", maximum: maximum || "∞" });
}
function coreVersionCheck(version: Version | null, currentValue = status.value?.comfyui_version): CoreVersionCheck {
  const current = currentValue?.trim() || "";
  const state = coreVersionState(current, version);
  if (state === "aligned") {
    return {
      state,
      tone: "ok",
      label: "coreVersionAligned",
      detail: "coreVersionAlignedDetail",
      params: { current, required: version ? comfyuiCompatibilityLabel(version) : "—" },
    };
  }
  if (state === "mismatch") {
    return {
      state,
      tone: "warn",
      label: "coreVersionMismatch",
      detail: "coreVersionMismatchDetail",
      params: { current, required: version ? comfyuiCompatibilityLabel(version) : "—" },
    };
  }
  if (state === "not_declared") {
    return { state, tone: "muted", label: "coreVersionNotDeclared", detail: "coreVersionNotDeclaredDetail" };
  }
  return { state, tone: "muted", label: "coreVersionUnavailable", detail: "coreVersionUnavailableDetail" };
}
function pluginDependencyCheck(version: Version | null): PluginDependencyCheck {
  const total = version?.custom_nodes.length || 0;
  if (!version || !total) {
    return {
      state: "aligned",
      tone: "ok",
      label: "pluginStatusNoDependencies",
      detail: "pluginStatusNoDependenciesDetail",
    };
  }
  const item = selected.value;
  const key = item ? dependencyKey(item, version) : "";
  if (!item || !status.value || dependencyPlanLoading[key] || (activeDependencyOperation.value && isOperationActive(activeDependencyOperation.value))) {
    return {
      state: "checking",
      tone: "muted",
      label: "pluginStatusChecking",
      detail: "pluginStatusCheckingDetail",
      params: { count: total },
    };
  }
  const plan = dependencyPlans[key];
  if (!plan || plan.length < total) {
    return {
      state: "unavailable",
      tone: "muted",
      label: "pluginStatusUnavailable",
      detail: "pluginStatusUnavailableDetail",
      params: { count: total },
    };
  }
  const missing = plan.filter((entry) => entry.action === "install").length;
  const attention = plan.filter((entry) => entry.action !== "keep").length;
  if (missing) {
    return {
      state: "missing",
      tone: "missing",
      label: "pluginStatusMissing",
      detail: "pluginStatusMissingDetail",
      params: { count: missing, total },
    };
  }
  if (attention) {
    return {
      state: "mismatch",
      tone: "warn",
      label: "pluginStatusMismatch",
      detail: "pluginStatusMismatchDetail",
      params: { count: attention, total },
    };
  }
  return {
    state: "aligned",
    tone: "ok",
    label: "pluginStatusAligned",
    detail: "pluginStatusAlignedDetail",
    params: { count: total },
  };
}
const activeCoreCheck = computed(() => coreVersionCheck(activeDetailVersion.value));
const activePluginCheck = computed(() => pluginDependencyCheck(activeDetailVersion.value));
const activeImageCount = computed(() => activeDetailVersion.value?.inputs?.length || 0);
function latest(item: Product) {
  return [...item.versions].sort(compareVersions).at(-1);
}
function productCover(item: Product) {
  return item.cover || latest(item)?.preview || null;
}
function repositoryUrl(item: Product) {
  return `https://github.com/${encodeURIComponent(item.source.owner)}/${encodeURIComponent(item.source.repo)}`;
}
function productRepositoryUrl(item: Product) {
  const path = item.repository_path.split("/").map(encodeURIComponent).join("/");
  return `${repositoryUrl(item)}/tree/HEAD/${path}`;
}
function openDetails(item: Product) {
  selected.value = item;
  selectedDetailVersion.value = latest(item)?.version || "";
  resourceDialog.value = null;
}
async function selectDetailVersion(version: string) {
  selectedDetailVersion.value = version;
  resourceDialog.value = null;
  await nextTick();
  detailReleaseScroll.value?.scrollTo({ top: 0, behavior: "smooth" });
}
function openResourceDialog(kind: ResourceDialog) {
  resourceDialog.value = kind;
}
function closeResourceDialog() {
  resourceDialog.value = null;
}
function closeDetails() {
  resourceDialog.value = null;
  selected.value = null;
}
function productKey(item: Product | null) {
  return item ? `${item.source.owner}/${item.source.repo}/${item.id}` : "";
}
function dependencyKey(item: Product | null, version: Version | null) {
  return item && version ? `${productKey(item)}@${version.version}` : "";
}
function downloadKey(item: Product, version: Version) {
  return `${item.source.owner.toLowerCase()}/${item.source.repo.toLowerCase()}/${item.id}@${version.version}`;
}
function isVersionDownloading(item: Product, version: Version) {
  const key = downloadKey(item, version);
  const owner = item.source.owner.toLowerCase();
  const repo = item.source.repo.toLowerCase();
  return Boolean(downloadOperationIds[key]) || operations.value.some((operation) =>
    operation.kind === "download" && operation.status === "running"
    && String(operation.metadata?.owner || "").toLowerCase() === owner
    && String(operation.metadata?.repo || "").toLowerCase() === repo
    && operation.metadata?.workflow_id === item.id
    && operation.metadata?.version === version.version
  );
}
function dependencyIdentity(item: { task_id?: string; source_url?: string | null; registry_id?: string | null; name?: string }) {
  if (item.task_id) return item.task_id;
  if (item.source_url) return `git:${item.source_url.trim().toLowerCase().replace(/\/$/, "").replace(/\.git$/, "")}`;
  if (item.registry_id) return `manager:${item.registry_id.trim().toLowerCase()}`;
  return `name:${String(item.name || "").trim().toLowerCase()}`;
}
function dependencySourceUrl(item: { source_url?: string | null; registry_id?: string | null }) {
  const source = (item.source_url || "").trim();
  if (/^https:\/\//i.test(source)) return source;
  const registryId = (item.registry_id || "").trim();
  return registryId ? `https://registry.comfy.org/nodes/${encodeURIComponent(registryId)}` : "";
}
const dependencyChangeActions = new Set<DependencyPlan["action"]>(["install", "upgrade", "downgrade"]);
function dependencyActionRequiresSelection(action: DependencyPlan["action"]) {
  return dependencyChangeActions.has(action);
}
function dependencyActionKey(item: DependencyPlan) {
  return `${dependencyIdentity(item)}:${item.requested || ""}:${item.action}`;
}
function dependencyActionSelected(key: string, item: DependencyPlan) {
  return (selectedDependencyActions[key] || []).includes(dependencyActionKey(item));
}
function dependencyChangeCount(key: string) {
  return (dependencyPlans[key] || []).filter((item) => dependencyActionRequiresSelection(item.action)).length;
}
function dependencySelectedChangeCount(key: string) {
  return (dependencyPlans[key] || []).filter((item) => dependencyActionRequiresSelection(item.action) && dependencyActionSelected(key, item)).length;
}
function dependencyNodeKey(item: NodeDependencyInfo) {
  return dependencyIdentity(item);
}
function humanBytes(value: number) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KiB`;
  return `${(value / 1024 / 1024).toFixed(1)} MiB`;
}
function isOperationActive(item: Operation) {
  return item.status === "running" || item.error_code === "dependencies.manager_result_unknown";
}
function publishResultText(operation: Operation | null, key: string) {
  const value = operation?.result?.[key];
  return typeof value === "string" && value ? value : "";
}
function operationTimeLabel(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return operationTimeFormatter.value.format(date);
}
function operationStageLabel(stage: string) {
  return t.value(operationStageMessages[stage] || "stageUnknown", { stage });
}
function isPublishOperation(item: Operation) {
  return item.kind === "publish" || item.kind === "publish-resume";
}
function operationProgressStages(item: Operation) {
  if (item.kind === "download") return downloadProgressStages;
  if (isPublishOperation(item)) return publishProgressStages;
  if (item.kind === "publisher-manage") {
    return managementProgressStages[String(item.metadata?.action || "")] || managementDefaultProgressStages;
  }
  return null;
}
function hasStageProgress(item: Operation) {
  return operationProgressStages(item) !== null;
}
function stageProgress(item: Operation) {
  const stages = operationProgressStages(item) || [];
  const total = stages.length;
  if (item.status === "success" || item.stage === "complete") {
    return { current: total, completed: total, total, percent: 100 };
  }
  const stage = item.status === "failed"
    ? String(item.metadata?.failed_stage || item.stage)
    : item.stage;
  const index = stages.indexOf(stage);
  if (index < 0) return { current: 0, completed: 0, total, percent: 0 };
  return { current: index + 1, completed: index, total, percent: (index / total) * 100 };
}
function stageProgressLabel(item: Operation) {
  const progress = stageProgress(item);
  const stage = item.status === "failed"
    ? String(item.metadata?.failed_stage || item.stage)
    : item.stage;
  return t.value(isPublishOperation(item) ? "publishStageProgress" : "operationStageProgress", {
    current: progress.current,
    total: progress.total,
    stage: operationStageLabel(stage),
  });
}
function operationKindLabel(kind: string, metadata?: Record<string, unknown>) {
  const labels: Record<string, MessageKey> = {
    dependencies: "dependencyInstall",
    download: "operationDownload",
    publish: "operationPublish",
    "publish-resume": "operationPublish",
  };
  if (kind === "publisher-manage") {
    const managementLabels: Record<string, MessageKey> = {
      edit_metadata: "operationEditMetadata",
      archive: "operationArchive",
      unarchive: "operationUnarchive",
      edit_changelog: "operationEditChangelog",
      update_dependencies: "operationUpdateDependencies",
      delete_version: "operationDeleteVersion",
      delete_workflow: "operationDeleteWorkflow",
    };
    return t.value(managementLabels[String(metadata?.action || "")] || "operationManage");
  }
  return t.value(labels[kind] || "operationUnknown", { kind });
}
function localizedBackendError(code: string, params?: Record<string, string | number>) {
  const key = backendErrorMessages[code];
  return key ? t.value(key, params) : t.value("operationFailedDetail", { detail: params?.detail || code });
}
function errorMessage(reason: unknown) {
  if (reason instanceof ApiError && reason.code) return localizedBackendError(reason.code, reason.params);
  return reason instanceof Error ? reason.message : String(reason);
}
function operationErrorMessage(item: Operation) {
  const summary = item.error_code ? localizedBackendError(item.error_code, item.error_params) : "";
  return [summary, ...item.logs].filter(Boolean).join("\n");
}
function updateOperations(items: Operation[]) {
  operations.value = items.filter((item) => !hiddenOperationIds.has(item.id));
}
function prependOperation(item: Operation) {
  if (hiddenOperationIds.has(item.id)) return;
  operations.value = [item, ...operations.value.filter((entry) => entry.id !== item.id)];
}
function hideOperations(ids: string[]) {
  for (const id of ids) hiddenOperationIds.add(id);
  operations.value = operations.value.filter((item) => !hiddenOperationIds.has(item.id));
}
function rememberPublishOperation(id: string) {
  publishOperationId.value = id;
  publishSourceName.value = workflowSourceName.value;
  publishCompletion.value = null;
  try {
    window.sessionStorage.setItem(PUBLISH_OPERATION_KEY, id);
    window.sessionStorage.setItem(PUBLISH_SOURCE_KEY, publishSourceName.value);
  } catch {
    // The current page can still track the operation when browser storage is unavailable.
  }
}
function forgetPublishOperation() {
  publishOperationId.value = "";
  publishSourceName.value = "";
  try {
    window.sessionStorage.removeItem(PUBLISH_OPERATION_KEY);
    window.sessionStorage.removeItem(PUBLISH_SOURCE_KEY);
  } catch {
    // Nothing else is required when browser storage is unavailable.
  }
}
function restorePublishOperation() {
  if (publishOperationId.value) return;
  try {
    publishOperationId.value = window.sessionStorage.getItem(PUBLISH_OPERATION_KEY) || "";
    publishSourceName.value = publishOperationId.value ? window.sessionStorage.getItem(PUBLISH_SOURCE_KEY) || "" : "";
  } catch {
    publishOperationId.value = "";
    publishSourceName.value = "";
  }
}
function syncPublishOperation(items: Operation[]) {
  if (!publishOperationId.value) return;
  const operation = items.find((item) => item.id === publishOperationId.value);
  if (!operation || isOperationActive(operation)) return;
  if (operation.status === "success") {
    if (publishCompletion.value?.id === operation.id && publishStep.value === 4) return;
    publishCompletion.value = operation;
    if (operation.kind === "publish-resume") {
      const tag = String(operation.metadata?.tag || "");
      if (tag) pendingPublications.value = pendingPublications.value.filter((item) => item.tag !== tag);
    }
    publishStep.value = 4;
    drawer.value = false;
    error.value = "";
    notice.value = "";
    void (async () => {
      await refreshSubscribedSource(catalogOperationTarget(operation));
      invalidateCatalogCache();
      await refreshCatalog();
    })().catch((reason) => { error.value = errorMessage(reason); });
    return;
  }
  forgetPublishOperation();
  publishCompletion.value = null;
  notice.value = "";
  error.value = operationErrorMessage(operation) || t.value("operationFailed");
}
async function deleteOperation(item: Operation) {
  if (isOperationActive(item) || activityMutationBusy.value) return;
  deletingOperationIds[item.id] = true;
  error.value = "";
  try {
    await remove(`/operations/${encodeURIComponent(item.id)}`);
    hideOperations([item.id]);
    notice.value = t.value("activityDeleted");
  } catch (reason) {
    if (reason instanceof ApiError && reason.code === "operation.not_found") {
      hideOperations([item.id]);
      return;
    }
    error.value = errorMessage(reason);
  } finally {
    delete deletingOperationIds[item.id];
  }
}
async function clearCompletedOperations() {
  if (!completedOperationCount.value || activityMutationBusy.value) return;
  if (!confirm(t.value("confirmClearActivities", { count: completedOperationCount.value }))) return;
  clearingOperations.value = true;
  error.value = "";
  try {
    const result = await remove<{ deleted: number; ids: string[] }>("/operations/completed");
    const ids = Array.isArray(result.ids) ? result.ids : [];
    hideOperations(ids);
    notice.value = t.value("activitiesCleared", { count: result.deleted });
  } catch (reason) {
    error.value = errorMessage(reason);
  } finally {
    clearingOperations.value = false;
  }
}
function sourceErrorMessage(item: Source) {
  return item.error ? localizedBackendError(item.error) : item.url;
}
function moveToPublishStep(step: PublishStep) {
  if (step === 4 || publishOperationRunning.value) return;
  if (step === 1 || (step === 2 && canConfirmPublishResources.value) || (step === 3 && canFinalizePublish.value)) {
    publishStep.value = step;
  }
}
function otherModelAssets(version: Version) {
  return version.models.filter((model) => model.type !== "loras");
}
function progressPercent(progress: { received: number; total: number }) {
  if (progress.total <= 0) return 0;
  return Math.min(100, Math.max(0, (progress.received / progress.total) * 100));
}
function clearMessages() {
  error.value = "";
  notice.value = "";
}
function handleWorkspaceShortcut(event: KeyboardEvent) {
  const target = event.target as HTMLElement | null;
  const editing = target?.matches("input, textarea, select, [contenteditable='true']");
  if (event.key === "/" && !editing && tab.value === "subscribe") {
    event.preventDefault();
    searchInput.value?.focus();
  } else if (event.key === "Escape" && settingsOpen.value) {
    closeSettings();
  } else if (event.key === "Escape" && resourceDialog.value) {
    closeResourceDialog();
  } else if (event.key === "Escape" && document.activeElement === searchInput.value && search.value) {
    search.value = "";
  }
}
function closeHubPage() {
  if (window.parent !== window) {
    window.parent.postMessage({ type: "AAALICE_WORKFLOW_HUB_CLOSE" }, window.location.origin);
    return;
  }
  window.close();
}
async function openSourceComposer() {
  sourceComposerOpen.value = true;
  await nextTick();
  sourceInput.value?.focus();
}
function applyCatalog(snapshot: CatalogSnapshot<Source, Product>) {
  sources.value = snapshot.sources;
  products.value = snapshot.products;
  if (selected.value) {
    selected.value = snapshot.products.find((item) => productKey(item) === productKey(selected.value)) || null;
  }
}

function invalidateCatalogRequests() {
  catalogRequests.invalidate();
}

function invalidateCatalogCache() {
  invalidateCatalogRequests();
  const scope = status.value?.catalog_cache_scope;
  if (scope) clearCatalogCache(scope);
}

function requestCatalog() {
  return catalogRequests.get();
}

let catalogRefreshInFlight: Promise<void> | null = null;
function refreshCatalog(): Promise<void> {
  if (catalogRefreshInFlight) return catalogRefreshInFlight;
  const task = (async () => {
    catalogRefreshing.value = true;
    try {
      let snapshot = await requestCatalog();
      while (!catalogRequests.isCurrent()) snapshot = await requestCatalog();
      applyCatalog(snapshot);
      const scope = status.value?.catalog_cache_scope;
      if (scope) writeCatalogCache(scope, snapshot);
    } finally {
      catalogRefreshing.value = false;
    }
  })();
  catalogRefreshInFlight = task;
  void task.then(
    () => { if (catalogRefreshInFlight === task) catalogRefreshInFlight = null; },
    () => { if (catalogRefreshInFlight === task) catalogRefreshInFlight = null; },
  );
  return task;
}

function restoreCatalogCache(s: Status) {
  const scope = s.catalog_cache_scope;
  if (!scope) return null;
  const cached = readCatalogCache<Source, Product>(scope);
  if (cached) applyCatalog(cached);
  return cached;
}

let remoteCatalogRefreshInFlight: Promise<number> | null = null;
function refreshRemoteCatalog(force = true): Promise<number> {
  if (remoteCatalogRefreshInFlight) return remoteCatalogRefreshInFlight;
  const task = (async () => {
    catalogRefreshing.value = true;
    try {
      invalidateCatalogRequests();
      const result = await post<CatalogRefreshResult>("/subscriptions/refresh-all", { force });
      applyCatalog({ sources: result.sources, products: result.products });
      if (!result.failed.length) {
        const scope = status.value?.catalog_cache_scope;
        if (scope) writeCatalogCache(scope, { sources: result.sources, products: result.products });
      }
      return result.failed.length;
    } finally {
      catalogRefreshing.value = false;
    }
  })();
  remoteCatalogRefreshInFlight = task;
  void task.then(
    () => { if (remoteCatalogRefreshInFlight === task) remoteCatalogRefreshInFlight = null; },
    () => { if (remoteCatalogRefreshInFlight === task) remoteCatalogRefreshInFlight = null; },
  );
  return task;
}

function load(): Promise<void> {
  if (loadInFlight) return loadInFlight;
  const task = (async () => {
    const showInitialLoading = !loadAttempted;
    if (showInitialLoading) loading.value = true;
    restorePublishOperation();
    clearMessages();
    const catalogRequest = requestCatalog();
    void catalogRequest.catch(() => undefined);
    try {
      const [s, ops] = await Promise.all([
        api<Status>("/status"),
        api<{ items: Operation[] }>("/operations"),
      ]);
      status.value = s;
      updateOperations(ops.items);
      syncPublishOperation(ops.items);
      for (const operation of ops.items) {
        if (operation.kind === "publisher-manage" && operation.status === "running") {
          publisherManagementOperationIds[operation.id] = true;
          publisherManagementOperationSynced[operation.id] = false;
        }
      }
      const cached = restoreCatalogCache(s);
      if (cached) loading.value = false;
      try {
        const snapshot = await catalogRequest;
        applyCatalog(snapshot);
        if (s.catalog_cache_scope) writeCatalogCache(s.catalog_cache_scope, snapshot);
      } catch (reason) {
        if (!cached) throw reason;
        applyCatalog(cached);
        error.value = errorMessage(reason);
      }
      if (!s.github.authenticated) {
        repositories.value = [];
        pendingPublications.value = [];
        publisherLoaded = false;
      } else if (tab.value === "publish" || tab.value === "manage") {
        await loadPublisherWorkspace();
      }
    } catch (reason) {
      error.value = errorMessage(reason);
    } finally {
      loading.value = false;
      loadAttempted = true;
    }
  })();
  loadInFlight = task;
  void task.then(
    () => { if (loadInFlight === task) loadInFlight = null; },
    () => { if (loadInFlight === task) loadInFlight = null; },
  );
  return task;
}
async function withBusy(name: string, action: () => Promise<void>) {
  busy.value = name;
  clearMessages();
  try { await action(); } catch (reason) { error.value = errorMessage(reason); }
  finally { busy.value = ""; }
}
function openSettings() {
  const current = status.value?.settings;
  settingsDraft.auto_update_check = current?.auto_update_check ?? true;
  settingsDraft.update_check_interval_hours = current?.update_check_interval_hours ?? 24;
  settingsError.value = "";
  settingsSaved.value = false;
  settingsOpen.value = true;
}
function closeSettings() {
  if (settingsSaving.value) return;
  settingsOpen.value = false;
  settingsError.value = "";
}
function notifyHostSettingsChanged() {
  const targets = new Set<Window>();
  if (window.parent !== window) targets.add(window.parent);
  if (window.opener && !window.opener.closed) targets.add(window.opener);
  for (const target of targets) target.postMessage({ type: "AAALICE_WORKFLOW_HUB_SETTINGS_CHANGED" }, window.location.origin);
}
async function saveSettings() {
  const interval = Number(settingsDraft.update_check_interval_hours);
  if (!Number.isInteger(interval) || interval < 1 || interval > 168) {
    settingsError.value = t.value("updateCheckIntervalInvalid", { minimum: 1, maximum: 168 });
    settingsSaved.value = false;
    return;
  }
  settingsSaving.value = true;
  settingsError.value = "";
  settingsSaved.value = false;
  try {
    const saved = await post<NonNullable<Status["settings"]>>("/settings", {
      auto_update_check: settingsDraft.auto_update_check,
      update_check_interval_hours: interval,
    });
    settingsDraft.auto_update_check = saved.auto_update_check;
    settingsDraft.update_check_interval_hours = saved.update_check_interval_hours;
    if (status.value) status.value.settings = saved;
    settingsSaved.value = true;
    notifyHostSettingsChanged();
  } catch (reason) {
    settingsError.value = errorMessage(reason);
  } finally {
    settingsSaving.value = false;
  }
}
async function addSource() {
  sourceUrl.value = sourceUrl.value.trim();
  if (!sourceUrl.value) return;
  await withBusy("add-source", async () => {
    await post("/subscriptions", { url: sourceUrl.value });
    sourceUrl.value = "";
    invalidateCatalogCache();
    await refreshCatalog();
  });
}
async function refreshSource(item: Source) {
  await withBusy(`refresh-${item.owner}-${item.repo}`, async () => {
    await post(`/subscriptions/${item.owner}/${item.repo}/refresh`, {});
    invalidateCatalogCache();
    await refreshCatalog();
  });
}
async function refreshAllSources() {
  await withBusy("refresh-all", async () => {
    const failed = await refreshRemoteCatalog();
    notice.value = failed ? t.value("someSourcesFailed", { count: failed }) : t.value("allSourcesRefreshed");
  });
}
async function removeSource(item: Source) {
  if (!confirm(t.value("confirmRemoveSource"))) return;
  await withBusy(`remove-${item.owner}-${item.repo}`, async () => {
    await remove(`/subscriptions/${item.owner}/${item.repo}`);
    invalidateCatalogCache();
    await refreshCatalog();
  });
}
function downloadNeedsPreflight(check: DownloadPreflight) {
  return check.core.state === "mismatch"
    || check.core.state === "unavailable"
    || !!check.environmentError
    || !!check.dependencyError
    || check.dependencies.some((entry) => entry.action !== "keep");
}
async function inspectDownloadReadiness(item: Product, version: Version): Promise<DownloadPreflight> {
  const key = dependencyKey(item, version);
  dependencyAlignment[key] = true;
  let currentCoreVersion = "";
  let environmentError = "";
  try {
    const latestStatus = await api<Status>("/status");
    status.value = latestStatus;
    currentCoreVersion = latestStatus.comfyui_version || "";
  } catch (reason) {
    environmentError = errorMessage(reason);
  }
  let dependencies: DependencyPlan[] = [];
  let dependencyError = "";
  if (version.custom_nodes.length) {
    try {
      dependencies = await fetchDependencyPlan(item, version);
    } catch (reason) {
      dependencyError = errorMessage(reason);
    }
  } else {
    dependencyPlans[key] = [];
    selectedDependencyActions[key] = [];
  }
  return {
    item,
    version,
    core: coreVersionCheck(version, environmentError ? "" : currentCoreVersion),
    currentCoreVersion,
    environmentError,
    dependencies,
    dependencyError,
    syncing: false,
    syncOperationId: "",
    syncError: "",
  };
}
async function startDownload(item: Product, version: Version) {
  downloadCompletion.value = null;
  const result = await post<{ operation_id: string }>("/workflows/download", {
    owner: item.source.owner, repo: item.source.repo, workflow_id: item.id, version: version.version,
  });
  downloadOperationIds[downloadKey(item, version)] = result.operation_id;
  notice.value = t.value("downloadStarted");
  drawer.value = true;
  await pollOperations();
}
async function download(item: Product, version: Version) {
  if (isVersionDownloading(item, version)) return;
  let check: DownloadPreflight | null = null;
  await withBusy("download-check", async () => {
    check = await inspectDownloadReadiness(item, version);
  });
  if (!check) return;
  if (downloadNeedsPreflight(check)) {
    downloadPreflight.value = check;
    return;
  }
  await withBusy("download", () => startDownload(item, version));
}
function closeDownloadPreflight() {
  if (downloadPreflight.value?.syncing) return;
  downloadPreflight.value = null;
}
async function skipDownloadPreflight() {
  const check = downloadPreflight.value;
  if (!check || check.syncing) return;
  downloadPreflight.value = null;
  await withBusy("download", () => startDownload(check.item, check.version));
}
async function retryDownloadPreflight() {
  const check = downloadPreflight.value;
  if (!check || check.syncing) return;
  downloadPreflight.value = null;
  await download(check.item, check.version);
}
async function syncDownloadDependencies() {
  const check = downloadPreflight.value;
  if (!check || check.syncing || !preflightSyncableDependencies.value.length) return;
  const key = dependencyKey(check.item, check.version);
  const actions = preflightSyncableDependencies.value;
  check.syncing = true;
  check.syncError = "";
  await withBusy("dependency-execute", async () => {
    try {
      if (actions.some((entry) => entry.installer === "manager")) ensureManagerSocket();
      const result = await post<{ operation_id: string }>("/workflows/dependencies/execute", {
        confirmed: true,
        version_policy: "align",
        metadata: { workflow_key: key },
        actions,
      });
      dependencyOperationIds[key] = result.operation_id;
      dependencyOperationSynced[key] = false;
      check.syncOperationId = result.operation_id;
      drawer.value = true;
      try {
        const operation = await api<Operation>(`/operations/${result.operation_id}`);
        prependOperation(operation);
      } catch {
        // The operation poll remains the source of truth if the initial detail read races the start.
      }
      void pollOperations();
    } catch (reason) {
      check.syncing = false;
      check.syncError = errorMessage(reason);
    }
  });
}
async function deleteLocalVersion(item: Product, version: Version) {
  if (!confirm(t.value("confirmDeleteLocalVersion", { version: version.version }))) return;
  await withBusy("delete-local", async () => {
    await remove("/workflows/local", {
      owner: item.source.owner, repo: item.source.repo, workflow_id: item.id, version: version.version,
    });
    invalidateCatalogCache();
    await refreshCatalog();
  });
}
function downloadOperationTarget(operation: Operation | null) {
  const metadata = operation?.metadata || {};
  const owner = String(metadata.owner || "");
  const repo = String(metadata.repo || "");
  const workflowId = String(metadata.workflow_id || "");
  const version = String(metadata.version || "");
  return owner && repo && workflowId && version ? { owner, repo, workflow_id: workflowId, version } : null;
}
function dismissDownloadCompletion() {
  downloadCompletion.value = null;
}
async function revealDownloadCompletion() {
  const target = downloadOperationTarget(downloadCompletion.value);
  if (!target) {
    error.value = t.value("operationFailed");
    return;
  }
  await withBusy("reveal-download", async () => {
    await post("/workflows/local/reveal", target);
    notice.value = t.value("workflowFolderOpened");
  });
}
async function revealLocalVersion(item: Product, version: Version) {
  await withBusy("reveal-local", async () => {
    await post("/workflows/local/reveal", {
      owner: item.source.owner, repo: item.source.repo, workflow_id: item.id, version: version.version,
    });
  });
}
let workflowLoadRequestId = 0;
async function loadWorkflowOnHost(path: string, workflow: Record<string, unknown>) {
  const targets = new Set<Window>();
  if (window.parent !== window) targets.add(window.parent);
  if (window.opener && !window.opener.closed) targets.add(window.opener);
  if (!targets.size) throw new Error(t.value("openFromToolbar"));

  const requestId = String(++workflowLoadRequestId);
  await new Promise<void>((resolve, reject) => {
    const cleanup = () => {
      window.clearTimeout(timeout);
      window.removeEventListener("message", handleResult);
    };
    const handleResult = (event: MessageEvent) => {
      if (
        event.origin !== window.location.origin ||
        !targets.has(event.source as Window) ||
        event.data?.type !== "AAALICE_WORKFLOW_HUB_LOAD_WORKFLOW_RESULT" ||
        event.data?.requestId !== requestId
      ) return;
      cleanup();
      if (event.data?.ok) {
        resolve();
        return;
      }
      if (event.data?.errorCode === "workflow_load.invalid_path" || event.data?.errorCode === "workflow_load.invalid_payload") {
        reject(new Error(t.value("workflowLoadInvalidData")));
        return;
      }
      if (event.data?.errorCode === "workflow_load.missing_from_storage") {
        const missingPath = String(event.data?.errorParams?.path || path);
        reject(new Error(t.value("workflowLoadMissingFromStorage", { path: missingPath })));
        return;
      }
      const detail = typeof event.data?.detail === "string" ? event.data.detail : t.value("currentCanvasUnavailable");
      reject(new Error(t.value("workflowLoadFailed", { detail })));
    };
    const timeout = window.setTimeout(() => {
      cleanup();
      reject(new Error(t.value("workflowLoadTimedOut")));
    }, 30_000);
    window.addEventListener("message", handleResult);
    const message = { type: "AAALICE_WORKFLOW_HUB_LOAD_WORKFLOW", requestId, path, workflow };
    for (const target of targets) target.postMessage(message, window.location.origin);
  });
}
async function loadLocalVersion(item: Product, version: Version) {
  await withBusy("load-local", async () => {
    const result = await post<{ path: string; workflow: Record<string, unknown> }>("/workflows/local/load", {
      owner: item.source.owner, repo: item.source.repo, workflow_id: item.id, version: version.version,
    });
    await loadWorkflowOnHost(result.path, result.workflow);
    notice.value = t.value("workflowLoaded");
    closeHubPage();
  });
}
function clearFinishedDependencyExecution(key: string) {
  const operationId = dependencyOperationIds[key];
  if (!operationId) return;
  const operation = operations.value.find((item) => item.id === operationId);
  if (operation && isOperationActive(operation)) return;
  delete dependencyOperationIds[key];
  delete dependencyOperationSynced[key];
}
async function planDependencies(item: Product, version: Version) {
  clearFinishedDependencyExecution(dependencyKey(item, version));
  await withBusy("dependency-plan", async () => { await fetchDependencyPlan(item, version); });
}
async function fetchDependencyPlan(item: Product, version: Version): Promise<DependencyPlan[]> {
  const key = dependencyKey(item, version);
  const generation = (dependencyPlanGeneration[key] || 0) + 1;
  dependencyPlanGeneration[key] = generation;
  dependencyPlanLoading[key] = true;
  const alignVersions = dependencyAlignment[key] ?? true;
  dependencyAlignment[key] = alignVersions;
  try {
    const result = await post<{ items: DependencyPlan[] }>("/workflows/dependencies/plan", {
      dependencies: version.custom_nodes,
      version_policy: alignVersions ? "align" : "warn",
    });
    if (dependencyPlanGeneration[key] !== generation) return dependencyPlans[key] || [];
    dependencyPlans[key] = result.items;
    selectedDependencyActions[key] = result.items
      .map((entry) => ({ entry, id: dependencyActionKey(entry) }))
      .filter(({ entry }) => dependencyActionRequiresSelection(entry.action))
      .map(({ id }) => id);
    return result.items;
  } catch (reason) {
    if (dependencyPlanGeneration[key] === generation) {
      delete dependencyPlans[key];
      delete selectedDependencyActions[key];
    }
    throw reason;
  } finally {
    if (dependencyPlanGeneration[key] === generation) dependencyPlanLoading[key] = false;
  }
}
async function toggleDependencyAlignment(item: Product, version: Version, enabled: boolean) {
  const key = dependencyKey(item, version);
  dependencyAlignment[key] = enabled;
  clearFinishedDependencyExecution(key);
  await withBusy("dependency-plan", async () => { await fetchDependencyPlan(item, version); });
}
async function autoPlanDependencies(item: Product | null, version: Version | null) {
  if (!item || !version || !version.custom_nodes.length) return;
  if (!status.value?.git.available && !status.value?.manager?.compatible) return;
  const key = dependencyKey(item, version);
  if (dependencyPlans[key] || dependencyPlanLoading[key]) return;
  try {
    await fetchDependencyPlan(item, version);
  } catch {
    // A failed background pre-check just leaves the list without status badges;
    // the manual check button still surfaces the error.
  }
}
watch([selected, activeDetailVersion, status], ([item, version]) => {
  void autoPlanDependencies(item, version);
});
watch(operations, (items) => {
  const check = downloadPreflight.value;
  if (!check?.syncing || !check.syncOperationId) return;
  const operation = items.find((item) => item.id === check.syncOperationId);
  if (!operation || isOperationActive(operation)) return;
  if (operation.status !== "success") {
    check.syncing = false;
    check.syncOperationId = "";
    check.syncError = operation.error_code
      ? localizedBackendError(operation.error_code, operation.error_params)
      : t.value("dependencySyncFailed");
    return;
  }
  downloadPreflight.value = null;
  void download(check.item, check.version);
});
function dependencyWarning(entry: DependencyPlan) {
  if (!entry.warning_code) return "";
  const key = backendErrorMessages[entry.warning_code];
  return key ? t.value(key, entry.warning_params) : entry.warning_code;
}
function dependencyPlanEntry(node: NodeDependencyInfo): DependencyPlan | null {
  const item = selected.value;
  const version = activeDetailVersion.value;
  if (!item || !version) return null;
  const plan = dependencyPlans[dependencyKey(item, version)];
  if (!plan) return null;
  return plan.find((entry) => dependencyIdentity(entry) === dependencyNodeKey(node)) || null;
}
const dependencyActionLabels: Record<DependencyPlan["action"], MessageKey> = {
  keep: "depStatusInstalled",
  install: "depStatusMissing",
  newer: "depStatusNewer",
  upgrade: "depStatusUpgrade",
  downgrade: "depStatusDowngrade",
  conflict: "depStatusConflict",
  manual: "depStatusManual",
  unknown: "depStatusUnknown",
};
function dependencyActionTone(action: DependencyPlan["action"]) {
  if (action === "install") return "missing";
  if (action === "upgrade" || action === "downgrade" || action === "conflict") return "warn";
  return "muted";
}
function dependencyInstallerAvailable(entry: DependencyPlan) {
  return entry.installer === "manager" ? !!status.value?.manager?.compatible : !!status.value?.git.available;
}
function dependencyActionAvailable(key: string, id: string) {
  const plan = dependencyPlans[key] || [];
  const index = plan.findIndex((entry) => dependencyActionKey(entry) === id);
  return index >= 0 && dependencyInstallerAvailable(plan[index]);
}
function toggleDependencyAction(key: string, id: string, checked: boolean) {
  const values = selectedDependencyActions[key] || [];
  selectedDependencyActions[key] = checked ? [...new Set([...values, id])] : values.filter(value => value !== id);
}
function toggleDependencyRow(key: string, entry: DependencyPlan | null) {
  if (!entry || !dependencyActionRequiresSelection(entry.action) || !dependencyInstallerAvailable(entry)) return;
  toggleDependencyAction(key, dependencyActionKey(entry), !dependencyActionSelected(key, entry));
}
async function executeDependencyPlan(item: Product | null, version: Version | null) {
  if (!item || !version) return;
  const key = dependencyKey(item, version);
  const selectedIds = new Set(selectedDependencyActions[key] || []);
  const actions = (dependencyPlans[key] || []).filter((entry) => selectedIds.has(dependencyActionKey(entry)));
  await withBusy("dependency-execute", async () => {
    if (actions.some((entry) => entry.installer === "manager")) ensureManagerSocket();
    const result = await post<{ operation_id: string }>("/workflows/dependencies/execute", {
      confirmed: true,
      version_policy: dependencyAlignment[key] === false ? "warn" : "align",
      metadata: { workflow_key: key },
      actions,
    });
    dependencyOperationIds[key] = result.operation_id;
    dependencyOperationSynced[key] = false;
    try {
      const operation = await api<Operation>(`/operations/${result.operation_id}`);
      prependOperation(operation);
    } catch {
      // Polling below remains the source of truth if the initial detail read races the operation.
    }
    void pollOperations();
  });
}
function ensureManagerSocket() {
  if (managerSocket && managerSocket.readyState <= WebSocket.OPEN) return;
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${protocol}://${window.location.host}/ws?clientId=workflow-hub-progress`);
  socket.addEventListener("message", (event) => {
    let payload: { type?: string; data?: Record<string, unknown> };
    try { payload = JSON.parse(String(event.data)); } catch { return; }
    if (payload.type === "cm-queue-status" && payload.data) handleManagerQueueEvent(payload.data);
  });
  managerSocket = socket;
}
function handleManagerQueueEvent(data: Record<string, unknown>) {
  if (data.status !== "done" || typeof data.nodepack_result !== "object" || !data.nodepack_result) return;
  const results = data.nodepack_result as Record<string, unknown>;
  for (const operation of operations.value) {
    if (!isOperationActive(operation) || operation.kind !== "dependencies" || !Array.isArray(operation.result?.tasks)) continue;
    const updates: Record<string, { state: "success" | "failed"; message: string }> = {};
    for (const task of operation.result.tasks as DependencyResult[]) {
      const registryId = String(task.registry_id || "");
      const message = results[registryId];
      if (!registryId || typeof message !== "string") continue;
      const override = {
        state: message === "success" ? "success" : "failed",
        message: message === "success" ? "" : message,
      } as const;
      updates[registryId] = override;
      pendingManagerTaskOverrides[registryId] = override;
      managerTaskOverrides[`${operation.id}:${registryId}`] = override;
    }
    syncManagerResults(operation, updates);
  }
}
function syncManagerResults(operation: Operation, updates: Record<string, { state: "success" | "failed"; message: string }>) {
  if (!Object.keys(updates).length || managerResultSyncing.has(operation.id)) return;
  managerResultSyncing.add(operation.id);
  void post<Operation>(`/operations/${operation.id}/manager-results`, { results: updates })
    .then((updated) => {
      operations.value = operations.value.map((item) => item.id === updated.id ? updated : item);
      for (const registryId of Object.keys(updates)) delete pendingManagerTaskOverrides[registryId];
    })
    .catch(() => undefined)
    .finally(() => managerResultSyncing.delete(operation.id));
}
function scheduleOperationPoll() {
  window.clearTimeout(operationTimer);
  operationTimer = window.setTimeout(() => void pollOperations(), 1000);
}
async function pollOperations() {
  if (operationPollInFlight) return;
  operationPollInFlight = true;
  const activeBefore = new Map(
    operations.value.filter(isOperationActive).map((operation) => [operation.id, operation]),
  );
  const trackedDownloadIds = new Set(Object.values(downloadOperationIds));
  let catalogReloaded = false;
  try {
    updateOperations((await api<{ items: Operation[] }>("/operations")).items);
    syncPublishOperation(operations.value);
    for (const [operationId] of Object.entries(publisherManagementOperationIds)) {
      const operation = operations.value.find((item) => item.id === operationId);
      if (!operation) {
        delete publisherManagementOperationIds[operationId];
        delete publisherManagementOperationSynced[operationId];
        continue;
      }
      if (operation.status === "running" || publisherManagementOperationSynced[operationId]) continue;
      publisherManagementOperationSynced[operationId] = true;
      const target = managementOperationTarget(operation);
      try {
        if (operation.status === "success") {
          await reloadAfterManage(target);
          catalogReloaded = true;
          notice.value = t.value("operationCompleted", { operation: operationKindLabel(operation.kind, operation.metadata) });
        } else {
          if (target && manageRepositoryFullName().toLowerCase() === target.toLowerCase()) await loadManaged();
          error.value = operationErrorMessage(operation) || t.value("operationFailed");
        }
      } catch (reason) {
        error.value = errorMessage(reason);
      } finally {
        delete publisherManagementOperationIds[operationId];
        delete publisherManagementOperationSynced[operationId];
      }
    }
    for (const [key, operationId] of Object.entries(downloadOperationIds)) {
      const operation = operations.value.find((item) => item.id === operationId);
      if (!operation || operation.status !== "running") delete downloadOperationIds[key];
    }
    for (const operation of operations.value) {
      if (isOperationActive(operation) && operation.kind === "dependencies" && Array.isArray(operation.result?.tasks)) {
        const updates: Record<string, { state: "success" | "failed"; message: string }> = {};
        for (const task of operation.result.tasks as DependencyResult[]) {
          const registryId = String(task.registry_id || "");
          const override = registryId ? pendingManagerTaskOverrides[registryId] : undefined;
          if (registryId && override) updates[registryId] = override;
        }
        syncManagerResults(operation, updates);
      }
      const workflowKey = typeof operation.metadata?.workflow_key === "string" ? operation.metadata.workflow_key : "";
      if (operation.kind === "dependencies" && workflowKey && isOperationActive(operation) && !dependencyOperationIds[workflowKey]) {
        dependencyOperationIds[workflowKey] = operation.id;
        dependencyOperationSynced[workflowKey] = false;
      }
    }
    for (const [key, operationId] of Object.entries(dependencyOperationIds)) {
      const operation = operations.value.find((item) => item.id === operationId);
      if (!operation) {
        delete dependencyOperationIds[key];
        delete dependencyOperationSynced[key];
        continue;
      }
      if (isOperationActive(operation) || dependencyOperationSynced[key]) continue;
      dependencyOperationSynced[key] = true;
      if (selected.value && activeDetailVersion.value && key === dependencyKey(selected.value, activeDetailVersion.value)) {
        try { await fetchDependencyPlan(selected.value, activeDetailVersion.value); } catch { /* manual check remains available */ }
      }
    }
    const finishedDownloads = operations.value.filter((operation) =>
      operation.kind === "download"
      && operation.status !== "running"
      && (activeBefore.has(operation.id) || trackedDownloadIds.has(operation.id))
    );
    const completedDownload = finishedDownloads.find((operation) => operation.status === "success");
    const failedDownload = finishedDownloads.find((operation) => operation.status === "failed");
    if (completedDownload) {
      downloadCompletion.value = completedDownload;
      notifyHostUpdatesChanged();
      if (!catalogReloaded) {
        invalidateCatalogCache();
        await refreshCatalog();
        catalogReloaded = true;
      }
    }
    if (failedDownload) error.value = operationErrorMessage(failedDownload) || t.value("operationFailed");
    if (operations.value.some(isOperationActive)) scheduleOperationPoll();
  } catch (reason) {
    error.value = errorMessage(reason);
    scheduleOperationPoll();
  } finally {
    operationPollInFlight = false;
  }
}
async function refreshStartupCatalog() {
  catalogRefreshing.value = true;
  try {
    type RevalidationResult = { catalog_changed?: boolean; checked?: boolean; failed?: boolean };
    let result = await post<RevalidationResult>("/update-notifications", { revalidate: true });
    if (!result.checked && !result.failed) {
      result = await post<RevalidationResult>("/update-notifications", { revalidate: true });
    }
    if (result.catalog_changed || result.failed) {
      invalidateCatalogCache();
      await refreshCatalog();
    }
  } catch (reason) {
    error.value = errorMessage(reason);
  } finally {
    catalogRefreshing.value = false;
  }
}

function notifyHostUpdatesChanged() {
  const message = { type: "AAALICE_WORKFLOW_HUB_UPDATES_CHANGED" };
  if (window.parent !== window) window.parent.postMessage(message, window.location.origin);
  if (window.opener && !window.opener.closed) window.opener.postMessage(message, window.location.origin);
}

function requestCurrentCanvasWorkflow() {
  const message = { type: "AAALICE_WORKFLOW_HUB_REQUEST_CURRENT_WORKFLOW" };
  const targets = new Set<Window>();
  if (window.parent !== window) targets.add(window.parent);
  if (window.opener && !window.opener.closed) targets.add(window.opener);
  for (const target of targets) target.postMessage(message, window.location.origin);
  if (!targets.size) {
    canvasWorkflowError.value = t.value("openFromToolbar");
  }
}
async function handleHubMessage(event: MessageEvent) {
  if (event.origin !== window.location.origin || event.data?.type !== "AAALICE_WORKFLOW_HUB_CURRENT_WORKFLOW") return;
  const current = event.data?.workflow;
  if (!current || typeof current !== "object" || Array.isArray(current)) {
    canvasWorkflowError.value = event.data?.error || t.value("currentCanvasUnavailable");
    resourceScanPending.value = false;
    return;
  }
  canvasWorkflowError.value = "";
  dependencyScanError.value = "";
  resourceScanPending.value = true;
  imageReferences.value = [];
  loraReferences.value = [];
  scannedPluginDependencies.value = [];
  selectedPluginKeys.value = [];
  const filename = String(event.data?.filename || t.value("untitledWorkflowFile"));
  const sourceChanged = !workflow.value || workflowSourceName.value !== filename;
  workflow.value = current as Record<string, unknown>;
  workflowSourceName.value = filename;
  const samePublishedSource = !!publishSourceName.value && publishSourceName.value === filename;
  if (sourceChanged && publishStep.value === 4 && !samePublishedSource) {
    forgetPublishOperation();
    publishCompletion.value = null;
    publishDraft.value = null;
    publishStep.value = 1;
  }
  if (sourceChanged) {
    const parsed = parseWorkflowFilename(filename);
    form.name = parsed.name;
    form.version = parsed.version || "1.0";
    form.id = "";
  }
  try {
    await scanWorkflowAssets();
  } catch (reason) {
    canvasWorkflowError.value = errorMessage(reason);
  }
  try {
    await scanDependencies();
    dependencyScanError.value = "";
  } catch (reason) {
    dependencyScanError.value = errorMessage(reason);
  } finally {
    resourceScanPending.value = false;
  }
}
async function scanDependencies() {
  const result = await post<{ items: ScannedNodeDependency[] }>("/publisher/scan-dependencies", {});
  scannedPluginDependencies.value = result.items;
  selectedPluginKeys.value = result.items.map(pluginKey);
  syncSelectedPlugins();
}
async function scanWorkflowAssets() {
  if (!workflow.value) return;
  const result = await post<{ images: AssetReference[]; loras: AssetReference[] }>("/publisher/scan-assets", {
    workflow: workflow.value,
  });
  imageReferences.value = result.images;
  loraReferences.value = result.loras;
}
function generatedWorkflowId(name: string, category = form.category.trim()) {
  const source = `${category}-${name}`;
  const normalized = source.normalize("NFKD").toLocaleLowerCase()
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 55);
  let hash = 2166136261;
  for (const character of source) {
    hash ^= character.codePointAt(0) || 0;
    hash = Math.imul(hash, 16777619);
  }
  const suffix = (hash >>> 0).toString(36);
  return normalized ? `${normalized}-${suffix}` : `workflow-${suffix}`;
}
function syncCatalogProductByName() {
  const matches = publishCatalogProducts.value.filter(
    (item) => item.name.trim().toLocaleLowerCase() === form.name.trim().toLocaleLowerCase()
  );
  const category = form.category.trim().toLocaleLowerCase();
  const product = category
    ? matches.find((item) => item.category.trim().toLocaleLowerCase() === category)
    : (matches.length === 1 ? matches[0] : undefined);
  if (!product) {
    selectedCatalogProductId.value = "";
    form.id = "";
    return;
  }
  selectedCatalogProductId.value = product.id;
  Object.assign(form, {
    id: product.id,
    category: product.category,
    summary: product.summary,
    description: product.description,
    tags: product.tags.join(", "),
  });
}
async function loadPublisherWorkspace(force = false): Promise<void> {
  if (!status.value?.github.authenticated) return;
  if (publisherLoaded && !force) return;
  if (publisherLoadInFlight) return publisherLoadInFlight;
  const task = (async () => {
    publisherLoading.value = true;
    try {
      const [repos, pending] = await Promise.all([
        api<{ items: PublishRepository[] }>("/github/repositories"),
        api<{ items: { tag: string }[] }>("/publisher/pending"),
      ]);
      repositories.value = repos.items;
      let remembered = "";
      try {
        remembered = window.localStorage.getItem(LAST_PUBLISH_REPOSITORY_KEY) || "";
      } catch {
        // Browser storage may be unavailable in hardened embedded views.
      }
      form.repository_url = resolvePublishRepositoryUrl(repositories.value, form.repository_url, remembered);
      await applySelectedRepository();
      pendingPublications.value = pending.items;
      publisherLoaded = true;
    } catch (reason) {
      publisherLoaded = false;
      if (reason instanceof ApiError && reason.status === 401 && status.value) {
        status.value.github.authenticated = false;
        repositories.value = [];
        pendingPublications.value = [];
      }
      throw reason;
    } finally {
      publisherLoading.value = false;
    }
  })();
  publisherLoadInFlight = task;
  void task.finally(() => {
    if (publisherLoadInFlight === task) publisherLoadInFlight = null;
  }).catch(() => undefined);
  return task;
}

async function enterPublish() {
  tab.value = "publish";
  requestCurrentCanvasWorkflow();
  try {
    await loadPublisherWorkspace();
  } catch (reason) {
    error.value = errorMessage(reason);
  }
}

async function applySelectedRepository() {
  error.value = "";
  const fullName = form.repository_url.replace(/^https:\/\/github\.com\//i, "").replace(/\/+$/, "");
  const repository = repositories.value.find(item => item.full_name.toLocaleLowerCase() === fullName.toLocaleLowerCase());
  if (!repository) {
    publishCatalogProducts.value = [];
    repositoryCategories.value = [];
    return;
  }
  const [owner, name] = repository.full_name.split("/", 2);
  form.repository_name = repository.name || name;
  form.author = repository.owner || owner;
  form.repository_description = repository.description || "";
  try {
    window.localStorage.setItem(LAST_PUBLISH_REPOSITORY_KEY, form.repository_url);
  } catch {
    // Repository selection still works for this session when storage is unavailable.
  }
  try {
    const catalog = await api<{ categories: string[]; workflows: PublishCatalogProduct[] }>(
      `/publisher/catalog/${encodeURIComponent(owner)}/${encodeURIComponent(name)}`
    );
    repositoryCategories.value = catalog.categories;
    publishCatalogProducts.value = catalog.workflows;
  } catch (reason) {
    repositoryCategories.value = [];
    publishCatalogProducts.value = [];
    error.value = errorMessage(reason);
  }
  if (!publishCatalogProducts.value.some((item) => item.id === selectedCatalogProductId.value)) {
    selectedCatalogProductId.value = "";
    form.id = "";
  }
  syncCatalogProductByName();
}
async function createRepository() {
  await withBusy("create-repository", async () => {
    const result = await post<{ full_name: string; html_url: string }>("/github/repositories", {
      name: createRepositoryName.value, description: "",
    });
    form.repository_url = result.html_url;
    const [owner, name] = result.full_name.split("/", 2);
    form.repository_name = name;
    form.author = owner;
    form.repository_description = "";
    createRepositoryName.value = "";
    createRepositoryOpen.value = false;
    publisherLoaded = false;
    await load();
    notice.value = t.value("repositoryCreated");
  });
}
function payload() {
  const customNodes = JSON.parse(form.custom_nodes);
  if (!form.id) form.id = generatedWorkflowId(form.name.trim());
  const version = {
    version: form.version,
    published_at: new Date().toISOString(),
    release_tag: `${form.id}-v${form.version}`,
    changelog: form.changelog,
    comfyui: {
      minimum: status.value?.comfyui_version || null,
      maximum: status.value?.comfyui_version || null,
    },
    package: { url: "https://github.com/pending/package.zip", size: 1, sha256: "0".repeat(64) },
    custom_nodes: customNodes,
  };
  return {
    repository_url: form.repository_url,
    repository: { name: form.repository_name, author: form.author, description: form.repository_description },
    product: {
      id: form.id, name: form.name, category: form.category.trim(), summary: form.summary, description: form.description,
      tags: form.tags.split(",").map((item) => item.trim()).filter(Boolean), archived: false, versions: [version],
    },
    workflow: workflow.value,
    workflow_filename: workflowSourceName.value,
    ...(coverImage.value ? { cover: { filename: coverImage.value.filename, data_base64: coverImage.value.data_base64 } } : {}),
  };
}
const coverImageTypes: Record<string, string> = { "image/png": ".png", "image/webp": ".webp", "image/jpeg": ".jpg" };
const changelogFilePattern = /\.(md|markdown|txt)$/i;
async function importChangelogFile(event: Event, apply: (text: string) => void) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = "";
  if (!file) return;
  if (!changelogFilePattern.test(file.name)) {
    error.value = t.value("changelogFileInvalidType");
    return;
  }
  if (file.size > 1024 * 1024) {
    error.value = t.value("changelogFileTooLarge");
    return;
  }
  try {
    const text = (await file.text()).trim();
    // Backend catalog caps changelog at max_length=20000; longer text would fail validation.
    if (text.length > 20_000) {
      error.value = t.value("changelogFileTooLarge");
      return;
    }
    apply(text);
    error.value = "";
  } catch {
    error.value = t.value("changelogFileReadFailed");
  }
}
function chooseCoverImage(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = "";
  if (!file) return;
  const suffix = coverImageTypes[file.type];
  if (!suffix) {
    error.value = t.value("coverImageInvalidType");
    return;
  }
  if (file.size > 10 * 1024 * 1024) {
    error.value = t.value("coverImageTooLarge");
    return;
  }
  const reader = new FileReader();
  reader.onload = () => {
    const dataUrl = String(reader.result || "");
    const base64 = dataUrl.slice(dataUrl.indexOf(",") + 1);
    if (!base64) {
      error.value = t.value("coverImageReadFailed");
      return;
    }
    error.value = "";
    // The server derives the format from this suffix and stores the file as {tag}-cover{suffix}.
    coverImage.value = { name: file.name, filename: `cover${suffix}`, data_base64: base64, previewUrl: dataUrl, size: file.size };
  };
  reader.onerror = () => {
    error.value = t.value("coverImageReadFailed");
  };
  reader.readAsDataURL(file);
}
function clearCoverImage() {
  coverImage.value = null;
}
function publishDraftFromForm(): PublishDraft {
  return {
    name: form.name.trim(),
    version: form.version.trim(),
    workflowId: form.id || generatedWorkflowId(form.name.trim()),
    repository: `${form.author}/${form.repository_name}`,
  };
}
async function validatePublish() {
  await withBusy("validate", async () => {
    if (!workflow.value) throw new Error(t.value("workflowUnavailable"));
    await post("/publisher/validate", payload());
    notice.value = t.value("validationPassed");
  });
}
async function publishNow() {
  await withBusy("publish", async () => {
    if (!workflow.value) throw new Error(t.value("workflowUnavailable"));
    const request = payload();
    await post("/publisher/validate", request);
    publishDraft.value = publishDraftFromForm();
    const result = await post<{ operation_id: string }>("/publisher/publish", request);
    rememberPublishOperation(result.operation_id);
    notice.value = t.value("publishStarted");
    drawer.value = true;
    try {
      prependOperation(await api<Operation>(`/operations/${encodeURIComponent(result.operation_id)}`));
    } catch {
      // Polling remains the source of truth if the operation detail races its creation.
    }
    await pollOperations();
  });
}
async function resumePending(tag: string) {
  await withBusy("resume", async () => {
    publishDraft.value = null;
    publishStep.value = 3;
    const result = await post<{ operation_id: string }>(`/publisher/pending/${encodeURIComponent(tag)}/resume`, {});
    rememberPublishOperation(result.operation_id);
    notice.value = t.value("publishStarted");
    drawer.value = true;
    try {
      prependOperation(await api<Operation>(`/operations/${encodeURIComponent(result.operation_id)}`));
    } catch {
      // Polling remains the source of truth if the operation detail races its creation.
    }
    await pollOperations();
  });
}
function startAnotherPublication() {
  if (publishOperationRunning.value) return;
  forgetPublishOperation();
  publishDraft.value = null;
  publishCompletion.value = null;
  publishStep.value = 1;
  form.id = "";
  form.category = "";
  form.summary = "";
  form.description = "";
  form.tags = "";
  form.changelog = "";
  coverImage.value = null;
  selectedCatalogProductId.value = "";
  const parsed = parseWorkflowFilename(workflowSourceName.value);
  form.name = parsed.name;
  form.version = parsed.version || "1.0";
  syncSelectedPlugins();
  clearMessages();
  requestCurrentCanvasWorkflow();
}
async function openPublishedManage() {
  const repository = publishCompletionRepository.value;
  if (repository.includes("/")) manageRepositoryUrl.value = `https://github.com/${repository}`;
  tab.value = "manage";
  await enterManage();
}
function manageRepositoryFullName() {
  const match = manageRepositoryUrl.value.match(/github\.com\/([^/]+\/[^/]+)/i);
  return match ? match[1].replace(/\/+$/, "") : "";
}
const manageRepositoryPageUrl = computed(() => {
  const fullName = manageRepositoryFullName();
  return fullName ? `https://github.com/${fullName.split("/").map(encodeURIComponent).join("/")}` : "";
});
function managedVersions(product: ManagedProduct) {
  return [...product.versions].sort((a, b) => {
    const left = normalizeVersion(a.version), right = normalizeVersion(b.version);
    return right[0] - left[0] || right[1] - left[1] || right[2] - left[2];
  });
}
function toggleManageExpanded(id: string) {
  manageExpanded.value = manageExpanded.value.includes(id)
    ? manageExpanded.value.filter((item) => item !== id)
    : [...manageExpanded.value, id];
}
async function loadManaged() {
  const fullName = manageRepositoryFullName();
  if (!fullName) {
    managedProducts.value = [];
    return;
  }
  manageLoading.value = true;
  try {
    const [owner, repo] = fullName.split("/");
    const result = await api<{ items: ManagedProduct[] }>(`/publisher/manage/${owner}/${repo}`);
    managedProducts.value = result.items;
    manageExpanded.value = manageExpanded.value.filter((id) => result.items.some((item) => item.id === id));
  } finally {
    manageLoading.value = false;
  }
}
async function enterManage() {
  if (!status.value?.github.authenticated) return;
  try {
    await loadPublisherWorkspace();
  } catch (reason) {
    error.value = errorMessage(reason);
    return;
  }
  if (!manageRepositoryUrl.value) {
    manageRepositoryUrl.value = form.repository_url || (repositories.value[0] ? publishRepositoryUrl(repositories.value[0]) : "");
  }
  await withBusy("manage", loadManaged);
}
function managedWorkflowPath(productId: string, version?: string) {
  const [owner, repo] = manageRepositoryFullName().split("/");
  if (!owner || !repo) throw new Error(t.value("publisherRepositoryInvalid"));
  const path = `/publisher/workflows/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/${encodeURIComponent(productId)}`;
  return version === undefined ? path : `${path}/versions/${encodeURIComponent(version)}`;
}
async function startPublisherManagementOperation(
  action: string,
  submit: () => Promise<{ operation_id: string }>,
) {
  let started = false;
  await withBusy(`manage-${action}`, async () => {
    const result = await submit();
    publisherManagementOperationIds[result.operation_id] = true;
    publisherManagementOperationSynced[result.operation_id] = false;
    started = true;
    drawer.value = true;
    await pollOperations();
  });
  return started;
}
function managementOperationTarget(operation: Operation) {
  const owner = String(operation.metadata?.owner || "");
  const repo = String(operation.metadata?.repo || "");
  return owner && repo ? `${owner}/${repo}` : "";
}
function catalogOperationTarget(operation: Operation) {
  const repository = typeof operation.result?.repository === "string" ? operation.result.repository : "";
  return repository || managementOperationTarget(operation);
}
async function refreshSubscribedSource(targetFullName: string) {
  const target = targetFullName.toLowerCase();
  if (!target) return;
  const source = sources.value.find((item) => `${item.owner}/${item.repo}`.toLowerCase() === target);
  if (source) await post(`/subscriptions/${source.owner}/${source.repo}/refresh`, {});
}
async function reloadAfterManage(targetFullName = manageRepositoryFullName()) {
  const target = targetFullName.toLowerCase();
  if (target && manageRepositoryFullName().toLowerCase() === target) await loadManaged();
  await refreshSubscribedSource(targetFullName);
  publisherLoaded = false;
  invalidateCatalogCache();
  await load();
}
function openProductEditor(product: ManagedProduct) {
  editForm.name = product.name;
  editForm.category = product.category;
  editForm.summary = product.summary;
  editForm.description = product.description;
  editForm.tags = product.tags.join(", ");
  editingProduct.value = product;
}
async function saveProductEditor() {
  const product = editingProduct.value;
  if (!product) return;
  const started = await startPublisherManagementOperation("edit", () => api<{ operation_id: string }>(managedWorkflowPath(product.id), {
    method: "PATCH",
    body: JSON.stringify({
      name: editForm.name.trim(),
      category: editForm.category.trim(),
      summary: editForm.summary,
      description: editForm.description,
      tags: editForm.tags.split(",").map((item) => item.trim()).filter(Boolean),
    }),
  }));
  if (started) editingProduct.value = null;
}
async function toggleManagedArchive(product: ManagedProduct) {
  const next = !product.archived;
  if (!confirm(t.value(next ? "confirmArchive" : "confirmUnarchive", { name: product.name }))) return;
  await startPublisherManagementOperation(next ? "archive" : "unarchive", () => api<{ operation_id: string }>(managedWorkflowPath(product.id), {
    method: "PATCH", body: JSON.stringify({ archived: next }),
  }));
}
async function deleteManagedWorkflow(product: ManagedProduct) {
  if (!confirm(t.value("confirmDeleteWorkflow", { name: product.name, count: product.versions.length }))) return;
  await startPublisherManagementOperation("delete-workflow", () => remove<{ operation_id: string }>(managedWorkflowPath(product.id), { confirmed: true }));
}
async function deleteManagedVersion(product: ManagedProduct, version: ManagedVersion) {
  if (!confirm(t.value("confirmDeleteVersion", { name: product.name, version: version.version }))) return;
  await startPublisherManagementOperation("delete-version", () => remove<{ operation_id: string }>(managedWorkflowPath(product.id, version.version), { confirmed: true }));
}
function openChangelogEditor(product: ManagedProduct, version: ManagedVersion) {
  editingChangelog.value = { product, version, text: version.changelog };
}
async function saveChangelogEditor() {
  const editing = editingChangelog.value;
  if (!editing) return;
  const started = await startPublisherManagementOperation("changelog", () => api<{ operation_id: string }>(
    managedWorkflowPath(editing.product.id, editing.version.version),
    { method: "PATCH", body: JSON.stringify({ changelog: editing.text }) },
  ));
  if (started) editingChangelog.value = null;
}
function normalizeGitSourceUrl(value: string) {
  return value.trim().replace(/\/+$/, "").replace(/\.git$/, "").toLowerCase();
}
function versionGitDependencies(version: ManagedVersion) {
  return (version.custom_nodes || []).filter((dep) => dep.source_url && dep.commit);
}
function dependencyPinLatest(entry: DependencyPinEntry) {
  return entry.latest;
}
const dependencyPinChanges = computed(() =>
  (dependencyPinEditor.value?.entries || []).filter((entry) => entry.selected && entry.selected !== entry.current)
);
function dependencyPinOptionLabel(option: DependencyCommitOption) {
  const date = option.committed_at ? new Date(option.committed_at).toLocaleDateString() : "";
  return [option.sha.slice(0, 7), date, option.message].filter(Boolean).join(" · ");
}
async function openDependencyPinEditor(product: ManagedProduct, version: ManagedVersion) {
  const gitDependencies = versionGitDependencies(version);
  const entries: DependencyPinEntry[] = gitDependencies.map((dep) => ({
    key: dependencyIdentity(dep),
    name: dep.name,
    source_url: String(dep.source_url),
    current: String(dep.commit),
    selected: String(dep.commit),
    latest: "",
    commits: [],
    error: "",
  }));
  dependencyPinEditor.value = {
    product,
    version,
    entries,
    readonlyCount: (version.custom_nodes || []).length - gitDependencies.length,
    loading: true,
  };
  try {
    const result = await post<{ items: Array<{ source_url: string; commits: DependencyCommitOption[]; error?: string }> }>(
      "/publisher/dependency-commits",
      { sources: gitDependencies.map((dep) => String(dep.source_url)) },
    );
    const editor = dependencyPinEditor.value;
    if (!editor || editor.version !== version) return;
    const remote = new Map(result.items.map((item) => [normalizeGitSourceUrl(item.source_url), item]));
    for (const entry of editor.entries) {
      const item = remote.get(normalizeGitSourceUrl(entry.source_url));
      entry.commits = item?.commits || [];
      entry.latest = entry.commits[0]?.sha || "";
      if (entry.current && !entry.commits.some((option) => option.sha === entry.current)) {
        entry.commits.unshift({ sha: entry.current, message: t.value("dependencyPinCurrent"), committed_at: "", url: "" });
      }
      entry.error = item?.error || (entry.commits.length > 1 ? "" : t.value("dependencyPinNoCommits"));
    }
  } catch (reason) {
    dependencyPinEditor.value = null;
    error.value = errorMessage(reason);
    return;
  }
  if (dependencyPinEditor.value) dependencyPinEditor.value.loading = false;
}
function useLatestDependencyCommit(entry: DependencyPinEntry) {
  const latest = dependencyPinLatest(entry);
  if (latest) entry.selected = latest;
}
function useAllLatestDependencyCommits() {
  for (const entry of dependencyPinEditor.value?.entries || []) useLatestDependencyCommit(entry);
}
async function saveDependencyPinEditor() {
  const editor = dependencyPinEditor.value;
  if (!editor) return;
  const updates = dependencyPinChanges.value.map((entry) => ({ source_url: entry.source_url, commit: entry.selected }));
  if (!updates.length) return;
  const started = await startPublisherManagementOperation("update-dependencies", () => post<{ operation_id: string }>(
    `${managedWorkflowPath(editor.product.id, editor.version.version)}/dependencies`,
    { confirmed: true, updates },
  ));
  if (started) dependencyPinEditor.value = null;
}
async function startLogin() {
  await withBusy("login", async () => {
    window.clearTimeout(loginTimer);
    const started = await post<{ user_code: string; verification_uri: string; interval: number }>("/github/device/start", {});
    device.value = started;
    deviceCodeCopied.value = false;
    tab.value = "publish";
    pollLogin();
  });
}
async function copyDeviceCode() {
  if (!device.value) return;
  try {
    await navigator.clipboard.writeText(device.value.user_code);
  } catch {
    const input = document.createElement("textarea");
    input.value = device.value.user_code;
    input.style.position = "fixed";
    input.style.opacity = "0";
    document.body.appendChild(input);
    input.select();
    document.execCommand("copy");
    input.remove();
  }
  deviceCodeCopied.value = true;
  window.clearTimeout(copiedTimer);
  copiedTimer = window.setTimeout(() => deviceCodeCopied.value = false, 2500);
}
async function pollLogin() {
  const result = await post<{ authenticated?: boolean; pending?: boolean; error?: string }>("/github/device/poll", {});
  if (result.authenticated) {
    device.value = null;
    await load();
    return;
  }
  if (result.pending) {
    loginTimer = window.setTimeout(pollLogin, Math.max(device.value?.interval || 5, 5) * 1000);
    return;
  }
  error.value = result.error || t.value("githubLoginFailed");
}
async function logout() {
  window.clearTimeout(loginTimer);
  device.value = null;
  await post("/github/logout", {});
  await load();
}
onMounted(async () => {
  document.addEventListener("keydown", handleWorkspaceShortcut);
  window.addEventListener("message", handleHubMessage);
  try {
    await load();
    await pollOperations();
    void refreshStartupCatalog();
  } catch (reason) { error.value = errorMessage(reason); }
});
onBeforeUnmount(() => {
  document.removeEventListener("keydown", handleWorkspaceShortcut);
  window.removeEventListener("message", handleHubMessage);
  clearTimeout(operationTimer);
  clearTimeout(loginTimer);
  clearTimeout(copiedTimer);
  managerSocket?.close();
});
</script>

<template>
  <div :class="['app-shell', `theme-${tab}`]">
    <aside class="nav-rail">
      <div class="brand">
        <span class="brand-mark"><LibraryBig :size="19" /></span>
        <span class="brand-copy"><strong>{{ t("title") }}</strong><small>v1.0.1</small></span>
      </div>

      <nav class="primary-nav" :aria-label="t('primaryNavigation')">
        <button :class="{ active: tab === 'subscribe' }" @click="tab = 'subscribe'">
          <Compass :size="18" /><span>{{ t("subscribe") }}</span>
        </button>
        <button :class="{ active: tab === 'publish' }" @click="enterPublish">
          <UploadCloud :size="18" /><span>{{ t("publish") }}</span>
        </button>
        <button :class="{ active: tab === 'manage' }" @click="tab = 'manage'; enterManage()">
          <FolderCog :size="18" /><span>{{ t("manage") }}</span>
        </button>
      </nav>

      <div class="rail-spacer" />
      <div class="rail-actions">
        <button class="rail-action" :title="t('settings')" :aria-label="t('settings')" :disabled="settingsSaving" @click="openSettings">
          <SettingsIcon :size="17" /><span>{{ t("settings") }}</span>
        </button>
        <button class="rail-action" :title="t('activities')" :aria-label="t('activities')" @click="drawer = !drawer">
          <ActivityIcon :size="17" /><span>{{ t("activities") }}</span>
          <i v-if="operations.some(isOperationActive)" class="pulse" />
        </button>
        <button v-if="status?.github.authenticated" class="account-card" :title="t('logout')" :aria-label="t('logout')" @click="logout">
          <img v-if="status.github.user?.avatar_url" :src="status.github.user.avatar_url" alt="" />
          <CircleUserRound v-else :size="18" />
          <span><strong>{{ status.github.user?.login || t("signedIn") }}</strong><small>{{ t("logout") }}</small></span>
          <LogOut :size="15" />
        </button>
        <button v-else class="account-card" :title="t('login')" :aria-label="t('login')"
          :disabled="!status?.github.configured || !!busy" @click="startLogin">
          <GitBranch :size="18" /><span><strong>{{ t("login") }}</strong><small>{{ t("loginPurpose") }}</small></span>
          <ArrowRight :size="15" />
        </button>
        <button class="rail-action" :title="t('close')" :aria-label="t('close')" @click="closeHubPage">
          <X :size="18" />
        </button>
      </div>
    </aside>

    <section class="workspace">
      <main class="workspace-body">
        <div v-if="error" class="message error">
          <AlertCircle :size="18" /><span>{{ error }}</span><button :title="t('close')" :aria-label="t('close')" @click="error = ''"><X :size="17" /></button>
        </div>
        <div v-if="notice" class="message success">
          <CheckCircle2 :size="18" /><span>{{ notice }}</span><button :title="t('close')" :aria-label="t('close')" @click="notice = ''"><X :size="17" /></button>
        </div>
        <div v-if="downloadCompletion" class="message success download-completion">
          <CheckCircle2 :size="18" />
          <span>{{ t("downloadComplete", { name: downloadCompletionName, version: downloadCompletionVersion }) }}</span>
          <div class="message-actions">
            <button class="secondary message-action-button" :disabled="!!busy" @click="revealDownloadCompletion"><FolderOpen :size="15" />{{ t("openWorkflowFolder") }}</button>
            <button class="icon-button" :title="t('close')" :aria-label="t('close')" @click="dismissDownloadCompletion"><X :size="17" /></button>
          </div>
        </div>
        <div v-if="status && !status.git.available && tab === 'publish'" class="message warning">
          <TriangleAlert :size="18" /><span>{{ t("gitUnavailable") }}</span>
        </div>
        <div v-if="status && !status.github.configured && tab === 'publish'" class="message warning">
          <TriangleAlert :size="18" /><span>{{ t("githubNotConfigured") }}</span>
        </div>
        <Transition name="theme-page" mode="out-in">
          <section v-if="tab === 'subscribe'" key="subscribe" class="library-panel tab-page">
            <div class="catalog-toolbar">
              <label class="search-field">
                <SearchIcon :size="18" />
                <input ref="searchInput" v-model="search" :placeholder="t('search')" />
                <kbd>/</kbd>
              </label>
              <div class="toolbar-actions">
                <div class="segmented" role="group" :aria-label="t('workflowFilters')"
                  :style="{ '--filter-index': String(filterIndex) }">
                  <button v-for="item in (['all','downloaded','updates','archived'] as const)" :key="item"
                    :class="{ active: filter === item }" @click="filter = item">{{ t(item) }}</button>
                </div>
                <button class="toolbar-refresh" :disabled="!!busy || catalogRefreshing || !sources.length" :aria-busy="catalogRefreshing" @click="refreshAllSources">
                  <RefreshCw :size="16" :class="{ spinning: busy === 'refresh-all' || catalogRefreshing }" /><span>{{ t("refreshAll") }}</span>
                </button>
                <button class="source-toggle" :disabled="!!busy" :class="{ active: sourceComposerOpen }" @click="sourceComposerOpen ? sourceComposerOpen = false : openSourceComposer()">
                  <FolderGit2 :size="16" /><span>{{ t("sourcesLabel") }}</span><i>{{ sources.length }}</i>
                </button>
              </div>
            </div>

            <div v-if="sourceComposerOpen" class="source-composer">
              <div class="source-form">
                <GitBranch :size="18" />
                <input ref="sourceInput" v-model.trim="sourceUrl" :placeholder="t('sourcePlaceholder')" @keyup.enter="addSource" />
                <button class="primary" :disabled="!sourceUrl || !!busy || catalogRefreshing" @click="addSource">
                  <Plus :size="17" />{{ t("add") }}
                </button>
              </div>
            </div>

            <div v-if="sources.length" class="source-chips source-chips-persistent">
              <div v-for="item in sources" :key="item.url" class="source-chip" :class="{ invalid: item.error }" :title="sourceErrorMessage(item)">
                <AlertCircle v-if="item.error" :size="17" /><FolderGit2 v-else :size="17" />
                <span>{{ item.owner }}/{{ item.repo }}</span>
                <button :title="t('refresh')" :aria-label="t('refresh')" :disabled="!!busy || catalogRefreshing" @click="refreshSource(item)"><RefreshCw :size="15" /></button>
                <button :title="t('remove')" :aria-label="t('remove')" :disabled="!!busy || catalogRefreshing" @click="removeSource(item)"><Trash2 :size="15" /></button>
                <a class="source-chip-action" :href="item.url" target="_blank" rel="noopener"
                  :title="t('openSource')" :aria-label="`${t('openSource')}: ${item.owner}/${item.repo}`" @click.stop>
                  <ExternalLink :size="15" />
                </a>
              </div>
            </div>

            <div v-if="loading" class="empty-state loading-state"><LoaderCircle :size="32" class="dependency-task-spin" /><p>{{ t("loading") }}</p></div>
            <div v-else-if="visibleProducts.length" class="catalog">
              <article v-for="item in visibleProducts" :key="`${item.source.owner}/${item.source.repo}/${item.id}`"
                class="workflow-card" tabindex="0" @click="openDetails(item)" @keyup.enter="openDetails(item)">
                <div class="preview-wrap">
                  <img v-if="productCover(item)" class="card-preview" :src="productCover(item)?.url" :alt="item.name" loading="lazy" />
                  <div v-else class="preview-placeholder"><LibraryBig :size="28" /></div>
                  <span class="version-pill">v{{ latest(item)?.version }}</span>
                </div>
                <div class="card-body">
                  <div class="card-heading"><h2>{{ item.name }}</h2><ArrowRight :size="17" /></div>
                  <p>{{ item.summary }}</p>
                  <div class="tags"><span v-if="item.category" class="category-tag"><FolderOpen :size="11" />{{ item.category }}</span><span v-if="item.archived" class="archived-tag">{{ t("archived") }}</span><span v-for="tag in item.tags" :key="tag">{{ tag }}</span></div>
                  <footer>
                    <a class="source-origin" :href="productRepositoryUrl(item)" target="_blank" rel="noopener"
                      :title="t('repositoryPage')" :aria-label="`${t('repositoryPage')}: ${item.source.owner}/${item.source.repo}`"
                      @click.stop @keyup.enter.stop>
                      <GitBranch :size="13" />{{ item.source.owner }}/{{ item.source.repo }}<ExternalLink :size="11" />
                    </a>
                    <span v-if="item.downloaded_versions.length" class="downloaded"><Check :size="13" />{{ t("downloadedTag") }}</span>
                  </footer>
                </div>
              </article>
            </div>

            <div v-else class="empty-state">
              <span class="empty-orbit"><PackageOpen :size="32" /></span>
              <h2>{{ t("emptyTitle") }}</h2>
              <p>{{ search || filter !== "all" ? t("emptyFiltered") : t("noWorkflows") }}</p>
              <button v-if="!search && filter === 'all'" class="secondary" @click="openSourceComposer">
                <Plus :size="17" />{{ t("addSource") }}
              </button>
            </div>
          </section>

          <div v-else key="publish" class="publish-flow tab-page">
            <div v-if="!status?.github.authenticated" class="publish-auth-gate">
              <span class="auth-gate-icon"><GitBranch :size="28" /></span>
              <div v-if="device" class="device-auth-flow">
                <span class="eyebrow">{{ t("waitingGithubAuthorization") }}</span>
                <h1>{{ t("completeSignInTwoSteps") }}</h1>
                <p>{{ t("deviceFlowHint") }}</p>
                <ol class="device-steps">
                  <li>
                    <span>1</span>
                    <div><small>{{ t("copyVerificationCode") }}</small>
                      <button class="device-code" :aria-label="t('copyVerificationCode')" @click="copyDeviceCode">
                        <code>{{ device.user_code }}</code>
                        <span><Check v-if="deviceCodeCopied" :size="17" /><Copy v-else :size="17" />{{ deviceCodeCopied ? t("copied") : t("copy") }}</span>
                      </button>
                    </div>
                  </li>
                  <li>
                    <span>2</span>
                    <div><small>{{ t("openGithubAndPasteCode") }}</small>
                      <a class="primary device-open-link" :href="device.verification_uri" target="_blank" rel="noopener">
                        {{ t("openGithubAuthorization") }}<ExternalLink :size="16" />
                      </a>
                    </div>
                  </li>
                </ol>
                <span class="device-waiting"><i />{{ t("waitingAuthorization") }}</span>
              </div>
              <div v-else>
                <span class="eyebrow">{{ t("githubAuthorization") }}</span>
                <h1>{{ tab === 'manage' ? t("signInToManage") : t("signInToPublish") }}</h1>
                <p>{{ status?.github.configured
                  ? (tab === 'manage' ? t("signInManageHint") : t("signInPublishHint"))
                  : t("githubNotConfigured") }}</p>
              </div>
              <button v-if="!device" class="primary auth-gate-action" :disabled="!status?.github.configured || !!busy" @click="startLogin">
                <GitBranch :size="17" />{{ t("login") }}<ArrowRight :size="16" />
              </button>
            </div>

            <div v-else-if="publisherLoading" class="empty-state loading-state"><LoaderCircle :size="32" class="dependency-task-spin" /><p>{{ t("loading") }}</p></div>

            <template v-else>
              <template v-if="tab === 'publish'">
              <div v-if="pendingPublications.length" class="publish-utilities">
                <details v-if="pendingPublications.length"><summary>{{ t("pendingPublications") }}</summary>
                  <button v-for="item in pendingPublications" :key="item.tag" class="ghost" @click="resumePending(item.tag)">{{ item.tag }}</button>
                </details>
              </div>

              <section class="panel publish-console-shell" :class="{ complete: publishStep === 4 }" :aria-busy="publishOperationRunning">
                <header class="publish-context-bar" :class="{ unavailable: !workflow, complete: publishStep === 4 }">
                  <span class="upload-icon"><FileJson :size="20" /></span>
                  <span class="current-workflow-copy">
                    <small>{{ publishStep === 4 ? t("publishCompleteEyebrow") : t("publishing") }}</small>
                    <strong>{{ publishStep === 4 ? publishCompletionName : (workflowSourceName || t("readingCanvas")) }}</strong>
                    <em v-if="canvasWorkflowError">{{ canvasWorkflowError }}</em>
                  </span>
                  <nav class="publish-steps" :aria-label="t('publishSteps')">
                    <button
                      v-for="(label, index) in publishStepLabels"
                      :key="index"
                      :class="{ active: publishStep === index + 1, done: publishStep > index + 1 }"
                      :disabled="publishStep === 4 || publishStep <= index + 1"
                      @click="moveToPublishStep((index + 1) as PublishStep)"
                    >
                      <i>{{ index + 1 }}</i><span>{{ label }}</span>
                    </button>
                  </nav>
                  <div class="publish-context-stats">
                    <span><PackageOpen :size="14" />{{ customNodeCount }}</span>
                    <span><FileUp :size="14" />{{ imageReferences.length }}</span>
                    <span><TriangleAlert :size="14" />{{ loraReferences.length }}</span>
                  </div>
                </header>

                <div class="publish-stage-body">
                  <fieldset class="publish-stage-fieldset" :disabled="publishOperationRunning">
                    <section v-if="publishStep === 1" class="publish-stage resource-review-stage">
                    <div class="core-version-row">
                      <span><ActivityIcon :size="16" /></span>
                      <div><small>{{ t("comfyCoreVersion") }}</small><strong>{{ status?.comfyui_version || t("detecting") }}</strong></div>
                      <CheckCircle2 v-if="status?.comfyui_version" :size="17" />
                    </div>
                    <div v-if="resourceScanPending" class="resource-scan-pending"><RefreshCw :size="17" />{{ t("scanningCanvasResources") }}</div>

                    <div class="resource-review-group">
                      <div class="resource-review-heading"><span><PackageOpen :size="16" /><strong>{{ t("requiredPlugins") }}</strong><em>{{ customNodeCount }}</em></span><small>{{ dependencyScanError || t("gitPluginSelectionHint") }}</small></div>
                      <div v-if="!resourceScanPending && !dependencyScanError" class="plugin-selection-hint">
                        <TriangleAlert :size="17" />
                        <span><strong>{{ t("pluginSelectionTitle") }}</strong><small>{{ t("pluginSelectionDescription") }}</small></span>
                      </div>
                      <label
                        v-for="item in scannedPluginDependencies"
                        :key="pluginKey(item)"
                        class="publish-resource-row selectable with-checkbox"
                        :class="{ selected: selectedPluginKeys.includes(pluginKey(item)) }"
                      >
                        <input
                          type="checkbox"
                          :checked="selectedPluginKeys.includes(pluginKey(item))"
                          @change="togglePlugin(item, ($event.target as HTMLInputElement).checked)"
                        />
                        <span class="resource-row-icon"><PackageOpen :size="15" /></span>
                        <span><strong>{{ item.name }}</strong><small :title="pluginSourceLabel(item)">{{ pluginSourceLabel(item) }}</small></span>
                        <em><b class="dependency-installer-badge" :data-installer="item.installer">{{ item.installer === "manager" ? t("installerManager") : t("installerGit") }}</b> {{ pluginVersionLabel(item) }}<a
                          v-if="dependencySourceUrl(item)"
                          class="dependency-source-link"
                          :href="dependencySourceUrl(item)"
                          target="_blank"
                          rel="noopener noreferrer"
                          :title="t('openPluginSource')"
                          :aria-label="`${t('openPluginSource')}: ${item.name}`"
                          @click.stop
                        ><ExternalLink :size="14" /></a></em>
                      </label>
                      <div v-if="!resourceScanPending && !dependencyScanError && !scannedPluginDependencies.length" class="publish-resource-empty"><CheckCircle2 :size="18" /><span><strong>{{ t("noExtraPlugins") }}</strong><small>{{ t("environmentReady") }}</small></span></div>
                    </div>

                    <div class="resource-review-group">
                      <div class="resource-review-heading"><span><FileUp :size="16" /><strong>{{ t("imageReferences") }}</strong><em>{{ imageReferences.length }}</em></span><small>{{ t("imageReferenceHint") }}</small></div>
                      <div v-for="item in imageReferences" :key="item.name" class="publish-resource-row" :class="{ invalid: item.status !== 'ready' }">
                        <span class="resource-row-icon"><FileUp :size="15" /></span>
                        <span><strong>{{ item.name }}</strong><small>{{ t("referenceCount", { count: item.node_ids.length }) }}</small></span>
                        <em>{{ item.status === "ready" && item.size != null ? humanBytes(item.size) : item.status }}</em>
                      </div>
                      <div v-if="!resourceScanPending && !imageReferences.length" class="publish-resource-empty"><CheckCircle2 :size="18" /><span><strong>{{ t("noImageReferences") }}</strong><small>{{ t("noBundledImagesHint") }}</small></span></div>
                    </div>

                    <div class="resource-review-group">
                      <div class="resource-review-heading">
                        <span><TriangleAlert :size="16" /><strong>{{ t("loraReferences") }}</strong><em>{{ loraReferences.length }}</em></span>
                      </div>
                      <div v-if="loraReferences.length" class="plugin-selection-hint lora-reference-warning">
                        <TriangleAlert :size="17" />
                        <span><strong>{{ t("loraReferenceWarning", { count: loraReferences.length }) }}</strong><small>{{ t("loraReferenceWarningDescription") }}</small></span>
                      </div>
                      <div v-if="!resourceScanPending && !loraReferences.length" class="publish-resource-empty"><CheckCircle2 :size="18" /><span><strong>{{ t("noLoraReferences") }}</strong><small>{{ t("nothingElseToReview") }}</small></span></div>
                    </div>

                  </section>

                  <section v-else-if="publishStep === 2" class="publish-stage release-details-stage">
                    <div class="publish-form-section">
                      <div class="publish-section-title">
                        <span><GitBranch :size="16" /></span>
                        <div><strong>{{ t("destination") }}</strong><small>{{ t("repositoryRemembered") }}</small></div>
                      </div>
                      <div class="repository-row">
                        <label class="compact-field repository-select">
                          <span class="select-control">
                            <select v-model="form.repository_url" :disabled="!repositories.length" @change="applySelectedRepository">
                              <option v-if="!repositories.length" value="">{{ t("noAuthorizedRepositories") }}</option>
                              <option v-for="repo in repositories" :key="repo.full_name" :value="publishRepositoryUrl(repo)">{{ repo.full_name }}</option>
                            </select>
                            <span class="select-chevron" aria-hidden="true"><ChevronDown :size="15" :stroke-width="2.4" /></span>
                          </span>
                        </label>
                        <button class="secondary repository-new" @click="createRepositoryOpen = !createRepositoryOpen"><Plus :size="15" />{{ t("newRepository") }}</button>
                      </div>
                      <div v-if="createRepositoryOpen" class="inline create-repo">
                        <input v-model="createRepositoryName" :placeholder="t('repositoryNamePlaceholder')" @keyup.enter="createRepository" />
                        <button class="secondary" :disabled="!createRepositoryName" @click="createRepository"><Plus :size="16" />{{ t("create") }}</button>
                      </div>
                    </div>

                    <div class="publish-form-section release-field-list">
                      <div class="publish-section-title">
                        <span><FileJson :size="16" /></span>
                        <div><strong>{{ t("releaseInformation") }}</strong><small>{{ t("completeFieldsInOrder") }}</small></div>
                      </div>
                      <div class="field-grid">
                        <label class="compact-field"><span>{{ t("category") }}</span>
                          <input v-model="form.category" list="workflow-category-options" maxlength="80" required :placeholder="t('categoryPlaceholder')" @input="syncCatalogProductByName" />
                          <datalist id="workflow-category-options"><option v-for="category in repositoryCategories" :key="category" :value="category" /></datalist>
                        </label>
                        <label class="compact-field"><span>{{ t("name") }}</span>
                          <input v-model="form.name" list="workflow-name-options" maxlength="80" @input="syncCatalogProductByName" />
                          <datalist id="workflow-name-options"><option v-for="item in publishCatalogProducts" :key="item.id" :value="item.name" /></datalist>
                        </label>
                        <label class="compact-field"><span>{{ t("version") }}</span><input v-model="form.version" placeholder="1.0" /></label>
                        <div class="compact-field publish-id-preview"><span>{{ t("publishId") }}<em>{{ t("automatic") }}</em></span>
                          <strong>{{ form.id || generatedWorkflowId(form.name || t("unnamedWorkflow")) }}</strong>
                        </div>
                        <p v-if="selectedCatalogProduct" class="field-note span-2">{{ t("publishedVersions", { versions: selectedCatalogProduct.versions.join(t("listSeparator")) || t("none") }) }}</p>
                        <p v-if="existingVersionConflict" class="message warning span-2"><TriangleAlert :size="16" /><span>{{ t("versionAlreadyPublished") }}</span></p>
                        <label class="compact-field release-notes-field span-2"><span>{{ t("releaseNotes") }}<button class="ghost compact-action" type="button" @click.stop.prevent="publishChangelogFileInput?.click()"><FileUp :size="14" />{{ t("importChangelogFromFile") }}</button></span><textarea v-model="form.changelog" rows="4" /></label>
                        <input ref="publishChangelogFileInput" type="file" accept=".md,.markdown,.txt" hidden @change="importChangelogFile($event, (text) => { form.changelog = text; })" />
                        <div class="compact-field cover-field span-2">
                        <span>{{ t("coverImage") }}<em>{{ t("optional") }}</em></span>
                        <div v-if="coverImage" class="cover-selected">
                          <img :src="coverImage.previewUrl" :alt="t('coverImage')" />
                          <span><strong>{{ coverImage.name }}</strong><small>{{ humanBytes(coverImage.size) }}</small></span>
                          <button class="ghost compact-action" type="button" :disabled="!!busy" @click="clearCoverImage"><Trash2 :size="14" />{{ t("remove") }}</button>
                        </div>
                        <label v-else class="cover-picker">
                          <ImagePlus :size="16" />{{ t("chooseCoverImage") }}
                          <input type="file" accept="image/png,image/webp,image/jpeg" @change="chooseCoverImage" />
                        </label>
                        <small class="field-note cover-note">{{ t("coverImageHint") }}</small>
                        </div>
                      </div>
                    </div>
                  </section>

                    <section v-else-if="publishStep === 3" class="publish-stage publish-review-stage">
                    <div class="publish-review-summary">
                      <div><small>{{ t("repositoryLabel") }}</small><span><strong>{{ form.author && form.repository_name ? `${form.author}/${form.repository_name}` : "—" }}</strong></span></div>
                      <div><small>{{ t("workflowLabel") }}</small><span><strong>{{ form.name || "—" }}</strong><em>{{ form.category || "—" }}</em></span></div>
                      <div><small>{{ t("releaseVersion") }}</small><span><strong>v{{ form.version || "—" }}</strong><em>{{ form.id || generatedWorkflowId(form.name || "workflow") }}</em></span></div>
                      <div><small>{{ t("coverImage") }}</small>
                        <span v-if="coverImage"><img class="review-cover-thumb" :src="coverImage.previewUrl" :alt="t('coverImage')" /><em>{{ coverImage.name }}</em></span>
                        <span v-else><strong>—</strong></span>
                      </div>
                    </div>
                    <div class="publish-review-resources">
                      <span><ActivityIcon :size="16" /><strong>{{ status?.comfyui_version || "—" }}</strong><small>{{ t("comfyCore") }}</small></span>
                      <span><PackageOpen :size="16" /><strong>{{ customNodeCount }}</strong><small>{{ t("plugins") }}</small></span>
                      <span><FileUp :size="16" /><strong>{{ imageReferences.length }}</strong><small>{{ t("images") }}</small></span>
                    </div>
                    <div class="publish-review-notes"><small>{{ t("releaseNotes") }}</small><p>{{ form.changelog }}</p></div>
                    <p class="publish-final-warning"><AlertCircle :size="16" />{{ t("immutableReleaseWarning") }}</p>
                  </section>

                  <section v-else class="publish-stage publish-complete-stage">
                    <div class="publish-complete-hero">
                      <span class="publish-complete-icon"><CheckCircle2 :size="34" /></span>
                      <span class="eyebrow">{{ t("publishCompleteEyebrow") }}</span>
                      <h1>{{ t("publishCompleteTitle") }}</h1>
                      <p>{{ t("publishCompleteDescription", { name: publishCompletionName, version: publishCompletionVersion }) }}</p>
                    </div>
                    <div class="publish-complete-summary">
                      <div><small>{{ t("publishCompleteRepository") }}</small><span><strong>{{ publishCompletionRepository }}</strong></span></div>
                      <div><small>{{ t("workflowLabel") }}</small><span><strong>{{ publishCompletionName }}</strong><em>{{ publishCompletionWorkflowId }}</em></span></div>
                      <div><small>{{ t("releaseVersion") }}</small><span><strong>v{{ publishCompletionVersion }}</strong></span></div>
                      <div><small>{{ t("publishCompletePath") }}</small><span><strong>{{ publishCompletionRepositoryPath }}</strong></span></div>
                      <div><small>{{ t("publishCompleteRelease") }}</small>
                        <span v-if="publishCompletionReleaseUrl"><a class="publish-complete-link" :href="publishCompletionReleaseUrl" target="_blank" rel="noopener noreferrer">{{ t("openRelease") }}<ExternalLink :size="14" /></a></span>
                        <span v-else><strong>{{ t("none") }}</strong></span>
                      </div>
                      <div><small>{{ t("publishCompleteTime") }}</small><span><strong>{{ publishCompletionTime }}</strong></span></div>
                    </div>
                    <div class="publish-complete-catalog-note"><CheckCircle2 :size="17" />{{ t("publishCompleteCatalogHint") }}</div>
                    <div class="publish-complete-actions">
                      <a v-if="publishCompletionReleaseUrl" class="secondary" :href="publishCompletionReleaseUrl" target="_blank" rel="noopener noreferrer"><ExternalLink :size="16" />{{ t("openRelease") }}</a>
                      <button class="ghost" @click="drawer = true"><ActivityIcon :size="16" />{{ t("viewActivity") }}</button>
                      <button class="secondary" @click="openPublishedManage"><FolderCog :size="16" />{{ t("goToManage") }}</button>
                      <button class="primary" @click="startAnotherPublication"><UploadCloud :size="16" />{{ t("publishAnother") }}</button>
                    </div>
                  </section>
                  </fieldset>
                </div>

                <footer class="publish-action-bar staged-actions">
                  <span v-if="publishOperationRunning"><LoaderCircle :size="16" class="dependency-task-spin" />{{ t("publishInProgress") }}</span>
                  <span v-else-if="publishStep === 1"><CheckCircle2 v-if="canConfirmPublishResources" :size="16" /><AlertCircle v-else :size="16" />{{ canConfirmPublishResources
                    ? t("resourcesReady")
                    : (canvasWorkflowError || dependencyScanError || (resourceScanPending ? t("scanningResources") : t("resourceReviewFailed"))) }}</span>
                  <span v-else-if="publishStep === 2"><CheckCircle2 v-if="canFinalizePublish" :size="16" /><AlertCircle v-else :size="16" />{{ canFinalizePublish ? t("releaseDetailsComplete") : t("completeReleaseFields") }}</span>
                  <span v-else-if="publishStep === 3"><ShieldCheck :size="16" />{{ t("publishReviewReady") }}</span>
                  <span v-else><CheckCircle2 :size="16" />{{ t("publishCompleteFooter") }}</span>

                  <button v-if="publishStep > 1 && publishStep < 4" class="ghost" :disabled="!!busy || publishOperationRunning" @click="moveToPublishStep((publishStep - 1) as 1 | 2 | 3)"><ArrowLeft :size="15" />{{ t("back") }}</button>
                  <button v-if="publishStep === 1" class="primary" :disabled="!!busy || publishOperationRunning || !canConfirmPublishResources" @click="moveToPublishStep(2)">{{ t("confirmResourcesNext") }}<ArrowRight :size="16" /></button>
                  <button v-else-if="publishStep === 2" class="primary" :disabled="!!busy || publishOperationRunning || !canFinalizePublish" @click="moveToPublishStep(3)">{{ t("confirmDetailsNext") }}<ArrowRight :size="16" /></button>
                  <template v-else-if="publishStep === 3">
                    <button class="secondary" :disabled="!!busy || publishOperationRunning || !canFinalizePublish" @click="validatePublish"><ShieldCheck :size="16" />{{ t("validate") }}</button>
                    <button class="primary" :disabled="!!busy || publishOperationRunning || !canFinalizePublish || !status?.github.authenticated" @click="publishNow"><UploadCloud :size="16" />{{ t("publishNow") }}</button>
                  </template>
                </footer>
              </section>
              </template>

              <section v-else class="manage-shell">
                <header class="manage-toolbar">
                  <label class="compact-field manage-repository">
                    <span class="select-control">
                      <select v-model="manageRepositoryUrl" :disabled="!repositories.length || manageLoading || publisherManagementOperationRunning" @change="withBusy('manage', loadManaged)">
                        <option v-if="!repositories.length" value="">{{ t("noAuthorizedRepositories") }}</option>
                        <option v-for="repo in repositories" :key="repo.full_name" :value="publishRepositoryUrl(repo)">{{ repo.full_name }}</option>
                      </select>
                      <span class="select-chevron" aria-hidden="true"><ChevronDown :size="15" :stroke-width="2.4" /></span>
                    </span>
                  </label>
                  <a
                    class="secondary compact-action manage-repository-link"
                    :href="manageRepositoryPageUrl || undefined"
                    target="_blank"
                    rel="noopener noreferrer"
                    :aria-disabled="!manageRepositoryPageUrl"
                    :aria-label="manageRepositoryPageUrl ? `${t('repositoryPage')}: ${manageRepositoryFullName()}` : t('repositoryPage')"
                    :title="t('repositoryPage')"
                  >
                    <ExternalLink :size="14" />{{ t("repositoryPage") }}
                  </a>
                  <button class="ghost compact-action" :disabled="!!busy || manageLoading || publisherManagementOperationRunning" @click="withBusy('manage', loadManaged)"><RefreshCw :size="15" />{{ t("refreshManaged") }}</button>
                </header>
                <p class="manage-hint">{{ t("manageHint") }}</p>

                <div v-if="manageLoading" class="empty small"><RefreshCw :size="20" class="spinning" /><span>{{ t("manageLoading") }}</span></div>
                <div v-else-if="!managedProducts.length" class="empty small"><FolderCog :size="22" /><span>{{ t("noManagedProducts") }}</span></div>
                <ul v-else class="manage-list">
                  <li v-for="product in managedProducts" :key="product.id" class="manage-item" :class="{ archived: product.archived }">
                    <div class="manage-item-main">
                      <button class="manage-item-head" @click="toggleManageExpanded(product.id)">
                        <span class="manage-cover"><img v-if="product.cover" :src="product.cover.url" :alt="product.name" /><LibraryBig v-else :size="18" /></span>
                        <span class="manage-identity">
                          <strong>{{ product.name }}<em v-if="product.archived" class="archived-tag">{{ t("archived") }}</em></strong>
                          <small>{{ product.category }} · {{ product.versions.length }} {{ t("versions") }}</small>
                        </span>
                        <ChevronDown :size="16" class="manage-chevron" :class="{ expanded: manageExpanded.includes(product.id) }" />
                      </button>
                      <div class="manage-item-actions">
                        <button class="secondary compact-action" :disabled="!!busy || publisherManagementOperationRunning" @click="openProductEditor(product)">{{ t("edit") }}</button>
                        <button class="ghost compact-action" :disabled="!!busy || publisherManagementOperationRunning" @click="toggleManagedArchive(product)"><ArchiveIcon :size="14" />{{ product.archived ? t("unarchive") : t("archive") }}</button>
                        <button class="ghost compact-action danger-action" :disabled="!!busy || publisherManagementOperationRunning" @click="deleteManagedWorkflow(product)"><Trash2 :size="14" />{{ t("deleteWorkflow") }}</button>
                      </div>
                    </div>
                    <div v-if="manageExpanded.includes(product.id)" class="manage-versions">
                      <div v-for="version in managedVersions(product)" :key="version.version" class="manage-version-row">
                        <span class="manage-version-meta"><strong>v{{ version.version }}</strong><small>{{ new Date(version.published_at).toLocaleDateString() }} · {{ humanBytes(version.package.size) }}</small></span>
                        <p>{{ version.changelog }}</p>
                        <span class="manage-version-actions">
                          <button class="ghost compact-action" :disabled="!!busy || publisherManagementOperationRunning" @click="openChangelogEditor(product, version)"><SquarePen :size="13" />{{ t("editChangelog") }}</button>
                          <button v-if="versionGitDependencies(version).length" class="ghost compact-action" :disabled="!!busy || publisherManagementOperationRunning" @click="openDependencyPinEditor(product, version)"><FolderGit2 :size="13" />{{ t("updateDependencies") }}</button>
                          <button class="ghost compact-action danger-action" :disabled="!!busy || publisherManagementOperationRunning" @click="deleteManagedVersion(product, version)"><Trash2 :size="13" />{{ t("deleteVersion") }}</button>
                        </span>
                      </div>
                    </div>
                  </li>
                </ul>
              </section>
            </template>
          </div>
        </Transition>
      </main>
    </section>

    <div v-if="selected" class="backdrop" @click.self="closeDetails">
      <aside class="detail">
        <button class="icon-button close" :title="t('close')" :aria-label="t('close')" @click="closeDetails"><X :size="18" /></button>
        <header class="detail-hero">
          <div v-if="productCover(selected)" class="detail-cover">
            <img :src="productCover(selected)?.url" :alt="selected.name" />
          </div>
          <div v-else class="detail-cover detail-cover-placeholder"><LibraryBig :size="30" /></div>
          <div class="detail-identity">
            <a class="eyebrow repository-link" :href="productRepositoryUrl(selected)" target="_blank" rel="noopener"
              :title="t('repositoryPage')">
              <GitBranch :size="13" />{{ selected.source.owner }}/{{ selected.source.repo }}<ExternalLink :size="11" />
            </a>
            <h1>{{ selected.name }}</h1>
            <p>{{ selected.summary || selected.description || t("noWorkflowDescription") }}</p>
            <div class="tags"><span v-if="selected.category" class="category-tag"><FolderOpen :size="11" />{{ selected.category }}</span><span v-for="tag in selected.tags" :key="tag">{{ tag }}</span></div>
          </div>
        </header>

        <div class="detail-workbench">
          <nav class="version-rail" :aria-label="t('versions')">
            <div class="version-rail-heading"><span>{{ t("versions") }}</span><em>{{ selected.versions.length }}</em></div>
            <button v-for="version in detailVersions" :key="version.version"
              :class="{ active: activeDetailVersion?.version === version.version }"
              :aria-current="activeDetailVersion?.version === version.version ? 'true' : undefined"
              @click="selectDetailVersion(version.version)">
              <span><strong>v{{ version.version }}</strong><small>{{ new Date(version.published_at).toLocaleDateString() }}</small></span>
              <CheckCircle2 v-if="selected.downloaded_versions.includes(version.version)" :size="15" />
            </button>
          </nav>

          <div ref="detailReleaseScroll" class="detail-release-scroll">
            <article v-if="activeDetailVersion" class="release release-focused">
              <div class="release-overview">
                <div class="release-version-summary">
                  <span class="eyebrow">{{ t("selectedVersion") }}</span>
                  <div class="release-head"><strong>v{{ activeDetailVersion.version }}</strong><span>{{ humanBytes(activeDetailVersion.package.size) }}</span></div>
                  <p class="compatibility">{{ comfyuiCompatibilityLabel(activeDetailVersion) }}</p>
                </div>
                <div class="resource-status-toolbar" role="group" :aria-label="t('resourceStatusSummary')">
                  <button
                    class="resource-status-chip"
                    :data-tone="activeCoreCheck.tone"
                    :title="t(activeCoreCheck.detail, activeCoreCheck.params)"
                    :aria-label="t('resourceStatusAria', { resource: t('comfyCoreVersion'), status: t(activeCoreCheck.label, activeCoreCheck.params) })"
                    @click="openResourceDialog('core')"
                  >
                    <CheckCircle2 v-if="activeCoreCheck.state === 'aligned'" :size="17" />
                    <TriangleAlert v-else-if="activeCoreCheck.state === 'mismatch'" :size="17" />
                    <Clock v-else :size="17" />
                    <span><small>{{ t("comfyCoreVersion") }}</small><strong>{{ t(activeCoreCheck.label, activeCoreCheck.params) }}</strong></span>
                  </button>
                  <button
                    class="resource-status-chip"
                    :data-tone="activePluginCheck.tone"
                    :title="t(activePluginCheck.detail, activePluginCheck.params)"
                    :aria-label="t('resourceStatusAria', { resource: t('requiredPlugins'), status: t(activePluginCheck.label, activePluginCheck.params) })"
                    @click="openResourceDialog('plugins')"
                  >
                    <CheckCircle2 v-if="activePluginCheck.state === 'aligned'" :size="17" />
                    <CircleX v-else-if="activePluginCheck.state === 'missing'" :size="17" />
                    <TriangleAlert v-else-if="activePluginCheck.state === 'mismatch'" :size="17" />
                    <LoaderCircle v-else-if="activePluginCheck.state === 'checking'" :size="17" class="dependency-task-spin" />
                    <Clock v-else :size="17" />
                    <span><small>{{ t("requiredPlugins") }}</small><strong>{{ t(activePluginCheck.label, activePluginCheck.params) }}</strong></span>
                  </button>
                  <button
                    class="resource-status-chip"
                    :data-tone="activeImageCount ? 'ok' : 'muted'"
                    :title="t(activeImageCount ? 'includedImagesDetail' : 'noBundledImagesDetail', { count: activeImageCount })"
                    :aria-label="t('resourceStatusAria', { resource: t('includedImages'), status: t('includedImageCount', { count: activeImageCount }) })"
                    @click="openResourceDialog('images')"
                  >
                    <FileUp :size="17" />
                    <span><small>{{ t("includedImages") }}</small><strong>{{ t("includedImageCount", { count: activeImageCount }) }}</strong></span>
                  </button>
                </div>
              </div>

              <div class="version-actions" :class="{ 'downloaded-actions': selected.downloaded_versions.includes(activeDetailVersion.version) }">
                <button v-if="!selected.downloaded_versions.includes(activeDetailVersion.version)" class="primary wide" :disabled="!!busy || isVersionDownloading(selected, activeDetailVersion)" @click="download(selected, activeDetailVersion)"><LoaderCircle v-if="busy === 'download-check' || busy === 'download' || isVersionDownloading(selected, activeDetailVersion)" :size="17" class="dependency-task-spin" /><DownloadIcon v-else :size="17" />{{ busy === "download-check" ? t("checkingDownload") : busy === "download" || isVersionDownloading(selected, activeDetailVersion) ? t("downloading") : t("download") }}</button>
                <template v-else>
                  <button class="primary wide" :disabled="!!busy" @click="loadLocalVersion(selected, activeDetailVersion)"><FileJson :size="17" />{{ t("loadToCanvas") }}</button>
                  <button class="secondary wide" :disabled="!!busy" @click="revealLocalVersion(selected, activeDetailVersion)"><FolderOpen :size="17" />{{ t("revealLocal") }}</button>
                  <button class="ghost wide danger-action" :disabled="!!busy" @click="deleteLocalVersion(selected, activeDetailVersion)"><Trash2 :size="16" />{{ t("deleteLocal") }}</button>
                </template>
              </div>

              <section class="release-note">
                <span>{{ t("changelog") }}</span>
                <div class="changelog markdown-body" v-html="renderedActiveChangelog"></div>
              </section>

              <details v-if="otherModelAssets(activeDetailVersion).length" class="model-assets"><summary>{{ t("models") }} ({{ otherModelAssets(activeDetailVersion).length }})</summary>
                <div v-for="model in otherModelAssets(activeDetailVersion)" :key="`${model.type}:${model.filename}`" class="model-asset">
                  <span><strong>{{ model.name }}</strong><small>{{ model.type }} · {{ model.filename }}</small></span>
                  <a :href="model.source_url" target="_blank" rel="noopener"><ExternalLink :size="14" /></a>
                </div>
              </details>
            </article>
          </div>
        </div>
      </aside>
    </div>

    <div v-if="selected && activeDetailVersion && resourceDialog" class="backdrop resource-detail-backdrop" @click.self="closeResourceDialog">
      <section v-if="resourceDialog === 'core'" class="resource-detail-dialog" role="dialog" aria-modal="true" :aria-label="t('comfyCoreVersion')">
        <header class="resource-dialog-head">
          <div class="resource-dialog-title">
            <span class="section-icon"><ActivityIcon :size="19" /></span>
            <div>
              <h2>{{ t("comfyCoreVersion") }}</h2>
              <p>{{ t(activeCoreCheck.label, activeCoreCheck.params) }}</p>
            </div>
          </div>
          <button class="icon-button" :title="t('close')" :aria-label="t('close')" @click="closeResourceDialog"><X :size="18" /></button>
        </header>
        <div class="resource-dialog-content">
          <div class="core-version-summary resource-dialog-core-summary" :data-state="activeCoreCheck.state">
            <div class="core-version-value">
              <small>{{ t("coreVersionCurrent") }}</small>
              <strong>{{ status?.comfyui_version || t("detecting") }}</strong>
            </div>
            <ArrowRight :size="16" class="core-version-arrow" />
            <div class="core-version-value">
              <small>{{ t("coreVersionRequired") }}</small>
              <strong>{{ comfyuiCompatibilityLabel(activeDetailVersion) }}</strong>
            </div>
          </div>
          <div class="dependency-inline-state core-version-state" :data-tone="activeCoreCheck.tone">
            <CheckCircle2 v-if="activeCoreCheck.state === 'aligned'" :size="15" />
            <TriangleAlert v-else-if="activeCoreCheck.state === 'mismatch'" :size="15" />
            <Clock v-else :size="15" />
            <span>{{ t(activeCoreCheck.detail, activeCoreCheck.params) }}</span>
          </div>
          <p class="resource-dialog-note">{{ t("coreVersionManualAction") }}</p>
        </div>
      </section>

      <section v-else-if="resourceDialog === 'plugins' && activeDetailVersion" class="resource-detail-dialog resource-detail-dialog-wide" role="dialog" aria-modal="true" :aria-label="t('requiredPlugins')">
        <header class="resource-dialog-head">
          <div class="resource-dialog-title">
            <span class="section-icon"><PackageOpen :size="19" /></span>
            <div>
              <h2>{{ t("requiredPlugins") }} <em>{{ activeDetailVersion.custom_nodes.length }}</em></h2>
              <p>{{ t(activePluginCheck.detail, activePluginCheck.params) }}</p>
            </div>
          </div>
          <button class="icon-button" :title="t('close')" :aria-label="t('close')" @click="closeResourceDialog"><X :size="18" /></button>
        </header>
        <div class="resource-dialog-content">
          <section v-if="activeDetailVersion.custom_nodes.length" class="resource-group plugin-resource-group resource-dialog-resource-group">
            <div class="resource-group-heading dependency-group-heading">
              <span><ListFilter :size="16" /><strong>{{ t("dependencyDetails") }}</strong></span>
              <div class="resource-heading-actions">
                <button
                  class="ghost compact-action dependency-refresh-action"
                  :disabled="!!busy || dependencyPlanLoading[dependencyKey(selected, activeDetailVersion)]"
                  :title="t('checkPluginDependencies')"
                  @click="planDependencies(selected, activeDetailVersion)">
                  <ListFilter :size="14" />{{ t("checkPluginDependencies") }}
                </button>
              </div>
            </div>
            <div v-if="dependencyPlanLoading[dependencyKey(selected, activeDetailVersion)]" class="dependency-inline-state"><LoaderCircle :size="15" class="dependency-task-spin" /><span>{{ t("checkingDependencies") }}</span></div>
            <div v-if="dependencyPlans[dependencyKey(selected, activeDetailVersion)]" class="dependency-plan-toolbar">
              <div class="dependency-plan-summary">
                <strong>{{ t("dependencyPlanSummary", { selected: dependencySelectedChangeCount(dependencyKey(selected, activeDetailVersion)), total: dependencyChangeCount(dependencyKey(selected, activeDetailVersion)) }) }}</strong>
                <small v-if="!dependencyChangeCount(dependencyKey(selected, activeDetailVersion))">{{ t("dependencyNoChanges") }}</small>
              </div>
              <label class="version-alignment-row"><input
                :checked="dependencyAlignment[dependencyKey(selected, activeDetailVersion)] !== false"
                type="checkbox"
                @change="toggleDependencyAlignment(selected, activeDetailVersion, ($event.target as HTMLInputElement).checked)" />{{ t("alignDependencyVersions") }}</label>
            </div>
            <div v-if="dependencyPlans[dependencyKey(selected, activeDetailVersion)] && !status?.git.available && !status?.manager?.compatible" class="message warning"><TriangleAlert :size="17" /><span>{{ t("dependencyInstallerUnavailable") }}</span></div>
            <div v-if="dependencyPlans[dependencyKey(selected, activeDetailVersion)] && status?.git.launcher_mirrors?.git" class="dependency-inline-state dependency-inline-state-muted"><Info :size="15" /><span>{{ t("dependencyLauncherGitMirror") }}</span></div>
            <div v-if="dependencyAlignment[dependencyKey(selected, activeDetailVersion)] === false" class="message warning"><TriangleAlert :size="16" /><span>{{ t("versionAlignmentDisabledWarning") }}</span></div>
            <div v-if="dependencyPlans[dependencyKey(selected, activeDetailVersion)] && dependencyChangeCount(dependencyKey(selected, activeDetailVersion))" class="dependency-plan-actions">
              <button class="primary wide"
                :disabled="!dependencySelectedChangeCount(dependencyKey(selected, activeDetailVersion)) || !selectedDependencyActions[dependencyKey(selected, activeDetailVersion)]?.every((id) => dependencyActionAvailable(dependencyKey(selected, activeDetailVersion), id)) || !!busy || dependencyOperationRunning || dependencyPlanLoading[dependencyKey(selected, activeDetailVersion)]"
                @click="executeDependencyPlan(selected, activeDetailVersion)">{{ t("oneClickInstall") }}</button>
            </div>
            <div v-if="activeDependencyExecution" class="dependency-execution">
              <div class="dependency-progress-head">
                <span>{{ t("installProgress", { done: activeDependencyExecution.done, total: activeDependencyExecution.total }) }}</span>
                <div class="dependency-progress"><div class="dependency-progress-bar" :style="{ width: `${Math.round((activeDependencyExecution.done / Math.max(activeDependencyExecution.total, 1)) * 100)}%` }"></div></div>
              </div>
              <ul class="dependency-tasks">
                <li v-for="task in activeDependencyExecution.tasks" :key="task.registryId" :data-state="task.state">
                  <LoaderCircle v-if="task.state === 'installing' || task.state === 'python_installing'" :size="15" class="dependency-task-spin" />
                  <CheckCircle2 v-else-if="task.state === 'success'" :size="15" />
                  <AlertCircle v-else-if="task.state === 'failed'" :size="15" />
                  <Clock v-else :size="15" />
                  <span class="dependency-task-name"><strong>{{ task.name }}</strong><small v-if="task.version">{{ task.version }}</small></span>
                  <span class="dependency-task-state">{{ t(dependencyTaskStateKeys[task.state]) }}</span>
                  <small v-if="task.message" class="dependency-task-message">{{ task.message }}</small>
                </li>
              </ul>
              <details v-if="activeDependencyExecution.logs.length" class="dependency-logs" open>
                <summary>{{ t("installLogs", { count: activeDependencyExecution.logs.length }) }}</summary>
                <pre>{{ activeDependencyExecution.logs.join("\n") }}</pre>
              </details>
              <div v-if="activeDependencyExecution.finished" class="dependency-result">
                <span v-if="dependencyExecutionFailures">{{ t("installFinishedWithFailures", { count: dependencyExecutionFailures }) }}</span>
                <span v-else>{{ t("installFinished") }}</span>
                <span v-if="!dependencyExecutionFailures">{{ t("restartToApply") }}</span>
                <pre v-if="dependencyExecutionFailures && activeDependencyOperation?.error_code">{{ operationErrorMessage(activeDependencyOperation) }}</pre>
              </div>
            </div>
            <template v-for="node in activeDetailVersion.custom_nodes" :key="node.source_url || node.registry_id || node.name">
              <template v-for="entry in [dependencyPlanEntry(node)]" :key="`plan-${node.source_url || node.registry_id || node.name}`">
                <div class="asset-row plugin-asset-row" :class="{ 'has-selection': entry && dependencyActionRequiresSelection(entry.action), 'dependency-selected': entry && dependencyActionRequiresSelection(entry.action) && dependencyActionSelected(dependencyKey(selected, activeDetailVersion), entry) }" @click="toggleDependencyRow(dependencyKey(selected, activeDetailVersion), entry)">
                  <input
                    v-if="entry && dependencyActionRequiresSelection(entry.action)"
                    class="asset-select"
                    type="checkbox"
                    :aria-label="`${t('selectPlugin')}: ${node.name}`"
                    :checked="dependencyActionSelected(dependencyKey(selected, activeDetailVersion), entry)"
                    :disabled="!dependencyInstallerAvailable(entry)"
                    @click.stop
                    @change="toggleDependencyAction(dependencyKey(selected, activeDetailVersion), dependencyActionKey(entry), ($event.target as HTMLInputElement).checked)"
                  />
                  <span class="asset-identity">
                    <CheckCircle2 v-if="entry && entry.action === 'keep'" :size="16" class="dep-tone-ok" />
                    <CircleX v-else-if="entry && entry.action === 'install'" :size="16" class="dep-tone-missing" />
                    <TriangleAlert v-else-if="entry && (entry.action === 'upgrade' || entry.action === 'downgrade' || entry.action === 'conflict')" :size="16" class="dep-tone-warn" />
                    <PackageOpen v-else :size="16" />
                    <strong>{{ node.name }}</strong>
                    <small :title="node.source_url || node.registry_id || undefined">{{ node.source_url || node.registry_id || t("githubSourceUnavailable") }}</small>
                    <small v-if="entry && entry.warning_code" class="dependency-warning">{{ dependencyWarning(entry) }}</small>
                  </span>
                  <span class="asset-meta">
                    <span class="asset-meta-line"><b v-if="entry" class="dependency-installer-badge" :data-installer="entry.installer">{{ entry.installer === "manager" ? t("installerManager") : t("installerGit") }}</b><small :title="dependencyVersionTitle(node, entry)">{{ dependencyVersionLabel(node, entry) }}</small></span>
                    <b
                      v-if="entry"
                      class="dependency-status"
                      :data-tone="entry.action === 'keep' ? 'ok' : entry.action === 'install' ? 'missing' : entry.action === 'upgrade' || entry.action === 'downgrade' || entry.action === 'conflict' ? 'warn' : 'muted'"
                    >{{ t(dependencyActionLabels[entry.action]) }}</b>
                    <a
                      v-if="dependencySourceUrl(node)"
                      class="dependency-source-link"
                      :href="dependencySourceUrl(node)"
                      target="_blank"
                      rel="noopener noreferrer"
                      :title="t('openPluginSource')"
                      :aria-label="`${t('openPluginSource')}: ${node.name}`"
                      @click.stop
                    ><ExternalLink :size="15" /></a>
                  </span>
                </div>
              </template>
            </template>
            <div v-if="!dependencyPlanLoading[dependencyKey(selected, activeDetailVersion)] && !dependencyPlans[dependencyKey(selected, activeDetailVersion)] && !status?.git.available && !status?.manager?.compatible" class="dependency-inline-state dependency-inline-state-muted"><TriangleAlert :size="15" /><span>{{ t("dependencyInstallerUnavailable") }}</span></div>
          </section>
          <div v-else class="dependency-empty"><CheckCircle2 :size="17" /><span>{{ t("pluginStatusNoDependenciesDetail") }}</span></div>
        </div>
      </section>

      <section v-else class="resource-detail-dialog" role="dialog" aria-modal="true" :aria-label="t('includedImages')">
        <header class="resource-dialog-head">
          <div class="resource-dialog-title">
            <span class="section-icon"><FileUp :size="19" /></span>
            <div>
              <h2>{{ t("includedImages") }}</h2>
              <p>{{ t(activeImageCount ? "includedImagesDetail" : "noBundledImagesDetail", { count: activeImageCount }) }}</p>
            </div>
          </div>
          <button class="icon-button" :title="t('close')" :aria-label="t('close')" @click="closeResourceDialog"><X :size="18" /></button>
        </header>
        <div class="resource-dialog-content">
          <div v-if="activeImageCount" class="resource-dialog-list">
            <div v-for="input in activeDetailVersion.inputs || []" :key="input.archive" class="asset-row">
              <span><FileUp :size="15" /><strong>{{ input.source }}</strong><small>{{ t("referenceCount", { count: input.node_ids.length }) }}</small></span>
              <em>{{ humanBytes(input.size) }}</em>
            </div>
          </div>
          <div v-else class="dependency-empty"><CheckCircle2 :size="17" /><span>{{ t("noBundledImagesHint") }}</span></div>
        </div>
      </section>
    </div>

    <div v-if="downloadPreflight" class="backdrop download-preflight-backdrop" @click.self="closeDownloadPreflight">
      <section class="download-check-dialog" role="dialog" aria-modal="true" aria-labelledby="download-check-title">
        <header class="download-check-head">
          <div class="download-check-title">
            <span class="section-icon"><ShieldCheck :size="19" /></span>
            <div>
              <h2 id="download-check-title">{{ t("downloadCheckTitle") }}</h2>
              <p>{{ t("downloadCheckDescription", { name: downloadPreflight.item.name, version: downloadPreflight.version.version }) }}</p>
            </div>
          </div>
          <button class="icon-button" :disabled="downloadPreflight.syncing" :title="t('close')" :aria-label="t('close')" @click="closeDownloadPreflight"><X :size="18" /></button>
        </header>

        <div v-if="downloadPreflight.syncing" class="download-check-syncing"><LoaderCircle :size="17" class="dependency-task-spin" /><span>{{ t("downloadCheckSyncing") }}</span></div>
        <div v-if="downloadPreflight.syncError" class="message warning"><TriangleAlert :size="17" /><span>{{ downloadPreflight.syncError }}</span></div>
        <div v-if="downloadPreflight.environmentError" class="message warning"><TriangleAlert :size="17" /><span>{{ downloadPreflight.environmentError }}</span></div>
        <div v-if="downloadPreflight.core.state === 'mismatch' || downloadPreflight.core.state === 'unavailable'" class="download-check-section download-check-core">
          <div class="download-check-section-head">
            <span><ActivityIcon :size="16" /><strong>{{ t("comfyCoreVersion") }}</strong></span>
            <b class="dependency-status" :data-tone="downloadPreflight.core.tone">{{ t(downloadPreflight.core.label) }}</b>
          </div>
          <div class="download-check-core-versions">
            <span><small>{{ t("coreVersionCurrent") }}</small><strong>{{ downloadPreflight.currentCoreVersion || t("detecting") }}</strong></span>
            <ArrowRight :size="16" />
            <span><small>{{ t("coreVersionRequired") }}</small><strong>{{ comfyuiCompatibilityLabel(downloadPreflight.version) }}</strong></span>
          </div>
          <p>{{ t(downloadPreflight.core.detail, downloadPreflight.core.params) }}</p>
          <small class="download-check-manual-hint">{{ t("coreVersionManualAction") }}</small>
        </div>

        <div v-if="preflightDependencyIssues.length" class="download-check-section">
          <div class="download-check-section-head">
            <span><PackageOpen :size="16" /><strong>{{ t("downloadCheckPlugins") }}</strong><em>{{ preflightDependencyIssues.length }}</em></span>
            <b class="dependency-status" data-tone="warn">{{ t("downloadCheckAttention") }}</b>
          </div>
          <div v-for="entry in preflightDependencyIssues" :key="`download-check-${dependencyActionKey(entry)}`" class="download-check-dependency">
            <span>
              <PackageOpen :size="15" />
              <strong>{{ entry.name }}</strong>
              <small>{{ entry.warning_code === "dependencies.non_git_install" ? t("nonGitInstall") : entry.installed || t("notInstalled") }} → {{ entry.requested || t("gitRevisionUnavailable") }}</small>
              <small v-if="entry.warning_code" class="dependency-warning">{{ dependencyWarning(entry) }}</small>
            </span>
            <span class="download-check-dependency-meta">
              <b class="dependency-status" :data-tone="dependencyActionTone(entry.action)">{{ t(dependencyActionLabels[entry.action]) }}</b>
              <a
                v-if="dependencySourceUrl(entry)"
                class="dependency-source-link"
                :href="dependencySourceUrl(entry)"
                target="_blank"
                rel="noopener noreferrer"
                :title="t('openPluginSource')"
                :aria-label="`${t('openPluginSource')}: ${entry.name}`"
              ><ExternalLink :size="15" /></a>
            </span>
          </div>
          <p v-if="preflightSyncableDependencies.length" class="download-check-hint">{{ t("downloadCheckSyncHint", { count: preflightSyncableDependencies.length }) }}</p>
          <p v-else class="download-check-hint">{{ t("downloadCheckManualPluginHint") }}</p>
        </div>
        <div v-if="downloadPreflight.dependencyError" class="message warning"><TriangleAlert :size="17" /><span>{{ downloadPreflight.dependencyError }}</span></div>

        <footer class="download-check-actions">
          <button v-if="downloadPreflight.environmentError || downloadPreflight.dependencyError || downloadPreflight.syncError" class="ghost" :disabled="!!busy || downloadPreflight.syncing" @click="retryDownloadPreflight">{{ t("retryCheck") }}</button>
          <button class="ghost" :disabled="downloadPreflight.syncing" @click="closeDownloadPreflight">{{ t("cancel") }}</button>
          <button class="secondary" :disabled="downloadPreflight.syncing" @click="skipDownloadPreflight">{{ t("downloadAnyway") }}</button>
          <button v-if="preflightSyncableDependencies.length" class="primary" :disabled="!!busy || downloadPreflight.syncing" @click="syncDownloadDependencies"><LoaderCircle v-if="downloadPreflight.syncing" :size="16" class="dependency-task-spin" />{{ t("syncPluginsThenDownload") }}</button>
        </footer>
      </section>
    </div>

    <div v-if="editingProduct" class="backdrop" @click.self="editingProduct = null">
      <section class="manage-dialog">
        <h2>{{ t("editMetadataTitle") }}</h2>
        <label class="compact-field"><span>{{ t("name") }}</span><input v-model="editForm.name" maxlength="80" /></label>
        <label class="compact-field"><span>{{ t("category") }}</span><input v-model="editForm.category" maxlength="80" /></label>
        <label class="compact-field"><span>{{ t("summary") }}</span><input v-model="editForm.summary" maxlength="300" /></label>
        <label class="compact-field"><span>{{ t("description") }}</span><textarea v-model="editForm.description" rows="4"></textarea></label>
        <label class="compact-field"><span>{{ t("tags") }}</span><input v-model="editForm.tags" /></label>
        <div class="manage-dialog-actions">
          <button class="ghost" @click="editingProduct = null">{{ t("cancel") }}</button>
          <button class="primary" :disabled="!!busy || publisherManagementOperationRunning || !editForm.name.trim() || !editForm.category.trim()" @click="saveProductEditor">{{ t("save") }}</button>
        </div>
      </section>
    </div>

    <div v-if="editingChangelog" class="backdrop" @click.self="editingChangelog = null">
      <section class="manage-dialog">
        <h2>{{ t("changelogFor", { version: editingChangelog.version.version }) }}</h2>
        <div class="manage-changelog-toolbar">
          <button class="ghost compact-action" type="button" @click="manageChangelogFileInput?.click()"><FileUp :size="14" />{{ t("importChangelogFromFile") }}</button>
        </div>
        <textarea v-model="editingChangelog.text" rows="8" class="manage-changelog-input"></textarea>
        <input ref="manageChangelogFileInput" type="file" accept=".md,.markdown,.txt" hidden @change="importChangelogFile($event, (text) => { if (editingChangelog) editingChangelog.text = text; })" />
        <div class="manage-dialog-actions">
          <button class="ghost" @click="editingChangelog = null">{{ t("cancel") }}</button>
          <button class="primary" :disabled="!!busy || publisherManagementOperationRunning || !editingChangelog.text.trim()" @click="saveChangelogEditor">{{ t("save") }}</button>
        </div>
      </section>
    </div>

    <div v-if="dependencyPinEditor" class="backdrop" @click.self="dependencyPinEditor = null">
      <section class="manage-dialog dependency-pin-dialog" role="dialog" aria-modal="true" :aria-label="t('updateDependencies')">
        <div class="dependency-pin-head">
          <h2>{{ t("dependencyPinTitle", { version: dependencyPinEditor.version.version }) }}</h2>
          <p>{{ t("dependencyPinDescription") }}</p>
        </div>
        <div class="dependency-pin-toolbar">
          <small v-if="dependencyPinEditor.readonlyCount">{{ t("dependencyPinReadonly", { count: dependencyPinEditor.readonlyCount }) }}</small>
          <span v-else></span>
          <button
            class="ghost compact-action"
            :disabled="dependencyPinEditor.loading || !!busy || publisherManagementOperationRunning || !dependencyPinEditor.entries.some((entry) => dependencyPinLatest(entry))"
            @click="useAllLatestDependencyCommits"
          ><RefreshCw :size="14" />{{ t("dependencyPinAllLatest") }}</button>
        </div>
        <div v-if="dependencyPinEditor.loading" class="dependency-pin-loading"><LoaderCircle :size="16" class="dependency-task-spin" /><span>{{ t("dependencyPinLoading") }}</span></div>
        <ul class="dependency-pin-list">
          <li v-for="entry in dependencyPinEditor.entries" :key="entry.key">
            <span class="dependency-pin-identity">
              <strong>{{ entry.name }}</strong>
              <small :title="entry.source_url">{{ entry.source_url }}</small>
              <small class="dependency-pin-current">{{ t("dependencyPinCurrent") }}: {{ entry.current.slice(0, 7) }}</small>
            </span>
            <span class="dependency-pin-picker">
              <span class="select-control">
                <select v-model="entry.selected" :disabled="dependencyPinEditor.loading || !entry.commits.length" :aria-label="`${t('dependencyPinSelectCommit')}: ${entry.name}`">
                  <option v-if="!entry.commits.length" :value="entry.current">{{ t("dependencyPinNoCommits") }}</option>
                  <option v-for="option in entry.commits" :key="option.sha" :value="option.sha">{{ dependencyPinOptionLabel(option) }}</option>
                </select>
                <span class="select-chevron" aria-hidden="true"><ChevronDown :size="14" :stroke-width="2.4" /></span>
              </span>
              <button class="ghost compact-action" :disabled="!dependencyPinLatest(entry) || entry.selected === dependencyPinLatest(entry)" @click="useLatestDependencyCommit(entry)">{{ t("dependencyPinUseLatest") }}</button>
            </span>
            <small v-if="entry.error && !dependencyPinEditor.loading" class="dependency-pin-error">{{ entry.error }}</small>
          </li>
        </ul>
        <div class="manage-dialog-actions">
          <button class="ghost" @click="dependencyPinEditor = null">{{ t("cancel") }}</button>
          <button class="primary" :disabled="!!busy || publisherManagementOperationRunning || dependencyPinEditor.loading || !dependencyPinChanges.length" @click="saveDependencyPinEditor">{{ t("dependencyPinConfirm", { count: dependencyPinChanges.length }) }}</button>
        </div>
      </section>
    </div>

    <div v-if="settingsOpen" class="backdrop" @click.self="closeSettings">
      <section class="settings-dialog" role="dialog" aria-modal="true" :aria-label="t('settings')">
        <div class="settings-dialog-head">
          <div class="settings-dialog-title"><span class="section-icon"><SettingsIcon :size="18" /></span><h2>{{ t("settings") }}</h2></div>
          <button class="icon-button" :title="t('close')" :aria-label="t('close')" :disabled="settingsSaving" @click="closeSettings"><X :size="18" /></button>
        </div>
        <div class="settings-dialog-body">
          <label class="settings-toggle-row">
            <span class="settings-toggle-copy">
              <strong>{{ t("autoUpdateCheck") }}</strong>
              <small>{{ t("autoUpdateCheckHint") }}</small>
            </span>
            <input v-model="settingsDraft.auto_update_check" type="checkbox" @change="settingsSaved = false" />
          </label>
          <label class="settings-field">
            <span>{{ t("updateCheckInterval") }}</span>
            <div class="settings-number-input">
              <input v-model.number="settingsDraft.update_check_interval_hours" type="number" min="1" max="168" step="1" :disabled="!settingsDraft.auto_update_check" @input="settingsSaved = false" />
              <span>{{ t("hours") }}</span>
            </div>
            <small>{{ t("updateCheckIntervalHint", { hours: settingsDraft.update_check_interval_hours }) }}</small>
          </label>
          <p v-if="settingsError" class="settings-inline-error"><AlertCircle :size="16" />{{ settingsError }}</p>
          <p v-else-if="settingsSaved" class="settings-inline-success"><CheckCircle2 :size="16" />{{ t("settingsSaved") }}</p>
          <p v-if="status?.settings?.last_checked_at" class="settings-last-check">
            {{ t("lastUpdateCheck", { time: operationTimeLabel(status.settings.last_checked_at) }) }}
          </p>
        </div>
        <div class="settings-dialog-actions">
          <button class="ghost" :disabled="settingsSaving" @click="closeSettings">{{ t("cancel") }}</button>
          <button class="primary" :disabled="settingsSaving" @click="saveSettings">
            <LoaderCircle v-if="settingsSaving" :size="16" class="dependency-task-spin" />
            <Check v-else :size="16" />{{ t("save") }}
          </button>
        </div>
      </section>
    </div>

    <aside v-if="drawer" class="activity-drawer" :aria-busy="activityMutationBusy">
      <div class="drawer-head">
        <div class="drawer-title"><span class="section-icon"><ActivityIcon :size="18" /></span><h2>{{ t("activities") }}</h2></div>
        <div class="drawer-actions">
          <button
            v-if="completedOperationCount > 0"
            class="ghost activity-clear"
            :disabled="activityMutationBusy"
            :title="t('clearCompletedActivities', { count: completedOperationCount })"
            :aria-label="t('clearCompletedActivities', { count: completedOperationCount })"
            @click="clearCompletedOperations"
          >
            <LoaderCircle v-if="clearingOperations" :size="15" class="dependency-task-spin" />
            <Trash2 v-else :size="15" />
            {{ t("clearCompletedActivities", { count: completedOperationCount }) }}
          </button>
          <button class="icon-button" :title="t('close')" :aria-label="t('close')" @click="drawer = false"><X :size="18" /></button>
        </div>
      </div>
      <div v-if="!operations.length" class="empty small"><ActivityIcon :size="25" /><span>{{ t("noActivities") }}</span></div>
      <div v-else class="activity-list">
        <article v-for="item in operations" :key="item.id" class="operation">
          <div class="operation-heading">
            <div class="operation-label"><strong>{{ operationKindLabel(item.kind, item.metadata) }}</strong><span :class="`status ${item.status}`">{{ operationStageLabel(item.stage) }}</span></div>
            <button
              v-if="!isOperationActive(item)"
              class="icon-button operation-delete"
              :disabled="activityMutationBusy"
              :title="t('deleteActivity')"
              :aria-label="t('deleteActivity')"
              @click="deleteOperation(item)"
            >
              <LoaderCircle v-if="deletingOperationIds[item.id]" :size="15" class="dependency-task-spin" />
              <Trash2 v-else :size="15" />
            </button>
          </div>
          <time class="operation-time" :datetime="item.created_at">{{ t("activityTime", { time: operationTimeLabel(item.created_at) }) }}</time>
          <template v-if="hasStageProgress(item)">
            <div
              class="operation-stage-progress"
              :class="{ complete: item.status === 'success', failed: item.status === 'failed' }"
              role="progressbar"
              :aria-label="stageProgressLabel(item)"
              aria-valuemin="0"
              :aria-valuemax="stageProgress(item).total"
              :aria-valuenow="stageProgress(item).completed"
            >
              <span
                v-for="(_, index) in operationProgressStages(item) || []"
                :key="index"
                :class="{
                  complete: index < stageProgress(item).completed,
                  active: item.status === 'running' && index === stageProgress(item).current - 1,
                  failed: item.status === 'failed' && index === stageProgress(item).current - 1,
                }"
              />
            </div>
            <small class="progress-copy stage-progress-copy">{{ stageProgressLabel(item) }}</small>
          </template>
          <template v-if="item.progress?.total">
            <div class="operation-progress" role="progressbar" aria-valuemin="0" aria-valuemax="100"
              :aria-valuenow="Math.round(progressPercent(item.progress))">
              <i :style="{ width: `${progressPercent(item.progress)}%` }" />
            </div>
            <small class="progress-copy">{{ item.progress_mode === "tasks" ? t("installProgress", { done: item.progress.received, total: item.progress.total }) : `${humanBytes(item.progress.received)} / ${humanBytes(item.progress.total)}` }}</small>
          </template>
          <ul v-if="item.kind === 'dependencies' && operationTaskRows(item).length" class="operation-tasks">
            <li v-for="task in operationTaskRows(item)" :key="task.registryId" :data-state="task.state">
              <LoaderCircle v-if="task.state === 'installing' || task.state === 'python_installing'" :size="14" class="dependency-task-spin" />
              <CheckCircle2 v-else-if="task.state === 'success'" :size="14" />
              <AlertCircle v-else-if="task.state === 'failed'" :size="14" />
              <Clock v-else :size="14" />
              <span>{{ task.name }}</span><small>{{ task.version || task.installer || "" }}</small>
            </li>
          </ul>
          <pre v-if="item.error_code || item.logs.length">{{ operationErrorMessage(item) }}</pre>
        </article>
      </div>
    </aside>

  </div>
</template>
