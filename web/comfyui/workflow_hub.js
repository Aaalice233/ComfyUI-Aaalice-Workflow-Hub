import { app } from "../../scripts/app.js";
import { resolveHostLocale, translateHost } from "./i18n.js";

const PAGE = "/workflow-hub";
const ICON_CLASS = "aaalice-workflow-hub-icon";
const ICON_STYLE_ID = "aaalice-workflow-hub-icon-style";
const MODAL_ID = "aaalice-workflow-hub-modal";
let workflowUpdateTimer = 0;
const LIBRARY_BIG_SVG = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="black" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="8" height="18" x="3" y="3" rx="1"/><path d="M7 3v18"/><path d="M20.4 18.9c.2.5-.1 1.1-.6 1.3l-1.9.7c-.5.2-1.1-.1-1.3-.6L11.1 5.1c-.2-.5.1-1.1.6-1.3l1.9-.7c.5-.2 1.1.1 1.3.6Z"/></svg>`;

function getComfyLocale() {
  return app.ui.settings.getSettingValue("Comfy.Locale");
}

function t(key, params) {
  return translateHost(resolveHostLocale(getComfyLocale()), key, params);
}

const TOOLTIP = t("tooltip");

function getHubUrl() {
  const params = new URLSearchParams({
    locale: getComfyLocale(),
    embedded: "1",
    revision: String(Date.now()),
  });
  return `${PAGE}?${params}`;
}

function handleLocaleChange(event) {
  const frame = document.querySelector(`#${MODAL_ID} .aaalice-workflow-hub-frame`);
  frame?.contentWindow?.postMessage(
    { type: "AAALICE_WORKFLOW_HUB_LOCALE", locale: event.detail?.value },
    window.location.origin,
  );
}

function scheduleWorkflowUpdateCheck(nextCheckAt) {
  window.clearTimeout(workflowUpdateTimer);
  workflowUpdateTimer = 0;
  if (!nextCheckAt) return;
  const timestamp = Date.parse(nextCheckAt);
  if (Number.isNaN(timestamp)) return;
  const delay = Math.max(30_000, timestamp - Date.now());
  workflowUpdateTimer = window.setTimeout(() => {
    workflowUpdateTimer = 0;
    void notifyWorkflowUpdates();
  }, delay);
}

async function notifyWorkflowUpdates() {
  try {
    const response = await fetch("/workflow-hub/api/v1/update-notifications", {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json", "Cache-Control": "no-cache" },
      body: "{}",
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const result = await response.json();
    scheduleWorkflowUpdateCheck(result.next_check_at);
    const { items } = result;
    if (!Array.isArray(items) || items.length === 0) return;

    const visible = items.slice(0, 3).map((item) => `${item.name} v${item.version}`);
    const remaining = items.length - visible.length;
    const detail = remaining > 0
      ? t("updateDetailMore", { items: visible.join(t("listSeparator")), remaining, total: items.length })
      : visible.join(t("listSeparator"));
    app.extensionManager.toast.add({
      severity: "info",
      summary: t(items.length === 1 ? "updatesAvailableOne" : "updatesAvailable", { count: items.length }),
      detail,
      life: 5000,
    });
  } catch (error) {
    scheduleWorkflowUpdateCheck(new Date(Date.now() + 5 * 60 * 1000).toISOString());
    console.warn("[Aaalice Workflow Hub] Failed to check workflow updates.", error);
  }
}

function installIconStyle() {
  if (document.getElementById(ICON_STYLE_ID)) return;

  const iconMask = `url("data:image/svg+xml,${encodeURIComponent(LIBRARY_BIG_SVG)}")`;
  const style = document.createElement("style");
  style.id = ICON_STYLE_ID;
  style.textContent = `
    button[aria-label="${TOOLTIP}"] {
      padding: 6px;
      border: 1px solid transparent;
      border-radius: 4px;
      background-color: var(--primary-bg) !important;
      transition: background-color 0.2s ease;
    }

    button[aria-label="${TOOLTIP}"]:hover {
      background-color: var(--primary-hover-bg) !important;
    }

    .${ICON_CLASS} {
      display: inline-block;
      width: 20px;
      height: 20px;
      flex: none;
      background-color: #d3e2e7;
      -webkit-mask: ${iconMask} center / contain no-repeat;
      mask: ${iconMask} center / contain no-repeat;
    }

    .aaalice-workflow-hub-modal {
      position: fixed;
      inset: 0;
      z-index: 10000;
      display: grid;
      place-items: center;
      padding: 36px;
      background: rgb(5 8 12 / 82%);
    }

    .aaalice-workflow-hub-panel {
      display: flex;
      width: min(1180px, 92vw);
      height: min(780px, 86vh);
      min-height: 520px;
      overflow: hidden;
      border-radius: 14px;
      background: var(--comfy-menu-bg, #17191d);
      box-shadow: 0 28px 80px rgb(0 0 0 / 48%), inset 0 1px rgb(255 255 255 / 6%);
      flex-direction: column;
    }

    .aaalice-workflow-hub-frame {
      position: relative;
      width: 100%;
      min-height: 0;
      border: 0;
      background: #101216;
      flex: 1;
    }

    @media (max-width: 760px), (max-height: 640px) {
      .aaalice-workflow-hub-modal {
        padding: 18px;
      }

      .aaalice-workflow-hub-panel {
        width: 94vw;
        height: 90vh;
        min-height: 0;
      }
    }
  `;
  document.head.appendChild(style);
}

function closeHub() {
  document.getElementById(MODAL_ID)?.remove();
  document.removeEventListener("keydown", handleHubKeydown, true);
}

function handleHubMessage(event) {
  if (event.origin !== window.location.origin) return;
  if (event.data?.type === "AAALICE_WORKFLOW_HUB_SETTINGS_CHANGED") {
    void notifyWorkflowUpdates();
    return;
  }
  if (event.data?.type === "AAALICE_WORKFLOW_HUB_CLOSE") {
    closeHub();
    return;
  }
  if (event.data?.type === "AAALICE_WORKFLOW_HUB_LOAD_WORKFLOW") {
    try {
      if (!event.data.workflow || typeof event.data.workflow !== "object") throw new Error("Invalid workflow payload");
      app.loadGraphData(event.data.workflow);
      closeHub();
    } catch (error) {
      console.error("[Aaalice Workflow Hub] Failed to load workflow.", error);
    }
    return;
  }
  if (event.data?.type !== "AAALICE_WORKFLOW_HUB_REQUEST_CURRENT_WORKFLOW") return;

  try {
    const activeWorkflow = app.extensionManager?.workflow?.activeWorkflow;
    const activeName = (activeWorkflow?.filename || activeWorkflow?.path || "").split(/[\\/]/).at(-1);
    const filename = activeName
      ? (activeName.toLowerCase().endsWith(".json") ? activeName : `${activeName}.json`)
      : t("untitledWorkflowFile");
    const workflow = JSON.parse(JSON.stringify(app.graph.serialize()));
    event.source?.postMessage(
      { type: "AAALICE_WORKFLOW_HUB_CURRENT_WORKFLOW", filename, workflow },
      window.location.origin,
    );
  } catch (error) {
    event.source?.postMessage(
      {
        type: "AAALICE_WORKFLOW_HUB_CURRENT_WORKFLOW",
        error: error instanceof Error ? error.message : String(error),
      },
      window.location.origin,
    );
  }
}

function handleHubKeydown(event) {
  if (event.key !== "Escape") return;
  event.preventDefault();
  closeHub();
}

function openEmbeddedHub() {
  const current = document.getElementById(MODAL_ID);
  if (current) {
    current.querySelector(".aaalice-workflow-hub-close")?.focus();
    return;
  }

  const modal = document.createElement("div");
  modal.id = MODAL_ID;
  modal.className = "aaalice-workflow-hub-modal";
  modal.setAttribute("role", "dialog");
  modal.setAttribute("aria-modal", "true");
  modal.setAttribute("aria-label", t("title"));

  const panel = document.createElement("section");
  panel.className = "aaalice-workflow-hub-panel";

  const frame = document.createElement("iframe");
  frame.className = "aaalice-workflow-hub-frame";
  frame.src = getHubUrl();
  frame.title = t("title");
  frame.loading = "eager";
  frame.addEventListener("load", () => {
    frame.contentDocument?.addEventListener("keydown", handleHubKeydown, true);
    frame.focus();
  });

  panel.append(frame);
  modal.append(panel);
  modal.addEventListener("click", (event) => {
    if (event.target === modal) closeHub();
  });
  document.body.appendChild(modal);
  document.addEventListener("keydown", handleHubKeydown, true);
}

function openHub(event) {
  const url = `${window.location.origin}${getHubUrl()}`;
  if (event?.shiftKey) {
    window.open(url, "_blank", "width=1240,height=840,resizable=yes,scrollbars=yes,status=yes");
    return;
  }
  openEmbeddedHub();
}

installIconStyle();
app.ui.settings.addEventListener("Comfy.Locale.change", handleLocaleChange);
window.addEventListener("message", handleHubMessage);

app.registerExtension({
  name: "Aaalice.WorkflowHub",
  setup() {
    void notifyWorkflowUpdates();
  },
  actionBarButtons: [
    {
      icon: ICON_CLASS,
      tooltip: TOOLTIP,
      onClick: openHub,
    },
  ],
  aboutPageBadges: [
    {
      label: "Aaalice Workflow Hub v1.0.4",
      url: "https://github.com/Aaalice233/ComfyUI-Aaalice-Workflow-Hub",
      icon: "pi pi-box",
    },
  ],
});
