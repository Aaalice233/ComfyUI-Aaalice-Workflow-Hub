<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from "vue";
import {
  Activity as ActivityIcon,
  AlertCircle,
  Archive as ArchiveIcon,
  ArrowRight,
  Check,
  CheckCircle2,
  CircleUserRound,
  CloudDownload,
  Compass,
  Download as DownloadIcon,
  ExternalLink,
  FileCheck2,
  FileUp,
  FolderGit2,
  GitBranch,
  Languages,
  LibraryBig,
  ListFilter,
  LogOut,
  PackageOpen,
  Plus,
  RefreshCw,
  Search as SearchIcon,
  ShieldCheck,
  Sparkles,
  Trash2,
  TriangleAlert,
  UploadCloud,
  X,
} from "@lucide/vue";
import { api, post, remove } from "./api";
import { requestCanvas } from "./channel";
import { locale, t, toggleLocale } from "./i18n";

type Source = { owner: string; repo: string; url: string; refreshed_at: string; error?: string };
type Version = {
  version: string; published_at: string; changelog: string;
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
const sourceUrl = ref("");
const sourceInput = ref<HTMLInputElement | null>(null);
const search = ref("");
const filter = ref<"all" | "downloaded" | "updates" | "archived">("all");
const busy = ref("");
const error = ref("");
const notice = ref("");
const drawer = ref(false);
const operations = ref<Operation[]>([]);
const saved = ref<{ name: string; path: string }[]>([]);
const repositories = ref<{ full_name: string }[]>([]);
const createRepositoryName = ref("");
const drafts = ref<{ id: string; name: string; payload: ReturnType<typeof payload> }[]>([]);
const pendingPublications = ref<{ tag: string }[]>([]);
const selectedSaved = ref("");
const sourceMode = ref<"canvas" | "saved">("canvas");
const workflow = ref<Record<string, unknown> | null>(null);
const workflowSourceName = ref("");
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
const downloadedCount = computed(() => products.value.filter((item) => item.downloaded_versions.length).length);
const updateCount = computed(() => products.value.filter((item) => {
  const version = latest(item)?.version;
  return !!version && !item.downloaded_versions.includes(version);
}).length);

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
function clearMessages() {
  error.value = "";
  notice.value = "";
}
async function load() {
  clearMessages();
  const [s, sub, flows, ops, files] = await Promise.all([
    api<Status>("/status"),
    api<{ items: Source[] }>("/subscriptions"),
    api<{ items: Product[] }>("/workflows"),
    api<{ items: Operation[] }>("/operations"),
    api<{ items: { name: string; path: string }[] }>("/publisher/saved-workflows"),
  ]);
  status.value = s;
  sources.value = sub.items;
  products.value = flows.items;
  operations.value = ops.items;
  saved.value = files.items;
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
async function getCanvas() {
  await withBusy("canvas", async () => {
    const snapshot = await requestCanvas();
    workflow.value = snapshot.workflow;
    workflowSourceName.value = snapshot.name;
    if (!form.name) form.name = snapshot.name;
  });
  if (!workflow.value && !error.value) error.value = t.value("canvasUnavailable");
}
async function loadSaved() {
  if (!selectedSaved.value) return;
  await withBusy("saved", async () => {
    const result = await post<{ workflow: Record<string, unknown>; name: string }>("/publisher/load-workflow", { path: selectedSaved.value });
    workflow.value = result.workflow;
    workflowSourceName.value = result.name;
    if (!form.name) form.name = result.name;
  });
}
async function scanDependencies() {
  await withBusy("scan", async () => {
    if (!workflow.value) throw new Error(t.value("canvasUnavailable"));
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
    if (!workflow.value) throw new Error(t.value("canvasUnavailable"));
    await post("/publisher/validate", payload());
    notice.value = locale.value === "zh" ? "校验通过，可以发布。" : "Validation passed. Ready to publish.";
  });
}
async function publishNow() {
  await withBusy("publish", async () => {
    if (!workflow.value) throw new Error(t.value("canvasUnavailable"));
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
  try { await load(); await pollOperations(); }
  catch (reason) { error.value = reason instanceof Error ? reason.message : String(reason); }
});
onBeforeUnmount(() => {
  clearTimeout(operationTimer);
  clearTimeout(loginTimer);
});
</script>

<template>
  <div class="app-shell">
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
      <div class="system-card">
        <div><span :class="['health-dot', { online: status?.manager.available && status?.manager.compatible }]" /><strong>ComfyUI Manager</strong></div>
        <small>{{ status?.manager.available && status?.manager.compatible ? (locale === "zh" ? "连接正常" : "Connected") : (locale === "zh" ? "需要检查" : "Needs attention") }}</small>
      </div>

      <div class="rail-actions">
        <button class="rail-action" @click="drawer = !drawer">
          <ActivityIcon :size="17" /><span>{{ t("activities") }}</span>
          <i v-if="operations.some(o => o.status === 'running')" class="pulse" />
        </button>
        <button class="rail-action" @click="toggleLocale">
          <Languages :size="17" /><span>{{ locale === "zh" ? "English" : "简体中文" }}</span>
        </button>
        <button v-if="status?.github.authenticated" class="account-card" @click="logout">
          <img v-if="status.github.user?.avatar_url" :src="status.github.user.avatar_url" alt="" />
          <CircleUserRound v-else :size="18" />
          <span><strong>{{ status.github.user?.login || t("signedIn") }}</strong><small>{{ t("logout") }}</small></span>
          <LogOut :size="15" />
        </button>
        <button v-else class="account-card" :disabled="!status?.github.configured || !!busy" @click="startLogin">
          <GitBranch :size="18" /><span><strong>{{ t("login") }}</strong><small>{{ locale === "zh" ? "用于发布和管理" : "Publish and manage" }}</small></span>
          <ArrowRight :size="15" />
        </button>
      </div>
    </aside>

    <section class="workspace">
      <header class="workspace-header">
        <div>
          <p class="eyebrow"><Sparkles :size="14" />{{ tab === "subscribe" ? t("libraryLabel") : t("publisherLabel") }}</p>
          <h1>{{ tab === "subscribe" ? t("subscribeTitle") : t("publishTitle") }}</h1>
          <p>{{ tab === "subscribe" ? t("subscribeDescription") : t("publishDescription") }}</p>
        </div>
        <div v-if="tab === 'subscribe'" class="header-metrics">
          <div><strong>{{ products.length }}</strong><span>{{ t("workflowsLabel") }}</span></div>
          <div><strong>{{ downloadedCount }}</strong><span>{{ t("downloaded") }}</span></div>
          <div><strong>{{ updateCount }}</strong><span>{{ t("updates") }}</span></div>
        </div>
      </header>

      <main class="workspace-body">
        <div v-if="error" class="message error">
          <AlertCircle :size="18" /><span>{{ error }}</span><button :aria-label="t('close')" @click="error = ''"><X :size="17" /></button>
        </div>
        <div v-if="notice" class="message success">
          <CheckCircle2 :size="18" /><span>{{ notice }}</span><button :aria-label="t('close')" @click="notice = ''"><X :size="17" /></button>
        </div>
        <div v-if="status && !status.manager.available" class="message warning">
          <TriangleAlert :size="18" /><span>{{ t("managerUnavailable") }}</span>
        </div>
        <div v-if="status && !status.github.configured && tab === 'publish'" class="message warning">
          <TriangleAlert :size="18" /><span>{{ t("githubNotConfigured") }}</span>
        </div>

        <template v-if="tab === 'subscribe'">
          <section class="source-command">
            <div class="section-intro">
              <span class="section-icon"><Plus :size="19" /></span>
              <div><h2>{{ t("addSource") }}</h2><p>{{ t("addSourceHint") }}</p></div>
            </div>
            <div class="source-form">
              <GitBranch :size="18" />
              <input ref="sourceInput" v-model="sourceUrl" :placeholder="t('sourcePlaceholder')" @keyup.enter="addSource" />
              <button class="primary" :disabled="!sourceUrl || !!busy" @click="addSource">
                <Plus :size="17" />{{ t("add") }}
              </button>
            </div>
            <div v-if="sources.length" class="source-chips">
              <div v-for="item in sources" :key="item.url" class="source-chip">
                <FolderGit2 :size="15" />
                <span>{{ item.owner }}/{{ item.repo }}</span>
                <button :title="t('refresh')" @click="refreshSource(item)"><RefreshCw :size="14" /></button>
                <button :title="t('remove')" @click="removeSource(item)"><Trash2 :size="14" /></button>
              </div>
            </div>
          </section>

          <section class="catalog-section">
            <div class="catalog-toolbar">
              <label class="search-field">
                <SearchIcon :size="18" />
                <input v-model="search" :placeholder="t('search')" />
              </label>
              <div class="segmented" role="group" :aria-label="locale === 'zh' ? '工作流筛选' : 'Workflow filters'">
                <button v-for="item in (['all','downloaded','updates','archived'] as const)" :key="item"
                  :class="{ active: filter === item }" @click="filter = item">{{ t(item) }}</button>
              </div>
            </div>

            <div v-if="visibleProducts.length" class="catalog">
              <article v-for="item in visibleProducts" :key="`${item.source.owner}/${item.source.repo}/${item.id}`"
                class="workflow-card" tabindex="0" @click="selected = item" @keyup.enter="selected = item">
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
                    <span><GitBranch :size="13" />{{ item.source.owner }}/{{ item.source.repo }}</span>
                    <span v-if="item.downloaded_versions.length" class="downloaded"><Check :size="13" />{{ t("downloadedTag") }}</span>
                  </footer>
                </div>
              </article>
            </div>

            <div v-else class="empty-state">
              <span class="empty-orbit"><PackageOpen :size="32" /></span>
              <h2>{{ t("emptyTitle") }}</h2>
              <p>{{ search || filter !== "all" ? t("emptyFiltered") : t("noWorkflows") }}</p>
              <button v-if="!search && filter === 'all'" class="secondary" @click="sourceInput?.focus()">
                <Plus :size="17" />{{ t("addSource") }}
              </button>
            </div>
          </section>
        </template>

        <template v-else>
          <div class="publish-grid">
            <aside class="publish-sidebar">
              <section class="panel source-panel">
                <div class="panel-heading">
                  <span class="step">01</span>
                  <div><h2>{{ t("source") }}</h2><p>{{ locale === "zh" ? "选择要发布的工作流" : "Choose the workflow to publish" }}</p></div>
                </div>
                <div class="choice">
                  <button :class="{ active: sourceMode === 'canvas' }" @click="sourceMode = 'canvas'">{{ t("currentCanvas") }}</button>
                  <button :class="{ active: sourceMode === 'saved' }" @click="sourceMode = 'saved'">{{ t("savedWorkflow") }}</button>
                </div>
                <button v-if="sourceMode === 'canvas'" class="secondary wide" :disabled="!!busy" @click="getCanvas">
                  <CloudDownload :size="17" />{{ t("requestCanvas") }}
                </button>
                <div v-else class="saved-picker">
                  <select v-model="selectedSaved"><option value="">{{ t("selectFile") }}</option><option v-for="item in saved" :key="item.path" :value="item.path">{{ item.name }}</option></select>
                  <button class="secondary" @click="loadSaved"><FileCheck2 :size="17" /></button>
                </div>
                <div v-if="workflow" class="ready-card">
                  <CheckCircle2 :size="18" /><span><strong>{{ locale === "zh" ? "已就绪" : "Ready" }}</strong><small>{{ workflowSourceName }}</small></span>
                </div>
                <button v-if="workflow" class="ghost wide" :disabled="!!busy" @click="scanDependencies">
                  <ListFilter :size="17" />{{ locale === "zh" ? "扫描节点依赖" : "Scan node dependencies" }}
                </button>
              </section>

              <section v-if="drafts.length || pendingPublications.length" class="panel compact-panel">
                <details v-if="drafts.length"><summary>{{ locale === "zh" ? "草稿" : "Drafts" }}</summary>
                  <button v-for="draft in drafts" :key="draft.id" class="ghost wide" @click="loadDraft(draft)">{{ draft.name }}</button>
                </details>
                <details v-if="pendingPublications.length"><summary>{{ locale === "zh" ? "待同步发布" : "Pending publications" }}</summary>
                  <button v-for="item in pendingPublications" :key="item.tag" class="ghost wide" @click="resumePending(item.tag)">{{ item.tag }}</button>
                </details>
              </section>
            </aside>

            <section class="panel form-panel">
              <div class="form-section">
                <div class="panel-heading">
                  <span class="step">02</span>
                  <div><h2>{{ t("repository") }}</h2><p>{{ t("publicOnly") }}</p></div>
                </div>
                <label>{{ t("repository") }}
                  <select v-if="repositories.length" v-model="form.repository_url">
                    <option value="">https://github.com/owner/repo</option>
                    <option v-for="repo in repositories" :key="repo.full_name" :value="`https://github.com/${repo.full_name}`">{{ repo.full_name }}</option>
                  </select>
                  <input v-else v-model="form.repository_url" placeholder="https://github.com/owner/repo" />
                </label>
                <div v-if="status?.github.authenticated" class="inline create-repo">
                  <input v-model="createRepositoryName" :placeholder="locale === 'zh' ? '新公共仓库名称' : 'New public repository name'" />
                  <button class="secondary" :disabled="!createRepositoryName" @click="createRepository">
                    <Plus :size="17" />{{ locale === "zh" ? "创建仓库" : "Create" }}
                  </button>
                </div>
                <div class="two"><label>{{ t("repositoryName") }}<input v-model="form.repository_name" /></label><label>{{ t("author") }}<input v-model="form.author" /></label></div>
                <label>{{ t("repositoryDescription") }}<textarea v-model="form.repository_description" rows="2" /></label>
              </div>

              <div class="form-section">
                <div class="panel-heading">
                  <span class="step">03</span>
                  <div><h2>{{ t("workflowInfo") }}</h2><p>{{ locale === "zh" ? "用于订阅者发现和理解工作流" : "Help subscribers discover and understand it" }}</p></div>
                </div>
                <div class="two"><label>{{ t("workflowId") }}<input v-model="form.id" placeholder="portrait-basic" /></label><label>{{ t("name") }}<input v-model="form.name" /></label></div>
                <label>{{ t("summary") }}<input v-model="form.summary" /></label>
                <label>{{ t("description") }}<textarea v-model="form.description" rows="4" /></label>
                <label>{{ t("tags") }}<input v-model="form.tags" /></label>
              </div>

              <div class="form-section">
                <div class="panel-heading">
                  <span class="step">04</span>
                  <div><h2>{{ t("version") }}</h2><p>{{ locale === "zh" ? "声明兼容范围与本次更新" : "Declare compatibility and release changes" }}</p></div>
                </div>
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

              <div class="publish-actions">
                <button class="ghost" :disabled="!!busy" @click="saveDraft">{{ locale === "zh" ? "保存草稿" : "Save draft" }}</button>
                <button class="secondary" :disabled="!!busy" @click="validatePublish"><ShieldCheck :size="17" />{{ t("validate") }}</button>
                <button class="primary" :disabled="!!busy || !status?.github.authenticated" @click="publishNow"><UploadCloud :size="17" />{{ t("publishNow") }}</button>
              </div>
            </section>
          </div>
        </template>
      </main>
    </section>

    <div v-if="selected" class="backdrop" @click.self="selected = null">
      <aside class="detail">
        <button class="icon-button close" :aria-label="t('close')" @click="selected = null"><X :size="18" /></button>
        <p class="eyebrow"><GitBranch :size="14" />{{ selected.source.owner }}/{{ selected.source.repo }}</p>
        <h1>{{ selected.name }}</h1><p class="detail-copy">{{ selected.description || selected.summary }}</p>
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
          <p class="changelog">{{ version.changelog }}</p>
          <details v-if="version.custom_nodes.length"><summary>{{ t("dependencies") }} ({{ version.custom_nodes.length }})</summary><pre>{{ JSON.stringify(version.custom_nodes, null, 2) }}</pre></details>
          <details v-if="version.models.length"><summary>{{ t("models") }} ({{ version.models.length }})</summary><pre>{{ JSON.stringify(version.models, null, 2) }}</pre></details>
          <div class="version-actions">
            <button v-if="!selected.downloaded_versions.includes(version.version)" class="primary wide" :disabled="!!busy" @click="download(selected, version)"><DownloadIcon :size="17" />{{ t("download") }}</button>
            <button v-else class="secondary wide" :disabled="!!busy" @click="deleteLocalVersion(selected, version)"><Check :size="17" />{{ t("downloadedTag") }} · {{ locale === "zh" ? "删除本地版本" : "Delete local version" }}</button>
            <button v-if="version.custom_nodes.length" class="secondary wide" :disabled="!!busy" @click="planDependencies(selected, version)"><ListFilter :size="17" />{{ locale === "zh" ? "生成依赖计划" : "Plan dependencies" }}</button>
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
      <div class="drawer-head"><div><span class="section-icon"><ActivityIcon :size="18" /></span><h2>{{ t("activities") }}</h2></div><button class="icon-button" :aria-label="t('close')" @click="drawer = false"><X :size="18" /></button></div>
      <div v-if="!operations.length" class="empty small"><ActivityIcon :size="25" /><span>{{ t("noActivities") }}</span></div>
      <article v-for="item in operations" :key="item.id" class="operation">
        <div><strong>{{ item.kind }}</strong><span :class="`status ${item.status}`">{{ item.stage }}</span></div>
        <progress v-if="item.progress?.total" :value="item.progress.received" :max="item.progress.total" />
        <pre v-if="item.logs.length">{{ item.logs.join("\n") }}</pre>
      </article>
    </aside>

    <div v-if="device" class="device">
      <div><GitBranch :size="20" /><strong>GitHub Device Flow</strong></div>
      <code>{{ device.user_code }}</code>
      <a :href="device.verification_uri" target="_blank" rel="noopener">{{ device.verification_uri }}<ExternalLink :size="14" /></a>
    </div>
  </div>
</template>
