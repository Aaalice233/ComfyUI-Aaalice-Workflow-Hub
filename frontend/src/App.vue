<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from "vue";
import {
  Activity as ActivityIcon,
  AlertCircle,
  Archive as ArchiveIcon,
  ArrowRight,
  Check,
  CheckCircle2,
  CircleUserRound,
  Compass,
  Copy,
  Download as DownloadIcon,
  ExternalLink,
  FileJson,
  FileUp,
  FolderGit2,
  FolderOpen,
  GitBranch,
  LibraryBig,
  ListFilter,
  LogOut,
  PackageOpen,
  Plus,
  RefreshCw,
  Search as SearchIcon,
  ShieldCheck,
  Trash2,
  TriangleAlert,
  UploadCloud,
  X,
} from "@lucide/vue";
import { api, post, remove } from "./api";
import { locale, t } from "./i18n";

type Source = { owner: string; repo: string; url: string; refreshed_at: string; error?: string };
type ModelAsset = { name: string; type: string; filename: string; source_url: string; sha256?: string | null };
type AssetReference = {
  name: string; filename: string; node_ids: string[]; status: string; size?: number | null; sha256?: string | null;
};
type BundledInput = {
  source: string; archive: string; size: number; sha256: string; node_ids: string[];
};
type Version = {
  version: string; published_at: string; release_tag: string; changelog: string;
  comfyui: { minimum?: string | null; maximum?: string | null };
  package: { url: string; size: number; sha256: string };
  preview?: { url: string; sha256: string } | null;
  custom_nodes: NodeDependencyInfo[]; inputs?: BundledInput[]; models: ModelAsset[];
};
type Product = {
  id: string; name: string; category?: string; summary: string; description: string; tags: string[]; archived: boolean;
  cover?: { url: string; sha256: string } | null;
  versions: Version[]; downloaded_versions: string[]; source: { owner: string; repo: string };
};
type Status = {
  plugin_version: string;
  manager: { available: boolean; compatible: boolean; version?: string };
  github: { configured: boolean; authenticated: boolean; user?: { login: string; avatar_url: string }; persistent_credentials: boolean };
};
type Operation = {
  id: string; kind: string; stage: string; status: string; logs: string[];
  progress?: { received: number; total: number }; result?: Record<string, unknown>;
};
type DependencyPlan = {
  registry_id?: string | null; name: string; requested?: string | null; installed?: string | null;
  action: "keep" | "install" | "upgrade" | "newer" | "conflict" | "unknown" | "manual";
  warning?: string | null;
};
type NodeDependencyInfo = {
  registry_id?: string | null; name: string; version?: string | null; manual?: boolean;
};
type PublishCatalogProduct = {
  id: string; name: string; category: string; summary: string; description: string; tags: string[]; versions: string[];
};

const LAST_PUBLISH_REPOSITORY_KEY = "aaalice-workflow-hub:last-publish-repository";
const tab = ref<"subscribe" | "publish">("subscribe");
const status = ref<Status | null>(null);
const sources = ref<Source[]>([]);
const products = ref<Product[]>([]);
const selected = ref<Product | null>(null);
const selectedDetailVersion = ref("");
const sourceUrl = ref("");
const sourceInput = ref<HTMLInputElement | null>(null);
const searchInput = ref<HTMLInputElement | null>(null);
const sourceComposerOpen = ref(false);
const search = ref("");
const filter = ref<"all" | "downloaded" | "updates" | "archived">("all");
const busy = ref("");
const error = ref("");
const notice = ref("");
const drawer = ref(false);
const operations = ref<Operation[]>([]);
const repositories = ref<{ full_name: string; name?: string; owner?: string; description?: string }[]>([]);
const createRepositoryName = ref("");
const createRepositoryOpen = ref(false);
const drafts = ref<{ id: string; name: string; payload: ReturnType<typeof payload> }[]>([]);
const pendingPublications = ref<{ tag: string }[]>([]);
const workflow = ref<Record<string, unknown> | null>(null);
const workflowSourceName = ref("");
const canvasWorkflowError = ref("");
const dependencyScanError = ref("");
const publishCatalogProducts = ref<PublishCatalogProduct[]>([]);
const repositoryCategories = ref<string[]>([]);
const selectedCatalogProductId = ref("");
const imageReferences = ref<AssetReference[]>([]);
const loraReferences = ref<AssetReference[]>([]);
const selectedLoras = ref<string[]>([]);
const publisherAssetTab = ref<"nodes" | "images" | "loras">("nodes");
const device = ref<{ user_code: string; verification_uri: string; interval: number } | null>(null);
const deviceCodeCopied = ref(false);
const dependencyPlans = reactive<Record<string, DependencyPlan[]>>({});
const selectedDependencyActions = reactive<Record<string, string[]>>({});
const dependencyConfirmed = reactive<Record<string, boolean>>({});
let operationTimer = 0;
let loginTimer = 0;
let copiedTimer = 0;

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
  minimum: "",
  maximum: "",
  changelog: "",
  custom_nodes: "[]",
  models: "[]",
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
const canAdvancePublish = computed(() => {
  return !!form.repository_url.trim() && !!form.repository_name.trim() && !!form.author.trim();
});
const generatedProductConflict = computed(() => {
  if (selectedCatalogProductId.value || !form.name.trim()) return null;
  const candidate = generatedWorkflowId(form.name.trim());
  return publishCatalogProducts.value.find((item) => item.id === candidate) || null;
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
  if (!workflow.value || !canAdvancePublish.value || !form.name.trim() || generatedProductConflict.value || existingVersionConflict.value
    || !/^(0|[1-9]\d*)\.(0|[1-9]\d*)(?:\.(0|[1-9]\d*))?$/.test(form.version.trim())
    || !form.changelog.trim()) {
    return false;
  }
  try {
    return Array.isArray(JSON.parse(form.custom_nodes)) && Array.isArray(JSON.parse(form.models));
  } catch {
    return false;
  }
});
const customNodeDependencies = computed<NodeDependencyInfo[]>(() => {
  try {
    const items = JSON.parse(form.custom_nodes);
    return Array.isArray(items) ? items : [];
  } catch {
    return [];
  }
});
const customNodeCount = computed(() => customNodeDependencies.value.length);
function normalizeVersion(value: string): number[] {
  const parts = value.split(".").map(Number);
  return [parts[0] || 0, parts[1] || 0, parts[2] || 0];
}
function compareVersions(a: Version, b: Version) {
  const left = normalizeVersion(a.version), right = normalizeVersion(b.version);
  return left[0] - right[0] || left[1] - right[1] || left[2] - right[2];
}
function latest(item: Product) {
  return [...item.versions].sort(compareVersions).at(-1);
}
function productCover(item: Product) {
  return item.cover || latest(item)?.preview || null;
}
function repositoryUrl(item: Product) {
  return `https://github.com/${encodeURIComponent(item.source.owner)}/${encodeURIComponent(item.source.repo)}`;
}
function releaseUrl(item: Product, version: Version) {
  return `${repositoryUrl(item)}/releases/tag/${encodeURIComponent(version.release_tag)}`;
}
function openDetails(item: Product) {
  selected.value = item;
  selectedDetailVersion.value = latest(item)?.version || "";
}
function dependencyKey(item: Product, version: Version) {
  return `${item.source.owner}/${item.source.repo}/${item.id}@${version.version}`;
}
function dependencyActionKey(item: DependencyPlan, index: number) {
  return `${index}:${item.registry_id || item.name}:${item.requested || ""}:${item.action}`;
}
function humanBytes(value: number) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KiB`;
  return `${(value / 1024 / 1024).toFixed(1)} MiB`;
}
function loraAssets(version: Version) {
  return version.models.filter((model) => model.type === "loras");
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
async function load() {
  clearMessages();
  const [s, sub, flows, ops] = await Promise.all([
    api<Status>("/status"),
    api<{ items: Source[] }>("/subscriptions"),
    api<{ items: Product[] }>("/workflows"),
    api<{ items: Operation[] }>("/operations"),
  ]);
  status.value = s;
  sources.value = sub.items;
  products.value = flows.items;
  operations.value = ops.items;
  if (s.github.authenticated) {
    const [repos, savedDrafts, pending] = await Promise.all([
      api<{ items: { full_name: string; name?: string; owner?: string; description?: string }[] }>("/github/repositories"),
      api<{ items: typeof drafts.value }>("/publisher/drafts"),
      api<{ items: { tag: string }[] }>("/publisher/pending"),
    ]);
    repositories.value = repos.items;
    if (!form.repository_url) {
      let remembered = "";
      try {
        remembered = window.localStorage.getItem(LAST_PUBLISH_REPOSITORY_KEY) || "";
      } catch {
        // Browser storage may be unavailable in hardened embedded views.
      }
      const rememberedExists = repositories.value.some(
        (item) => `https://github.com/${item.full_name}`.toLocaleLowerCase() === remembered.toLocaleLowerCase()
      );
      if (rememberedExists) {
        form.repository_url = remembered;
      } else if (repositories.value.length) {
        form.repository_url = `https://github.com/${repositories.value[0].full_name}`;
      }
    }
    await applySelectedRepository();
    drafts.value = savedDrafts.items;
    pendingPublications.value = pending.items;
  } else {
    repositories.value = [];
  }
  if (selected.value) {
    selected.value = products.value.find((item) =>
      item.id === selected.value?.id
      && item.source.owner === selected.value?.source.owner
      && item.source.repo === selected.value?.source.repo
    ) || null;
  }
}
async function withBusy(name: string, action: () => Promise<void>) {
  busy.value = name;
  clearMessages();
  try { await action(); } catch (reason) { error.value = reason instanceof Error ? reason.message : String(reason); }
  finally { busy.value = ""; }
}
async function addSource() {
  await withBusy("add-source", async () => {
    await post("/subscriptions", { url: sourceUrl.value });
    sourceUrl.value = "";
    await load();
  });
}
async function refreshSource(item: Source) {
  await withBusy(`refresh-${item.owner}-${item.repo}`, async () => {
    await post(`/subscriptions/${item.owner}/${item.repo}/refresh`, {});
    await load();
  });
}
async function removeSource(item: Source) {
  if (!confirm(locale.value === "zh" ? "移除订阅源？已下载的工作流会保留。" : "Remove subscription? Downloads are kept.")) return;
  await withBusy(`remove-${item.owner}-${item.repo}`, async () => {
    await remove(`/subscriptions/${item.owner}/${item.repo}`);
    await load();
  });
}
async function download(item: Product, version: Version) {
  await withBusy("download", async () => {
    const result = await post<{ operation_id: string }>("/workflows/download", {
      owner: item.source.owner, repo: item.source.repo, workflow_id: item.id, version: version.version,
    });
    notice.value = `${t.value("activities")}: ${result.operation_id}`;
    drawer.value = true;
    await pollOperations();
  });
}
async function downloadLora(item: Product, version: Version, model: ModelAsset) {
  await withBusy(`lora-${model.filename}`, async () => {
    const result = await post<{ operation_id: string }>("/workflows/models/download", {
      owner: item.source.owner,
      repo: item.source.repo,
      workflow_id: item.id,
      version: version.version,
      filename: model.filename,
      confirmed: true,
    });
    notice.value = `${t.value("activities")}: ${result.operation_id}`;
    drawer.value = true;
    await pollOperations();
  });
}
async function deleteLocalVersion(item: Product, version: Version) {
  if (!confirm(locale.value === "zh" ? `删除本地版本 v${version.version}？远程 Release 不受影响。` : `Delete local version v${version.version}? The remote release is unchanged.`)) return;
  await withBusy("delete-local", async () => {
    await remove("/workflows/local", {
      owner: item.source.owner, repo: item.source.repo, workflow_id: item.id, version: version.version,
    });
    await load();
  });
}
async function revealLocalVersion(item: Product, version: Version) {
  await withBusy("reveal-local", async () => {
    await post("/workflows/local/reveal", {
      owner: item.source.owner, repo: item.source.repo, workflow_id: item.id, version: version.version,
    });
  });
}
async function planDependencies(item: Product, version: Version) {
  const key = dependencyKey(item, version);
  await withBusy("dependency-plan", async () => {
    const result = await post<{ items: DependencyPlan[] }>("/workflows/dependencies/plan", { dependencies: version.custom_nodes });
    dependencyPlans[key] = result.items;
    selectedDependencyActions[key] = result.items
      .map((entry, index) => ({ entry, id: dependencyActionKey(entry, index) }))
      .filter(({ entry }) => entry.action === "install" || entry.action === "upgrade")
      .map(({ id }) => id);
    dependencyConfirmed[key] = false;
  });
}
function toggleDependencyAction(key: string, id: string, checked: boolean) {
  const values = selectedDependencyActions[key] || [];
  selectedDependencyActions[key] = checked ? [...new Set([...values, id])] : values.filter(value => value !== id);
}
async function executeDependencyPlan(item: Product, version: Version) {
  const key = dependencyKey(item, version);
  if (!dependencyConfirmed[key]) return;
  if (!confirm(locale.value === "zh" ? "确认让 ComfyUI-Manager 串行修改节点环境？" : "Confirm serial environment changes through ComfyUI-Manager?")) return;
  const selectedIds = new Set(selectedDependencyActions[key] || []);
  const actions = (dependencyPlans[key] || []).flatMap((entry, index) => {
    if (!selectedIds.has(dependencyActionKey(entry, index))) return [];
    return [{ ...entry, action: entry.action === "newer" ? "downgrade" : entry.action }];
  });
  await withBusy("dependency-execute", async () => {
    const result = await post<{ queued: DependencyPlan[] }>("/workflows/dependencies/execute", {
      confirmed: true, actions, client_id: "workflow-hub",
    });
    notice.value = locale.value === "zh" ? `已向 Manager 提交 ${result.queued.length} 个串行任务。` : `Queued ${result.queued.length} serial Manager tasks.`;
    dependencyConfirmed[key] = false;
  });
}
async function pollOperations() {
  operations.value = (await api<{ items: Operation[] }>("/operations")).items;
  if (operations.value.some((item) => item.status === "running")) {
    window.clearTimeout(operationTimer);
    operationTimer = window.setTimeout(pollOperations, 1000);
  } else {
    await Promise.all([
      api<{ items: Product[] }>("/workflows").then((value) => products.value = value.items),
      api<{ items: Source[] }>("/subscriptions").then((value) => sources.value = value.items),
    ]);
  }
}
function requestCurrentCanvasWorkflow() {
  const message = { type: "AAALICE_WORKFLOW_HUB_REQUEST_CURRENT_WORKFLOW" };
  const targets = new Set<Window>();
  if (window.parent !== window) targets.add(window.parent);
  if (window.opener && !window.opener.closed) targets.add(window.opener);
  for (const target of targets) target.postMessage(message, window.location.origin);
  if (!targets.size) {
    canvasWorkflowError.value = locale.value === "zh"
      ? "请从 ComfyUI 顶栏打开工作流中心，以读取当前画布。"
      : "Open Workflow Hub from the ComfyUI top bar to read the current canvas.";
  }
}
async function handleHubMessage(event: MessageEvent) {
  if (event.origin !== window.location.origin || event.data?.type !== "AAALICE_WORKFLOW_HUB_CURRENT_WORKFLOW") return;
  const current = event.data?.workflow;
  if (!current || typeof current !== "object" || Array.isArray(current)) {
    canvasWorkflowError.value = event.data?.error || (locale.value === "zh" ? "无法读取当前画布工作流。" : "Unable to read the current canvas workflow.");
    return;
  }
  canvasWorkflowError.value = "";
  workflow.value = current as Record<string, unknown>;
  workflowSourceName.value = String(event.data?.filename || (locale.value === "zh" ? "未命名工作流.json" : "Unsaved Workflow.json"));
  if (!form.name) form.name = workflowSourceName.value.replace(/\.json$/i, "");
  try {
    await scanWorkflowAssets();
  } catch (reason) {
    canvasWorkflowError.value = reason instanceof Error ? reason.message : String(reason);
  }
  try {
    await scanDependencies();
    dependencyScanError.value = "";
  } catch (reason) {
    dependencyScanError.value = reason instanceof Error ? reason.message : String(reason);
  }
}
async function scanDependencies() {
  if (!workflow.value) throw new Error(t.value("workflowUnavailable"));
  const result = await post<{ items: Record<string, unknown>[] }>("/publisher/scan-dependencies", { workflow: workflow.value });
  form.custom_nodes = JSON.stringify(result.items, null, 2);
}
async function scanWorkflowAssets() {
  if (!workflow.value) return;
  const result = await post<{ images: AssetReference[]; loras: AssetReference[] }>("/publisher/scan-assets", {
    workflow: workflow.value,
  });
  imageReferences.value = result.images;
  loraReferences.value = result.loras;
  selectedLoras.value = selectedLoras.value.filter(name =>
    result.loras.some(item => item.name === name && item.status === "ready")
  );
}
function toggleLora(name: string, checked: boolean) {
  selectedLoras.value = checked
    ? [...new Set([...selectedLoras.value, name])]
    : selectedLoras.value.filter(item => item !== name);
}
async function clearWorkflowLoras() {
  if (!workflow.value) return;
  if (!confirm(locale.value === "zh"
    ? "清空此工作流中 Lora Manager 的 LoRA 引用？仅修改当前待发布副本。"
    : "Clear Lora Manager references from this workflow? Only the pending publish copy is changed.")) return;
  await withBusy("clear-loras", async () => {
    const result = await post<{ workflow: Record<string, unknown>; loras: AssetReference[] }>("/publisher/clear-loras", {
      workflow: workflow.value,
    });
    workflow.value = result.workflow;
    loraReferences.value = result.loras;
    selectedLoras.value = [];
    notice.value = locale.value === "zh" ? "已清空当前待发布工作流中的 LoRA 引用。" : "LoRA references cleared from the pending workflow.";
  });
}
function generatedWorkflowId(name: string) {
  const normalized = name.normalize("NFKD").toLocaleLowerCase()
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 64);
  if (normalized) return normalized;
  let hash = 2166136261;
  for (const character of name) {
    hash ^= character.codePointAt(0) || 0;
    hash = Math.imul(hash, 16777619);
  }
  return `workflow-${(hash >>> 0).toString(36)}`;
}
function applySelectedCatalogProduct() {
  const product = publishCatalogProducts.value.find((item) => item.id === selectedCatalogProductId.value);
  if (!product) {
    Object.assign(form, { id: "", name: "", summary: "", description: "", tags: "" });
    return;
  }
  Object.assign(form, {
    id: product.id,
    name: product.name,
    category: product.category,
    summary: product.summary,
    description: product.description,
    tags: product.tags.join(", "),
  });
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
    error.value = reason instanceof Error ? reason.message : String(reason);
  }
  if (!publishCatalogProducts.value.some((item) => item.id === selectedCatalogProductId.value)) {
    selectedCatalogProductId.value = "";
    form.id = "";
  }
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
    await load();
    notice.value = locale.value === "zh"
      ? "仓库已创建。请在 GitHub App 设置中授权该仓库，然后重新加载本页。"
      : "Repository created. Authorize it in the GitHub App installation, then reload this page.";
  });
}
function payload() {
  const customNodes = JSON.parse(form.custom_nodes);
  const models = JSON.parse(form.models);
  if (!form.id) form.id = generatedWorkflowId(form.name.trim());
  const version = {
    version: form.version,
    published_at: new Date().toISOString(),
    release_tag: `${form.id}-v${form.version}`,
    changelog: form.changelog,
    comfyui: { minimum: form.minimum || null, maximum: form.maximum || null },
    package: { url: "https://github.com/pending/package.zip", size: 1, sha256: "0".repeat(64) },
    custom_nodes: customNodes,
    models,
  };
  return {
    repository_url: form.repository_url,
    repository: { name: form.repository_name, author: form.author, description: form.repository_description },
    product: {
      id: form.id, name: form.name, category: form.category.trim(), summary: form.summary, description: form.description,
      tags: form.tags.split(",").map((item) => item.trim()).filter(Boolean), archived: false, versions: [version],
    },
    workflow: workflow.value,
    selected_loras: selectedLoras.value,
  };
}
async function validatePublish() {
  await withBusy("validate", async () => {
    if (!workflow.value) throw new Error(t.value("workflowUnavailable"));
    await post("/publisher/validate", payload());
    notice.value = locale.value === "zh" ? "校验通过，可以发布。" : "Validation passed. Ready to publish.";
  });
}
async function publishNow() {
  await withBusy("publish", async () => {
    if (!workflow.value) throw new Error(t.value("workflowUnavailable"));
    await post("/publisher/validate", payload());
    const result = await post<{ operation_id: string }>("/publisher/publish", payload());
    notice.value = `${t.value("activities")}: ${result.operation_id}`;
    drawer.value = true;
    await pollOperations();
  });
}
async function saveDraft() {
  await withBusy("draft", async () => {
    await post("/publisher/drafts", { name: form.name || workflowSourceName.value || "Untitled", payload: payload() });
    notice.value = locale.value === "zh" ? "草稿已保存。" : "Draft saved.";
    await load();
  });
}
async function loadDraft(draft: { payload: ReturnType<typeof payload> }) {
  const value = draft.payload;
  Object.assign(form, {
    repository_url: value.repository_url,
    repository_name: value.repository.name,
    author: value.repository.author,
    repository_description: value.repository.description,
    id: value.product.id,
    name: value.product.name,
    category: value.product.category || "",
    summary: value.product.summary,
    description: value.product.description,
    tags: value.product.tags.join(", "),
    version: value.product.versions[0].version,
    minimum: value.product.versions[0].comfyui.minimum || "",
    maximum: value.product.versions[0].comfyui.maximum || "",
    changelog: value.product.versions[0].changelog,
    custom_nodes: JSON.stringify(value.product.versions[0].custom_nodes, null, 2),
    models: JSON.stringify(value.product.versions[0].models, null, 2),
  });
  await applySelectedRepository();
  selectedCatalogProductId.value = publishCatalogProducts.value.some((item) => item.id === value.product.id)
    ? value.product.id
    : "";
  selectedLoras.value = value.selected_loras || [];
  void scanWorkflowAssets();
}
async function resumePending(tag: string) {
  await withBusy("resume", async () => {
    const result = await post<{ operation_id: string }>(`/publisher/pending/${encodeURIComponent(tag)}/resume`, {});
    notice.value = `${t.value("activities")}: ${result.operation_id}`;
    drawer.value = true;
    await pollOperations();
  });
}
async function archiveProduct(item: Product) {
  const next = !item.archived;
  const message = next ? "归档" : "取消归档";
  if (!confirm(locale.value === "zh" ? `确认${message}“${item.name}”？历史版本不会删除。` : `Confirm ${next ? "archive" : "unarchive"} “${item.name}”?`)) return;
  await withBusy("archive", async () => {
    await api(`/publisher/workflows/${item.source.owner}/${item.source.repo}/${item.id}`, {
      method: "PATCH", body: JSON.stringify({ archived: next }),
    });
    selected.value = null;
    await load();
  });
}
async function editProduct(item: Product) {
  const name = prompt(locale.value === "zh" ? "名称" : "Name", item.name);
  if (name === null) return;
  const category = prompt(locale.value === "zh" ? "类别（可留空）" : "Category (optional)", item.category || "");
  if (category === null) return;
  const summary = prompt(locale.value === "zh" ? "简介" : "Summary", item.summary);
  if (summary === null) return;
  const tags = prompt(locale.value === "zh" ? "标签（逗号分隔）" : "Tags (comma-separated)", item.tags.join(", "));
  if (tags === null) return;
  await withBusy("metadata", async () => {
    await api(`/publisher/workflows/${item.source.owner}/${item.source.repo}/${item.id}`, {
      method: "PATCH",
      body: JSON.stringify({ name, category: category.trim(), summary, tags: tags.split(",").map(value => value.trim()).filter(Boolean) }),
    });
    await load();
  });
}
async function startLogin() {
  await withBusy("login", async () => {
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
  error.value = result.error || "GitHub login failed";
}
async function logout() {
  await post("/github/logout", {});
  await load();
}
onMounted(async () => {
  document.addEventListener("keydown", handleWorkspaceShortcut);
  window.addEventListener("message", handleHubMessage);
  requestCurrentCanvasWorkflow();
  try { await load(); await pollOperations(); }
  catch (reason) { error.value = reason instanceof Error ? reason.message : String(reason); }
});
onBeforeUnmount(() => {
  document.removeEventListener("keydown", handleWorkspaceShortcut);
  window.removeEventListener("message", handleHubMessage);
  clearTimeout(operationTimer);
  clearTimeout(loginTimer);
  clearTimeout(copiedTimer);
});
</script>

<template>
  <div :class="['app-shell', `theme-${tab}`]">
    <aside class="nav-rail">
      <div class="brand">
        <span class="brand-mark"><LibraryBig :size="19" /></span>
        <span class="brand-copy"><strong>{{ t("title") }}</strong><small>v1.0.0</small></span>
      </div>

      <nav class="primary-nav" :aria-label="locale === 'zh' ? '主要导航' : 'Primary navigation'">
        <button :class="{ active: tab === 'subscribe' }" @click="tab = 'subscribe'">
          <Compass :size="18" /><span>{{ t("subscribe") }}</span>
        </button>
        <button :class="{ active: tab === 'publish' }" @click="tab = 'publish'">
          <UploadCloud :size="18" /><span>{{ t("publish") }}</span>
        </button>
      </nav>

      <div class="rail-spacer" />
      <div class="rail-actions">
        <button class="rail-action" :title="t('activities')" :aria-label="t('activities')" @click="drawer = !drawer">
          <ActivityIcon :size="17" /><span>{{ t("activities") }}</span>
          <i v-if="operations.some(o => o.status === 'running')" class="pulse" />
        </button>
        <button v-if="status?.github.authenticated" class="account-card" :title="t('logout')" :aria-label="t('logout')" @click="logout">
          <img v-if="status.github.user?.avatar_url" :src="status.github.user.avatar_url" alt="" />
          <CircleUserRound v-else :size="18" />
          <span><strong>{{ status.github.user?.login || t("signedIn") }}</strong><small>{{ t("logout") }}</small></span>
          <LogOut :size="15" />
        </button>
        <button v-else class="account-card" :title="t('login')" :aria-label="t('login')"
          :disabled="!status?.github.configured || !!busy" @click="startLogin">
          <GitBranch :size="18" /><span><strong>{{ t("login") }}</strong><small>{{ locale === "zh" ? "用于发布和管理" : "Publish and manage" }}</small></span>
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
        <div v-if="status && !status.manager.available" class="message warning">
          <TriangleAlert :size="18" /><span>{{ t("managerUnavailable") }}</span>
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
                <div class="segmented" role="group" :aria-label="locale === 'zh' ? '工作流筛选' : 'Workflow filters'"
                  :style="{ '--filter-index': String(filterIndex) }">
                  <button v-for="item in (['all','downloaded','updates','archived'] as const)" :key="item"
                    :class="{ active: filter === item }" @click="filter = item">{{ t(item) }}</button>
                </div>
                <button class="source-toggle" :class="{ active: sourceComposerOpen }" @click="sourceComposerOpen ? sourceComposerOpen = false : openSourceComposer()">
                  <FolderGit2 :size="16" /><span>{{ t("sourcesLabel") }}</span><i>{{ sources.length }}</i>
                </button>
              </div>
            </div>

            <div v-if="sourceComposerOpen" class="source-composer">
              <div class="source-form">
                <GitBranch :size="18" />
                <input ref="sourceInput" v-model="sourceUrl" :placeholder="t('sourcePlaceholder')" @keyup.enter="addSource" />
                <button class="primary" :disabled="!sourceUrl || !!busy" @click="addSource">
                  <Plus :size="17" />{{ t("add") }}
                </button>
              </div>
              <div v-if="sources.length" class="source-chips">
                <div v-for="item in sources" :key="item.url" class="source-chip" :class="{ invalid: item.error }" :title="item.error || item.url">
                  <AlertCircle v-if="item.error" :size="15" /><FolderGit2 v-else :size="15" />
                  <span>{{ item.owner }}/{{ item.repo }}</span>
                  <button :title="t('refresh')" :aria-label="t('refresh')" @click="refreshSource(item)"><RefreshCw :size="14" /></button>
                  <button :title="t('remove')" :aria-label="t('remove')" @click="removeSource(item)"><Trash2 :size="14" /></button>
                </div>
              </div>
            </div>

            <div v-if="visibleProducts.length" class="catalog">
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
                  <div class="tags"><span v-if="item.category" class="category-tag"><FolderOpen :size="11" />{{ item.category }}</span><span v-for="tag in item.tags" :key="tag">{{ tag }}</span></div>
                  <footer>
                    <a class="source-origin" :href="repositoryUrl(item)" target="_blank" rel="noopener"
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
                <span class="eyebrow">{{ locale === "zh" ? "等待 GitHub 授权" : "Waiting for GitHub authorization" }}</span>
                <h1>{{ locale === "zh" ? "两步完成登录" : "Complete sign-in in two steps" }}</h1>
                <p>{{ locale === "zh"
                  ? "先复制验证码，再打开 GitHub 授权页面。授权完成后这里会自动进入发布界面。"
                  : "Copy the code first, then open GitHub. This page continues automatically after authorization." }}</p>
                <ol class="device-steps">
                  <li>
                    <span>1</span>
                    <div><small>{{ locale === "zh" ? "复制验证码" : "Copy verification code" }}</small>
                      <button class="device-code" :aria-label="locale === 'zh' ? '复制验证码' : 'Copy verification code'" @click="copyDeviceCode">
                        <code>{{ device.user_code }}</code>
                        <span><Check v-if="deviceCodeCopied" :size="17" /><Copy v-else :size="17" />{{ deviceCodeCopied ? (locale === "zh" ? "已复制" : "Copied") : (locale === "zh" ? "复制" : "Copy") }}</span>
                      </button>
                    </div>
                  </li>
                  <li>
                    <span>2</span>
                    <div><small>{{ locale === "zh" ? "前往 GitHub 并粘贴验证码" : "Open GitHub and paste the code" }}</small>
                      <a class="primary device-open-link" :href="device.verification_uri" target="_blank" rel="noopener">
                        {{ locale === "zh" ? "打开 GitHub 授权页面" : "Open GitHub authorization" }}<ExternalLink :size="16" />
                      </a>
                    </div>
                  </li>
                </ol>
                <span class="device-waiting"><i />{{ locale === "zh" ? "正在等待授权结果，无需刷新页面" : "Waiting for authorization — no refresh needed" }}</span>
              </div>
              <div v-else>
                <span class="eyebrow">{{ locale === "zh" ? "GitHub 授权" : "GitHub authorization" }}</span>
                <h1>{{ locale === "zh" ? "登录后发布工作流" : "Sign in to publish workflows" }}</h1>
                <p>{{ status?.github.configured
                  ? (locale === "zh"
                    ? "发布会创建 GitHub Release 并更新工作流目录。登录前不会读取仓库，也不会展示发布表单。"
                    : "Publishing creates a GitHub Release and updates the workflow catalog. Repositories and the publish form stay unavailable until you sign in.")
                  : t("githubNotConfigured") }}</p>
              </div>
              <button v-if="!device" class="primary auth-gate-action" :disabled="!status?.github.configured || !!busy" @click="startLogin">
                <GitBranch :size="17" />{{ t("login") }}<ArrowRight :size="16" />
              </button>
            </div>

            <template v-else>
              <div v-if="drafts.length || pendingPublications.length" class="publish-utilities">
                <details v-if="drafts.length"><summary>{{ locale === "zh" ? "草稿" : "Drafts" }}</summary>
                  <button v-for="draft in drafts" :key="draft.id" class="ghost" @click="loadDraft(draft)">{{ draft.name }}</button>
                </details>
                <details v-if="pendingPublications.length"><summary>{{ locale === "zh" ? "待同步发布" : "Pending publications" }}</summary>
                  <button v-for="item in pendingPublications" :key="item.tag" class="ghost" @click="resumePending(item.tag)">{{ item.tag }}</button>
                </details>
              </div>

              <section class="panel publish-console-shell">
                <header class="publish-context-bar" :class="{ unavailable: !workflow }">
                  <span class="upload-icon"><FileJson :size="20" /></span>
                  <span class="current-workflow-copy">
                    <small>{{ locale === "zh" ? "即将发布" : "Publishing" }}</small>
                    <strong>{{ workflowSourceName || (locale === "zh" ? "正在读取当前画布…" : "Reading current canvas…") }}</strong>
                    <em v-if="canvasWorkflowError">{{ canvasWorkflowError }}</em>
                  </span>
                  <div class="publish-context-stats">
                    <span><PackageOpen :size="14" />{{ customNodeCount }}</span>
                    <span><FileUp :size="14" />{{ imageReferences.length }}</span>
                    <span><TriangleAlert :size="14" />{{ loraReferences.length }}</span>
                  </div>
                </header>

                <div class="publish-console">
                  <section class="publish-editor">
                    <div class="publish-section-title">
                      <span><GitBranch :size="16" /></span>
                      <div><strong>{{ locale === "zh" ? "发布位置" : "Destination" }}</strong><small>{{ locale === "zh" ? "仓库选择会自动记住" : "Repository choice is remembered" }}</small></div>
                      <button class="ghost compact-action" @click="createRepositoryOpen = !createRepositoryOpen">
                        <Plus :size="14" />{{ locale === "zh" ? "新建仓库" : "New repository" }}
                      </button>
                    </div>
                    <label class="compact-field">
                      <select v-model="form.repository_url" :disabled="!repositories.length" @change="applySelectedRepository">
                        <option value="">{{ repositories.length ? (locale === "zh" ? "请选择 GitHub 仓库" : "Choose a GitHub repository") : (locale === "zh" ? "没有已授权的仓库" : "No authorized repositories") }}</option>
                        <option v-for="repo in repositories" :key="repo.full_name" :value="`https://github.com/${repo.full_name}`">{{ repo.full_name }}</option>
                      </select>
                    </label>
                    <div v-if="createRepositoryOpen" class="inline create-repo">
                      <input v-model="createRepositoryName" :placeholder="locale === 'zh' ? '仓库名称' : 'Repository name'" @keyup.enter="createRepository" />
                      <button class="secondary" :disabled="!createRepositoryName" @click="createRepository"><Plus :size="16" />{{ locale === "zh" ? "创建" : "Create" }}</button>
                    </div>

                    <div class="publish-divider" />

                    <div class="publish-section-title">
                      <span><FileJson :size="16" /></span>
                      <div><strong>{{ locale === "zh" ? "版本信息" : "Release information" }}</strong><small>{{ locale === "zh" ? "只填写发布真正需要的内容" : "Only the essentials" }}</small></div>
                    </div>
                    <label v-if="publishCatalogProducts.length" class="compact-field">
                      <span>{{ locale === "zh" ? "发布方式" : "Publish as" }}</span>
                      <select v-model="selectedCatalogProductId" @change="applySelectedCatalogProduct">
                        <option value="">{{ locale === "zh" ? "新建工作流" : "New workflow" }}</option>
                        <option v-for="item in publishCatalogProducts" :key="item.id" :value="item.id">{{ item.category ? `${item.category} / ` : "" }}{{ item.name }}</option>
                      </select>
                    </label>
                    <div class="two">
                      <label class="compact-field"><span>{{ locale === "zh" ? "类别" : "Category" }}<em>{{ locale === "zh" ? "可选" : "Optional" }}</em></span>
                        <input v-model="form.category" list="workflow-category-options" maxlength="80" :placeholder="locale === 'zh' ? '选择或输入新类别' : 'Choose or create'" />
                        <datalist id="workflow-category-options"><option v-for="category in repositoryCategories" :key="category" :value="category" /></datalist>
                      </label>
                      <label class="compact-field"><span>{{ t("name") }}</span><input v-model="form.name" maxlength="120" /></label>
                    </div>
                    <p v-if="generatedProductConflict" class="message warning"><TriangleAlert :size="16" /><span>{{ locale === "zh" ? `“${generatedProductConflict.name}”已存在，请选择已有工作流。` : `“${generatedProductConflict.name}” already exists. Select the existing workflow.` }}</span></p>
                    <div class="two">
                      <label class="compact-field"><span>{{ t("version") }}</span><input v-model="form.version" placeholder="1.0" /></label>
                      <label class="publish-id-preview compact-field"><span>{{ locale === "zh" ? "发布标识" : "Publish ID" }}<em>{{ locale === "zh" ? "自动生成" : "Automatic" }}</em></span>
                        <strong>{{ form.id || generatedWorkflowId(form.name || (locale === "zh" ? "未命名工作流" : "Untitled workflow")) }}</strong>
                      </label>
                    </div>
                    <p v-if="selectedCatalogProduct" class="field-note">{{ locale === "zh" ? `已有版本 ${selectedCatalogProduct.versions.join("、") || "无"}` : `Published ${selectedCatalogProduct.versions.join(", ") || "none"}` }}</p>
                    <p v-if="existingVersionConflict" class="message warning"><TriangleAlert :size="16" /><span>{{ locale === "zh" ? "这个版本已经发布，请填写新的版本号。" : "This version is already published." }}</span></p>
                    <label class="compact-field release-notes-field"><span>{{ t("releaseNotes") }}</span><textarea v-model="form.changelog" rows="5" /></label>

                    <details class="advanced-models publish-advanced">
                      <summary>{{ locale === "zh" ? "兼容性与其他模型" : "Compatibility and other models" }}</summary>
                      <div class="two">
                        <label>{{ t("minComfy") }}<input v-model="form.minimum" /></label>
                        <label>{{ t("maxComfy") }}<input v-model="form.maximum" /></label>
                      </div>
                      <label>{{ locale === "zh" ? "其他模型资源声明" : "Other model declarations" }}<textarea v-model="form.models" class="code" rows="7" /></label>
                    </details>
                  </section>

                  <aside class="publish-resource-inspector">
                    <div class="publish-section-title resource-title">
                      <span><ListFilter :size="16" /></span>
                      <div><strong>{{ locale === "zh" ? "资源检查" : "Resource check" }}</strong><small>{{ locale === "zh" ? "来自当前画布的自动扫描结果" : "Automatically scanned from the canvas" }}</small></div>
                    </div>
                    <div class="publish-resource-tabs">
                      <button :class="{ active: publisherAssetTab === 'nodes' }" @click="publisherAssetTab = 'nodes'">
                        <PackageOpen :size="16" /><span><strong>{{ customNodeCount }}</strong><small>{{ locale === "zh" ? "节点" : "Nodes" }}</small></span>
                      </button>
                      <button :class="{ active: publisherAssetTab === 'images' }" @click="publisherAssetTab = 'images'">
                        <FileUp :size="16" /><span><strong>{{ imageReferences.length }}</strong><small>{{ locale === "zh" ? "图片" : "Images" }}</small></span>
                      </button>
                      <button :class="{ active: publisherAssetTab === 'loras' }" @click="publisherAssetTab = 'loras'">
                        <TriangleAlert :size="16" /><span><strong>{{ loraReferences.length }}</strong><small>LoRA</small></span>
                      </button>
                    </div>

                    <div class="publish-resource-content">
                      <template v-if="publisherAssetTab === 'nodes'">
                        <div class="resource-content-heading"><strong>{{ locale === "zh" ? "所需自定义节点" : "Required custom nodes" }}</strong><small>{{ dependencyScanError || (locale === "zh" ? "发布时不会安装" : "Nothing is installed while publishing") }}</small></div>
                        <div v-for="item in customNodeDependencies" :key="item.registry_id || item.name" class="publish-resource-row">
                          <span class="resource-row-icon"><PackageOpen :size="15" /></span>
                          <span><strong>{{ item.name }}</strong><small>{{ item.registry_id || (locale === "zh" ? "未匹配 Registry" : "Not matched in Registry") }}</small></span>
                          <em>{{ item.version || (item.manual ? (locale === "zh" ? "手动" : "Manual") : (locale === "zh" ? "任意版本" : "Any")) }}</em>
                        </div>
                        <div v-if="!dependencyScanError && !customNodeDependencies.length" class="publish-resource-empty"><CheckCircle2 :size="18" /><span><strong>{{ locale === "zh" ? "没有额外节点" : "No extra nodes" }}</strong><small>{{ locale === "zh" ? "当前环境可直接使用" : "Ready for the current environment" }}</small></span></div>
                      </template>

                      <template v-else-if="publisherAssetTab === 'images'">
                        <div class="resource-content-heading"><strong>{{ locale === "zh" ? "随包图片" : "Included images" }}</strong><small>{{ locale === "zh" ? "下载工作流时自动安装" : "Installed with the workflow" }}</small></div>
                        <div v-for="item in imageReferences" :key="item.name" class="publish-resource-row" :class="{ invalid: item.status !== 'ready' }">
                          <span class="resource-row-icon"><FileUp :size="15" /></span>
                          <span><strong>{{ item.name }}</strong><small>{{ item.node_ids.length }} {{ locale === "zh" ? "个节点引用" : "references" }}</small></span>
                          <em>{{ item.status === "ready" && item.size != null ? humanBytes(item.size) : item.status }}</em>
                        </div>
                        <div v-if="!imageReferences.length" class="publish-resource-empty"><CheckCircle2 :size="18" /><span><strong>{{ locale === "zh" ? "没有随包图片" : "No included images" }}</strong><small>{{ locale === "zh" ? "工作流不会额外携带图片" : "No images will be bundled" }}</small></span></div>
                      </template>

                      <template v-else>
                        <div class="resource-content-heading">
                          <span><strong>{{ locale === "zh" ? "可选 LoRA" : "Optional LoRAs" }}</strong><small>{{ locale === "zh" ? "默认不发布，按需勾选" : "Excluded by default; select as needed" }}</small></span>
                          <button v-if="loraReferences.length" class="ghost danger-action compact-action" :disabled="!!busy" @click="clearWorkflowLoras"><Trash2 :size="14" />{{ locale === "zh" ? "清空引用" : "Clear" }}</button>
                        </div>
                        <label v-for="item in loraReferences" :key="item.name" class="publish-resource-row selectable" :class="{ invalid: item.status !== 'ready', selected: selectedLoras.includes(item.name) }">
                          <input type="checkbox" :checked="selectedLoras.includes(item.name)" :disabled="item.status !== 'ready'" @change="toggleLora(item.name, ($event.target as HTMLInputElement).checked)" />
                          <span><strong>{{ item.name }}</strong><small>{{ item.filename }}</small></span>
                          <em>{{ item.status === "ready" && item.size != null ? humanBytes(item.size) : item.status }}</em>
                        </label>
                        <div v-if="!loraReferences.length" class="publish-resource-empty"><CheckCircle2 :size="18" /><span><strong>{{ locale === "zh" ? "没有 LoRA 引用" : "No LoRA references" }}</strong><small>{{ locale === "zh" ? "无需额外处理" : "Nothing else to review" }}</small></span></div>
                      </template>
                    </div>
                  </aside>
                </div>

                <footer class="publish-action-bar">
                  <span><CheckCircle2 v-if="canFinalizePublish" :size="16" /><AlertCircle v-else :size="16" />{{ canFinalizePublish ? (locale === "zh" ? "发布信息已完整" : "Ready to publish") : (locale === "zh" ? "请补全名称、版本和更新日志" : "Complete the required release information") }}</span>
                  <button class="ghost" :disabled="!!busy || !canFinalizePublish" @click="saveDraft">{{ locale === "zh" ? "保存草稿" : "Save draft" }}</button>
                  <button class="secondary" :disabled="!!busy || !canFinalizePublish" @click="validatePublish"><ShieldCheck :size="16" />{{ t("validate") }}</button>
                  <button class="primary" :disabled="!!busy || !canFinalizePublish || !status?.github.authenticated" @click="publishNow"><UploadCloud :size="16" />{{ t("publishNow") }}</button>
                </footer>
              </section>
            </template>
          </div>
        </Transition>
      </main>
    </section>

    <div v-if="selected" class="backdrop" @click.self="selected = null">
      <aside class="detail">
        <button class="icon-button close" :title="t('close')" :aria-label="t('close')" @click="selected = null"><X :size="18" /></button>
        <header class="detail-hero">
          <div v-if="productCover(selected)" class="detail-cover">
            <img :src="productCover(selected)?.url" :alt="selected.name" />
          </div>
          <div v-else class="detail-cover detail-cover-placeholder"><LibraryBig :size="30" /></div>
          <div class="detail-identity">
            <a class="eyebrow repository-link" :href="repositoryUrl(selected)" target="_blank" rel="noopener"
              :title="t('repositoryPage')">
              <GitBranch :size="13" />{{ selected.source.owner }}/{{ selected.source.repo }}<ExternalLink :size="11" />
            </a>
            <h1>{{ selected.name }}</h1>
            <p>{{ selected.summary || selected.description || (locale === "zh" ? "暂无工作流说明" : "No workflow description") }}</p>
            <div class="tags"><span v-if="selected.category" class="category-tag"><FolderOpen :size="11" />{{ selected.category }}</span><span v-for="tag in selected.tags" :key="tag">{{ tag }}</span></div>
          </div>
          <div v-if="status?.github.authenticated" class="manage-actions">
            <button class="secondary" @click="editProduct(selected)">{{ locale === "zh" ? "编辑资料" : "Edit" }}</button>
            <button class="ghost danger-action" @click="archiveProduct(selected)"><ArchiveIcon :size="15" />{{ selected.archived ? (locale === "zh" ? "取消归档" : "Unarchive") : (locale === "zh" ? "归档" : "Archive") }}</button>
          </div>
        </header>

        <div class="detail-workbench">
          <nav class="version-rail" :aria-label="t('versions')">
            <div class="version-rail-heading"><span>{{ t("versions") }}</span><em>{{ selected.versions.length }}</em></div>
            <button v-for="version in detailVersions" :key="version.version"
              :class="{ active: activeDetailVersion?.version === version.version }"
              @click="selectedDetailVersion = version.version">
              <span><strong>v{{ version.version }}</strong><small>{{ new Date(version.published_at).toLocaleDateString() }}</small></span>
              <CheckCircle2 v-if="selected.downloaded_versions.includes(version.version)" :size="15" />
              <DownloadIcon v-else :size="15" />
            </button>
          </nav>

          <article v-if="activeDetailVersion" class="release release-focused">
            <div class="release-overview">
              <div>
                <span class="eyebrow">{{ locale === "zh" ? "当前版本" : "Selected version" }}</span>
                <div class="release-head"><strong>v{{ activeDetailVersion.version }}</strong><span>{{ humanBytes(activeDetailVersion.package.size) }}</span></div>
                <p class="compatibility">ComfyUI {{ activeDetailVersion.comfyui.minimum || "—" }} – {{ activeDetailVersion.comfyui.maximum || "∞" }}</p>
              </div>
              <a class="release-link" :href="releaseUrl(selected, activeDetailVersion)" target="_blank" rel="noopener">
                {{ t("releasePage") }}<ExternalLink :size="14" />
              </a>
            </div>

            <div class="version-actions" :class="{ 'downloaded-actions': selected.downloaded_versions.includes(activeDetailVersion.version) }">
              <button v-if="!selected.downloaded_versions.includes(activeDetailVersion.version)" class="primary wide" :disabled="!!busy" @click="download(selected, activeDetailVersion)"><DownloadIcon :size="17" />{{ t("download") }}</button>
              <template v-else>
                <button class="secondary wide" :disabled="!!busy" @click="revealLocalVersion(selected, activeDetailVersion)"><FolderOpen :size="17" />{{ t("revealLocal") }}</button>
                <button class="ghost wide danger-action" :disabled="!!busy" @click="deleteLocalVersion(selected, activeDetailVersion)"><Trash2 :size="16" />{{ t("deleteLocal") }}</button>
              </template>
              <button v-if="activeDetailVersion.custom_nodes.length" class="secondary wide dependency-action" :disabled="!!busy" @click="planDependencies(selected, activeDetailVersion)"><ListFilter :size="17" />{{ locale === "zh" ? "检查节点依赖" : "Check node dependencies" }}</button>
            </div>

            <section class="release-note">
              <span>{{ t("changelog") }}</span>
              <p class="changelog">{{ activeDetailVersion.changelog }}</p>
            </section>

            <div class="resource-metrics">
              <div><PackageOpen :size="17" /><span><strong>{{ activeDetailVersion.custom_nodes.length }}</strong><small>{{ locale === "zh" ? "自定义节点" : "Custom nodes" }}</small></span></div>
              <div><FileUp :size="17" /><span><strong>{{ activeDetailVersion.inputs?.length || 0 }}</strong><small>{{ locale === "zh" ? "随包图片" : "Included images" }}</small></span></div>
              <div><TriangleAlert :size="17" /><span><strong>{{ loraAssets(activeDetailVersion).length }}</strong><small>LoRA</small></span></div>
            </div>

            <div v-if="activeDetailVersion.custom_nodes.length || activeDetailVersion.inputs?.length || loraAssets(activeDetailVersion).length" class="resource-groups">
              <section v-if="activeDetailVersion.custom_nodes.length" class="resource-group">
                <div class="resource-group-heading"><PackageOpen :size="16" /><strong>{{ locale === "zh" ? "所需自定义节点" : "Required custom nodes" }}</strong></div>
                <div v-for="node in activeDetailVersion.custom_nodes" :key="node.registry_id || node.name" class="asset-row dependency-asset-row">
                  <span><PackageOpen :size="15" /><strong>{{ node.name }}</strong><small>{{ node.registry_id || (locale === "zh" ? "未匹配到 Comfy Registry" : "Not matched in Comfy Registry") }}</small></span>
                  <em>{{ node.version || (node.manual ? (locale === "zh" ? "需手动安装" : "Manual") : (locale === "zh" ? "任意版本" : "Any version")) }}</em>
                </div>
              </section>
              <section v-if="activeDetailVersion.inputs?.length" class="resource-group">
                <div class="resource-group-heading"><FileUp :size="16" /><strong>{{ locale === "zh" ? "随包图片" : "Included images" }}</strong></div>
                <div v-for="input in activeDetailVersion.inputs" :key="input.archive" class="asset-row">
                  <span><FileUp :size="15" /><strong>{{ input.source }}</strong><small>{{ input.node_ids.length }} {{ locale === "zh" ? "个节点引用" : "references" }}</small></span>
                  <em>{{ humanBytes(input.size) }}</em>
                </div>
              </section>
              <section v-if="loraAssets(activeDetailVersion).length" class="resource-group">
                <div class="resource-group-heading"><TriangleAlert :size="16" /><strong>{{ locale === "zh" ? "可选 LoRA" : "Optional LoRAs" }}</strong><small>{{ locale === "zh" ? "按需下载" : "Download individually" }}</small></div>
                <div v-for="model in loraAssets(activeDetailVersion)" :key="`${model.type}:${model.filename}`" class="model-asset">
                  <span><strong>{{ model.name }}</strong><small>{{ model.filename }}</small></span>
                  <button class="secondary" :disabled="!!busy" @click="downloadLora(selected, activeDetailVersion, model)"><DownloadIcon :size="15" />{{ t("download") }}</button>
                </div>
              </section>
            </div>

            <details v-if="otherModelAssets(activeDetailVersion).length" class="model-assets"><summary>{{ t("models") }} ({{ otherModelAssets(activeDetailVersion).length }})</summary>
              <div v-for="model in otherModelAssets(activeDetailVersion)" :key="`${model.type}:${model.filename}`" class="model-asset">
                <span><strong>{{ model.name }}</strong><small>{{ model.type }} · {{ model.filename }}</small></span>
                <a :href="model.source_url" target="_blank" rel="noopener"><ExternalLink :size="14" /></a>
              </div>
            </details>

          <div v-if="dependencyPlans[dependencyKey(selected, activeDetailVersion)]" class="dependency-plan">
            <div v-if="!status?.manager.available || !status?.manager.compatible" class="message warning"><TriangleAlert :size="17" /><span>{{ t("managerUnavailable") }}</span></div>
            <label v-for="(entry, index) in dependencyPlans[dependencyKey(selected, activeDetailVersion)]" :key="dependencyActionKey(entry, index)" class="dependency-row">
              <input v-if="['install','upgrade','newer'].includes(entry.action)" type="checkbox"
                :checked="selectedDependencyActions[dependencyKey(selected, activeDetailVersion)]?.includes(dependencyActionKey(entry, index))"
                :disabled="!status?.manager.available || !status?.manager.compatible"
                @change="toggleDependencyAction(dependencyKey(selected, activeDetailVersion), dependencyActionKey(entry, index), ($event.target as HTMLInputElement).checked)" />
              <span><strong>{{ entry.name }}</strong><small>{{ entry.installed || "—" }} → {{ entry.requested || "latest" }} · {{ entry.action }}<template v-if="entry.warning"> · {{ entry.warning }}</template></small></span>
            </label>
            <label class="confirm-row"><input v-model="dependencyConfirmed[dependencyKey(selected, activeDetailVersion)]" type="checkbox" />{{ t("confirmEnvironment") }}</label>
            <button class="primary wide"
              :disabled="!dependencyConfirmed[dependencyKey(selected, activeDetailVersion)] || !selectedDependencyActions[dependencyKey(selected, activeDetailVersion)]?.length || !status?.manager.available || !status?.manager.compatible || !!busy"
              @click="executeDependencyPlan(selected, activeDetailVersion)">{{ t("execute") }}</button>
          </div>
        </article>
        </div>
      </aside>
    </div>

    <aside v-if="drawer" class="activity-drawer">
      <div class="drawer-head"><div><span class="section-icon"><ActivityIcon :size="18" /></span><h2>{{ t("activities") }}</h2></div><button class="icon-button" :title="t('close')" :aria-label="t('close')" @click="drawer = false"><X :size="18" /></button></div>
      <div v-if="!operations.length" class="empty small"><ActivityIcon :size="25" /><span>{{ t("noActivities") }}</span></div>
      <article v-for="item in operations" :key="item.id" class="operation">
        <div><strong>{{ item.kind }}</strong><span :class="`status ${item.status}`">{{ item.stage }}</span></div>
        <template v-if="item.status === 'running' && item.progress?.total">
          <div class="operation-progress" role="progressbar" aria-valuemin="0" aria-valuemax="100"
            :aria-valuenow="Math.round(progressPercent(item.progress))">
            <i :style="{ width: `${progressPercent(item.progress)}%` }" />
          </div>
          <small class="progress-copy">{{ humanBytes(item.progress.received) }} / {{ humanBytes(item.progress.total) }}</small>
        </template>
        <pre v-if="item.logs.length">{{ item.logs.join("\n") }}</pre>
      </article>
    </aside>

  </div>
</template>
