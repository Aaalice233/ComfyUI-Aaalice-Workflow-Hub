<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from "vue";
import {
  Activity as ActivityIcon,
  AlertCircle,
  Archive as ArchiveIcon,
  ArrowRight,
  Check,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  CircleUserRound,
  Compass,
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
type Version = {
  version: string; published_at: string; release_tag: string; changelog: string;
  comfyui: { minimum?: string | null; maximum?: string | null };
  package: { url: string; size: number; sha256: string };
  preview?: { url: string; sha256: string } | null;
  custom_nodes: Record<string, unknown>[]; models: Record<string, unknown>[];
};
type Product = {
  id: string; name: string; summary: string; description: string; tags: string[]; archived: boolean;
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

const tab = ref<"subscribe" | "publish">("subscribe");
const status = ref<Status | null>(null);
const sources = ref<Source[]>([]);
const products = ref<Product[]>([]);
const selected = ref<Product | null>(null);
const expandedChangelog = ref<string | null>(null);
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
const repositories = ref<{ full_name: string }[]>([]);
const createRepositoryName = ref("");
const drafts = ref<{ id: string; name: string; payload: ReturnType<typeof payload> }[]>([]);
const pendingPublications = ref<{ tag: string }[]>([]);
const workflow = ref<Record<string, unknown> | null>(null);
const workflowSourceName = ref("");
const publishStep = ref(1);
const furthestPublishStep = ref(1);
const preview = ref<{ filename: string; data_base64: string } | null>(null);
const device = ref<{ user_code: string; verification_uri: string; interval: number } | null>(null);
const dependencyPlans = reactive<Record<string, DependencyPlan[]>>({});
const selectedDependencyActions = reactive<Record<string, string[]>>({});
const dependencyConfirmed = reactive<Record<string, boolean>>({});
let operationTimer = 0;
let loginTimer = 0;

const form = reactive({
  repository_url: "",
  repository_name: "",
  author: "",
  repository_description: "",
  id: "",
  name: "",
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
    return [item.name, item.summary, item.description, ...item.tags].join(" ").toLocaleLowerCase().includes(query);
  });
});
const filterIndex = computed(() => (["all", "downloaded", "updates", "archived"] as const).indexOf(filter.value));
const canAdvancePublish = computed(() => {
  if (publishStep.value === 1) return !!workflow.value;
  if (publishStep.value === 2) {
    return !!form.repository_url.trim() && !!form.repository_name.trim() && !!form.author.trim();
  }
  if (publishStep.value === 3) return !!form.id.trim() && !!form.name.trim() && !!form.summary.trim();
  return true;
});
const canFinalizePublish = computed(() => {
  if (!workflow.value || !/^(0|[1-9]\d*)\.(0|[1-9]\d*)(?:\.(0|[1-9]\d*))?$/.test(form.version.trim()) || !form.changelog.trim()) {
    return false;
  }
  try {
    return Array.isArray(JSON.parse(form.custom_nodes)) && Array.isArray(JSON.parse(form.models));
  } catch {
    return false;
  }
});
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
function repositoryUrl(item: Product) {
  return `https://github.com/${encodeURIComponent(item.source.owner)}/${encodeURIComponent(item.source.repo)}`;
}
function releaseUrl(item: Product, version: Version) {
  return `${repositoryUrl(item)}/releases/tag/${encodeURIComponent(version.release_tag)}`;
}
function openDetails(item: Product) {
  selected.value = item;
  expandedChangelog.value = null;
}
function toggleChangelog(item: Product, version: Version) {
  const key = dependencyKey(item, version);
  expandedChangelog.value = expandedChangelog.value === key ? null : key;
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
      api<{ items: { full_name: string }[] }>("/github/repositories"),
      api<{ items: typeof drafts.value }>("/publisher/drafts"),
      api<{ items: { tag: string }[] }>("/publisher/pending"),
    ]);
    repositories.value = repos.items;
    drafts.value = savedDrafts.items;
    pendingPublications.value = pending.items;
  } else {
    repositories.value = [];
  }
  if (selected.value) selected.value = products.value.find((item) => item.id === selected.value?.id) || null;
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
async function readWorkflowFile(file: File) {
  if (!file.name.toLocaleLowerCase().endsWith(".json") || file.size > 10 * 1024 * 1024) {
    error.value = locale.value === "zh" ? "请选择不超过 10 MiB 的 JSON 工作流文件。" : "Choose a JSON workflow file no larger than 10 MiB.";
    return;
  }
  await withBusy("workflow-file", async () => {
    const parsed = JSON.parse(await file.text()) as unknown;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      throw new Error(locale.value === "zh" ? "工作流文件内容不是有效的 JSON 对象。" : "The workflow file is not a valid JSON object.");
    }
    workflow.value = parsed as Record<string, unknown>;
    workflowSourceName.value = file.name;
    if (!form.name) form.name = file.name.replace(/\.json$/i, "");
    furthestPublishStep.value = Math.max(furthestPublishStep.value, 2);
  });
}
async function chooseWorkflowFile(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (file) await readWorkflowFile(file);
  input.value = "";
}
async function dropWorkflowFile(event: DragEvent) {
  const file = event.dataTransfer?.files?.[0];
  if (file) await readWorkflowFile(file);
}
function goToPublishStep(step: number) {
  if (step < 1 || step > 4 || step > furthestPublishStep.value) return;
  publishStep.value = step;
}
function nextPublishStep() {
  if (!canAdvancePublish.value || publishStep.value >= 4) return;
  const next = publishStep.value + 1;
  furthestPublishStep.value = Math.max(furthestPublishStep.value, next);
  publishStep.value = next;
}
function previousPublishStep() {
  if (publishStep.value > 1) publishStep.value -= 1;
}
async function scanDependencies() {
  await withBusy("scan", async () => {
    if (!workflow.value) throw new Error(t.value("workflowUnavailable"));
    const result = await post<{ items: Record<string, unknown>[] }>("/publisher/scan-dependencies", { workflow: workflow.value });
    form.custom_nodes = JSON.stringify(result.items, null, 2);
    notice.value = locale.value === "zh" ? `已扫描 ${result.items.length} 个节点依赖，请人工复核。` : `Found ${result.items.length} node dependencies. Review before publishing.`;
  });
}
async function choosePreview(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0];
  if (!file) {
    preview.value = null;
    return;
  }
  if (!["image/png", "image/webp"].includes(file.type) || file.size > 1024 * 1024) {
    error.value = locale.value === "zh" ? "预览图必须是小于 1 MiB 的 PNG 或 WebP。" : "Preview must be a PNG or WebP under 1 MiB.";
    (event.target as HTMLInputElement).value = "";
    return;
  }
  const dataUrl = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
  preview.value = { filename: file.name, data_base64: dataUrl.split(",", 2)[1] };
}
async function createRepository() {
  await withBusy("create-repository", async () => {
    const result = await post<{ full_name: string; html_url: string }>("/github/repositories", {
      name: createRepositoryName.value, description: form.repository_description,
    });
    form.repository_url = result.html_url;
    createRepositoryName.value = "";
    await load();
    notice.value = locale.value === "zh"
      ? "仓库已创建。请在 GitHub App 设置中授权该仓库，然后重新加载本页。"
      : "Repository created. Authorize it in the GitHub App installation, then reload this page.";
  });
}
function payload() {
  const customNodes = JSON.parse(form.custom_nodes);
  const models = JSON.parse(form.models);
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
      id: form.id, name: form.name, summary: form.summary, description: form.description,
      tags: form.tags.split(",").map((item) => item.trim()).filter(Boolean), archived: false, versions: [version],
    },
    workflow: workflow.value,
    preview: preview.value,
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
function loadDraft(draft: { payload: ReturnType<typeof payload> }) {
  const value = draft.payload;
  Object.assign(form, {
    repository_url: value.repository_url,
    repository_name: value.repository.name,
    author: value.repository.author,
    repository_description: value.repository.description,
    id: value.product.id,
    name: value.product.name,
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
  workflow.value = value.workflow;
  preview.value = value.preview;
  workflowSourceName.value = value.product.name;
  publishStep.value = 2;
  furthestPublishStep.value = 4;
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
  const summary = prompt(locale.value === "zh" ? "简介" : "Summary", item.summary);
  if (summary === null) return;
  const tags = prompt(locale.value === "zh" ? "标签（逗号分隔）" : "Tags (comma-separated)", item.tags.join(", "));
  if (tags === null) return;
  await withBusy("metadata", async () => {
    await api(`/publisher/workflows/${item.source.owner}/${item.source.repo}/${item.id}`, {
      method: "PATCH",
      body: JSON.stringify({ name, summary, tags: tags.split(",").map(value => value.trim()).filter(Boolean) }),
    });
    await load();
  });
}
async function startLogin() {
  await withBusy("login", async () => {
    const started = await post<{ user_code: string; verification_uri: string; interval: number }>("/github/device/start", {});
    device.value = started;
    window.open(started.verification_uri, "_blank", "noopener");
    pollLogin();
  });
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
  try { await load(); await pollOperations(); }
  catch (reason) { error.value = reason instanceof Error ? reason.message : String(reason); }
});
onBeforeUnmount(() => {
  document.removeEventListener("keydown", handleWorkspaceShortcut);
  clearTimeout(operationTimer);
  clearTimeout(loginTimer);
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
        <div v-if="device" class="device">
          <div><GitBranch :size="18" /><strong>GitHub Device Flow</strong></div>
          <code>{{ device.user_code }}</code>
          <a :href="device.verification_uri" target="_blank" rel="noopener">{{ device.verification_uri }}<ExternalLink :size="14" /></a>
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
                  <img v-if="latest(item)?.preview" class="card-preview" :src="latest(item)?.preview?.url" :alt="item.name" loading="lazy" />
                  <div v-else class="preview-placeholder"><LibraryBig :size="28" /></div>
                  <span class="version-pill">v{{ latest(item)?.version }}</span>
                </div>
                <div class="card-body">
                  <div class="card-heading"><h2>{{ item.name }}</h2><ArrowRight :size="17" /></div>
                  <p>{{ item.summary }}</p>
                  <div class="tags"><span v-for="tag in item.tags" :key="tag">{{ tag }}</span></div>
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
            <div v-if="drafts.length || pendingPublications.length" class="publish-utilities">
              <details v-if="drafts.length"><summary>{{ locale === "zh" ? "草稿" : "Drafts" }}</summary>
                <button v-for="draft in drafts" :key="draft.id" class="ghost" @click="loadDraft(draft)">{{ draft.name }}</button>
              </details>
              <details v-if="pendingPublications.length"><summary>{{ locale === "zh" ? "待同步发布" : "Pending publications" }}</summary>
                <button v-for="item in pendingPublications" :key="item.tag" class="ghost" @click="resumePending(item.tag)">{{ item.tag }}</button>
              </details>
            </div>

            <section class="panel publish-wizard">
              <ol class="wizard-steps">
                <li v-for="(label, index) in [t('source'), t('repository'), t('workflowInfo'), t('version')]" :key="label">
                  <button
                    :class="{ active: publishStep === index + 1, complete: furthestPublishStep > index + 1 }"
                    :disabled="furthestPublishStep < index + 1"
                    @click="goToPublishStep(index + 1)"
                  >
                    <span><Check v-if="furthestPublishStep > index + 1" :size="14" /><template v-else>{{ index + 1 }}</template></span>
                    <strong>{{ label }}</strong>
                  </button>
                </li>
              </ol>

              <div class="wizard-content">
                <div v-if="publishStep === 1" class="wizard-page source-step">
                  <label class="workflow-dropzone" @dragover.prevent @drop.prevent="dropWorkflowFile">
                    <span class="upload-icon"><FileJson :size="30" /></span>
                    <strong>{{ locale === "zh" ? "选择工作流文件" : "Choose a workflow file" }}</strong>
                    <small>{{ locale === "zh" ? "点击选择或拖入 JSON，最大 10 MiB" : "Click or drop a JSON file, up to 10 MiB" }}</small>
                    <input class="file-input" type="file" accept="application/json,.json" @change="chooseWorkflowFile" />
                  </label>
                  <div v-if="workflow" class="selected-file">
                    <div><FileJson :size="18" /><span><strong>{{ workflowSourceName }}</strong><small>{{ locale === "zh" ? "文件已读取" : "File loaded" }}</small></span></div>
                    <button class="secondary" :disabled="!!busy" @click="scanDependencies">
                      <ListFilter :size="16" />{{ locale === "zh" ? "扫描节点依赖" : "Scan dependencies" }}
                    </button>
                  </div>
                </div>

                <div v-else-if="publishStep === 2" class="wizard-page">
                <label>{{ t("repository") }}
                  <select v-if="repositories.length" v-model="form.repository_url">
                    <option value="">https://github.com/owner/repo</option>
                    <option v-for="repo in repositories" :key="repo.full_name" :value="`https://github.com/${repo.full_name}`">{{ repo.full_name }}</option>
                  </select>
                  <input v-else v-model="form.repository_url" placeholder="https://github.com/owner/repo" />
                </label>
                <p class="field-note">{{ t("publicOnly") }}</p>
                <div v-if="status?.github.authenticated" class="inline create-repo">
                  <input v-model="createRepositoryName" :placeholder="locale === 'zh' ? '新公共仓库名称' : 'New public repository name'" />
                  <button class="secondary" :disabled="!createRepositoryName" @click="createRepository">
                    <Plus :size="17" />{{ locale === "zh" ? "创建仓库" : "Create" }}
                  </button>
                </div>
                <div class="two"><label>{{ t("repositoryName") }}<input v-model="form.repository_name" /></label><label>{{ t("author") }}<input v-model="form.author" /></label></div>
                <label>{{ t("repositoryDescription") }}<textarea v-model="form.repository_description" rows="2" /></label>
                </div>

                <div v-else-if="publishStep === 3" class="wizard-page">
                <div class="two"><label>{{ t("workflowId") }}<input v-model="form.id" placeholder="portrait-basic" /></label><label>{{ t("name") }}<input v-model="form.name" /></label></div>
                <label>{{ t("summary") }}<input v-model="form.summary" /></label>
                <label>{{ t("description") }}<textarea v-model="form.description" rows="4" /></label>
                <label>{{ t("tags") }}<input v-model="form.tags" /></label>
                </div>

                <div v-else class="wizard-page">
                <div class="three"><label>{{ t("version") }}<input v-model="form.version" /></label><label>{{ t("minComfy") }}<input v-model="form.minimum" /></label><label>{{ t("maxComfy") }}<input v-model="form.maximum" /></label></div>
                <label>{{ t("releaseNotes") }}<textarea v-model="form.changelog" rows="5" /></label>
                <label class="file-field">{{ locale === "zh" ? "预览图（PNG/WebP，最大 1 MiB）" : "Preview (PNG/WebP, max 1 MiB)" }}
                  <span><FileUp :size="18" /><input type="file" accept="image/png,image/webp" @change="choosePreview" /></span>
                </label>
                <div class="advanced-fields">
                  <details><summary>{{ t("nodeDeps") }}</summary><textarea v-model="form.custom_nodes" class="code" rows="8" /></details>
                  <details><summary>{{ t("modelDeps") }}</summary><textarea v-model="form.models" class="code" rows="8" /></details>
                </div>
              </div>
              </div>

              <div class="wizard-actions">
                <button v-if="publishStep > 1" class="ghost" @click="previousPublishStep"><ChevronLeft :size="17" />{{ locale === "zh" ? "上一步" : "Back" }}</button>
                <span />
                <button v-if="publishStep < 4" class="primary" :disabled="!canAdvancePublish" @click="nextPublishStep">
                  {{ locale === "zh" ? "下一步" : "Continue" }}<ChevronRight :size="17" />
                </button>
                <template v-else>
                  <button class="ghost" :disabled="!!busy || !canFinalizePublish" @click="saveDraft">{{ locale === "zh" ? "保存草稿" : "Save draft" }}</button>
                  <button class="secondary" :disabled="!!busy || !canFinalizePublish" @click="validatePublish"><ShieldCheck :size="17" />{{ t("validate") }}</button>
                  <button class="primary" :disabled="!!busy || !canFinalizePublish || !status?.github.authenticated" @click="publishNow"><UploadCloud :size="17" />{{ t("publishNow") }}</button>
                </template>
              </div>
            </section>
          </div>
        </Transition>
      </main>
    </section>

    <div v-if="selected" class="backdrop" @click.self="selected = null">
      <aside class="detail">
        <button class="icon-button close" :title="t('close')" :aria-label="t('close')" @click="selected = null"><X :size="18" /></button>
        <a class="eyebrow repository-link" :href="repositoryUrl(selected)" target="_blank" rel="noopener"
          :title="t('repositoryPage')">
          <GitBranch :size="14" />{{ selected.source.owner }}/{{ selected.source.repo }}<ExternalLink :size="12" />
        </a>
        <h1>{{ selected.name }}</h1>
        <img v-if="latest(selected)?.preview" class="detail-preview" :src="latest(selected)?.preview?.url" :alt="selected.name" />
        <div class="tags"><span v-for="tag in selected.tags" :key="tag">{{ tag }}</span></div>
        <div v-if="status?.github.authenticated" class="manage-actions">
          <button class="secondary" @click="editProduct(selected)">{{ locale === "zh" ? "修改展示资料" : "Edit metadata" }}</button>
          <button class="secondary" @click="archiveProduct(selected)"><ArchiveIcon :size="16" />{{ selected.archived ? (locale === "zh" ? "取消归档" : "Unarchive") : (locale === "zh" ? "归档" : "Archive") }}</button>
        </div>
        <div class="detail-section-heading"><h3>{{ t("versions") }}</h3><span>{{ selected.versions.length }}</span></div>
        <article v-for="version in [...selected.versions].sort(compareVersions).reverse()" :key="version.version" class="release">
          <div class="release-head"><strong>v{{ version.version }}</strong><span>{{ new Date(version.published_at).toLocaleDateString() }} · {{ humanBytes(version.package.size) }}</span></div>
          <p class="compatibility">ComfyUI {{ version.comfyui.minimum || "—" }} – {{ version.comfyui.maximum || "∞" }}</p>
          <div class="release-links">
            <button class="release-link" :aria-expanded="expandedChangelog === dependencyKey(selected, version)"
              @click="toggleChangelog(selected, version)">
              <ChevronRight :size="15" :class="{ expanded: expandedChangelog === dependencyKey(selected, version) }" />
              {{ expandedChangelog === dependencyKey(selected, version) ? t("hideChangelog") : t("viewChangelog") }}
            </button>
            <a class="release-link" :href="releaseUrl(selected, version)" target="_blank" rel="noopener">
              {{ t("releasePage") }}<ExternalLink :size="14" />
            </a>
          </div>
          <Transition name="changelog">
            <div v-if="expandedChangelog === dependencyKey(selected, version)" class="changelog-panel">
              <span>{{ t("changelog") }}</span>
              <p class="changelog">{{ version.changelog }}</p>
            </div>
          </Transition>
          <details v-if="version.custom_nodes.length"><summary>{{ t("dependencies") }} ({{ version.custom_nodes.length }})</summary><pre>{{ JSON.stringify(version.custom_nodes, null, 2) }}</pre></details>
          <details v-if="version.models.length"><summary>{{ t("models") }} ({{ version.models.length }})</summary><pre>{{ JSON.stringify(version.models, null, 2) }}</pre></details>
          <div class="version-actions" :class="{ 'downloaded-actions': selected.downloaded_versions.includes(version.version) }">
            <button v-if="!selected.downloaded_versions.includes(version.version)" class="primary wide" :disabled="!!busy" @click="download(selected, version)"><DownloadIcon :size="17" />{{ t("download") }}</button>
            <template v-else>
              <button class="secondary wide" :disabled="!!busy" @click="revealLocalVersion(selected, version)"><FolderOpen :size="17" />{{ t("revealLocal") }}</button>
              <button class="ghost wide danger-action" :disabled="!!busy" @click="deleteLocalVersion(selected, version)"><Trash2 :size="16" />{{ t("deleteLocal") }}</button>
            </template>
            <button v-if="version.custom_nodes.length" class="secondary wide dependency-action" :disabled="!!busy" @click="planDependencies(selected, version)"><ListFilter :size="17" />{{ locale === "zh" ? "生成依赖计划" : "Plan dependencies" }}</button>
          </div>
          <div v-if="dependencyPlans[dependencyKey(selected, version)]" class="dependency-plan">
            <div v-if="!status?.manager.available || !status?.manager.compatible" class="message warning"><TriangleAlert :size="17" /><span>{{ t("managerUnavailable") }}</span></div>
            <label v-for="(entry, index) in dependencyPlans[dependencyKey(selected, version)]" :key="dependencyActionKey(entry, index)" class="dependency-row">
              <input v-if="['install','upgrade','newer'].includes(entry.action)" type="checkbox"
                :checked="selectedDependencyActions[dependencyKey(selected, version)]?.includes(dependencyActionKey(entry, index))"
                :disabled="!status?.manager.available || !status?.manager.compatible"
                @change="toggleDependencyAction(dependencyKey(selected, version), dependencyActionKey(entry, index), ($event.target as HTMLInputElement).checked)" />
              <span><strong>{{ entry.name }}</strong><small>{{ entry.installed || "—" }} → {{ entry.requested || "latest" }} · {{ entry.action }}<template v-if="entry.warning"> · {{ entry.warning }}</template></small></span>
            </label>
            <label class="confirm-row"><input v-model="dependencyConfirmed[dependencyKey(selected, version)]" type="checkbox" />{{ t("confirmEnvironment") }}</label>
            <button class="primary wide"
              :disabled="!dependencyConfirmed[dependencyKey(selected, version)] || !selectedDependencyActions[dependencyKey(selected, version)]?.length || !status?.manager.available || !status?.manager.compatible || !!busy"
              @click="executeDependencyPlan(selected, version)">{{ t("execute") }}</button>
          </div>
        </article>
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
