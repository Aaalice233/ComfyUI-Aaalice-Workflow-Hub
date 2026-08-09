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

function comfyUserHeaders() {
  try {
    const user = window.localStorage.getItem("Comfy.userId");
    return user ? { "Comfy-User": user } : {};
  } catch {
    return {};
  }
}

let pendingUpdates = [];
let badgeAttempts = 0;

function updatePendingBadge() {
  badgeAttempts = 0;
  applyPendingBadge();
}

function setPendingUpdates(items) {
  pendingUpdates = Array.isArray(items) ? items : [];
  updatePendingBadge();
  if (pendingUpdates.length === 0) {
    hideUpdateTooltip();
    closeUpdateMenu();
  } else {
    renderUpdateTooltip();
  }
}

const TOOLTIP_ID = "aaalice-workflow-hub-updates-tooltip";
const MENU_ID = "aaalice-workflow-hub-updates-menu";
const TOOLTIP_MAX_ITEMS = 8;

function updateTooltipElement() {
  return document.getElementById(TOOLTIP_ID);
}

function renderUpdateTooltip() {
  const tooltip = updateTooltipElement();
  if (!tooltip || pendingUpdates.length === 0) return;
  const visible = pendingUpdates.slice(0, TOOLTIP_MAX_ITEMS);
  const rows = visible.map((item) => {
    const row = document.createElement("div");
    row.className = "aaalice-workflow-hub-updates-tooltip-row";
    const name = document.createElement("span");
    name.textContent = item.name;
    const version = document.createElement("strong");
    version.textContent = `v${item.version}`;
    row.append(name, version);
    return row;
  });
  if (pendingUpdates.length > visible.length) {
    const more = document.createElement("div");
    more.className = "aaalice-workflow-hub-updates-tooltip-row more";
    more.textContent = t("updateMoreCount", { count: pendingUpdates.length - visible.length });
    rows.push(more);
  }
  const hint = document.createElement("div");
  hint.className = "aaalice-workflow-hub-updates-tooltip-hint";
  hint.textContent = t("ignoreUpdatesHint");
  tooltip.replaceChildren(...rows, hint);
}

function showUpdateTooltip() {
  if (pendingUpdates.length === 0) return;
  const button = document.querySelector(`button[aria-label="${TOOLTIP}"]`);
  if (!button) return;
  let tooltip = updateTooltipElement();
  if (!tooltip) {
    tooltip = document.createElement("div");
    tooltip.id = TOOLTIP_ID;
    document.body.append(tooltip);
  }
  renderUpdateTooltip();
  const rect = button.getBoundingClientRect();
  tooltip.style.left = `${Math.min(rect.left, window.innerWidth - 340)}px`;
  tooltip.style.top = `${rect.bottom + 8}px`;
}

function hideUpdateTooltip() {
  updateTooltipElement()?.remove();
}

function updateMenuElement() {
  return document.getElementById(MENU_ID);
}

function closeUpdateMenu() {
  updateMenuElement()?.remove();
  document.removeEventListener("pointerdown", handleUpdateMenuOutside, true);
  document.removeEventListener("keydown", handleUpdateMenuKeydown, true);
}

function handleUpdateMenuOutside(event) {
  if (!updateMenuElement()?.contains(event.target)) closeUpdateMenu();
}

function handleUpdateMenuKeydown(event) {
  if (event.key === "Escape") closeUpdateMenu();
}

async function ignorePendingUpdates(items) {
  try {
    const response = await fetch("/workflow-hub/api/v1/update-notifications/ignore", {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json", ...comfyUserHeaders() },
      body: JSON.stringify({ items }),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const result = await response.json();
    setPendingUpdates(result.pending);
  } catch (error) {
    app.extensionManager.toast.add({ severity: "error", summary: t("ignoreUpdateFailed"), life: 4000 });
    console.warn("[Aaalice Workflow Hub] Failed to ignore workflow updates.", error);
  }
}

function openUpdateMenu(event) {
  if (pendingUpdates.length === 0) return;
  event.preventDefault();
  event.stopPropagation();
  hideUpdateTooltip();
  closeUpdateMenu();
  const menu = document.createElement("div");
  menu.id = MENU_ID;
  menu.setAttribute("role", "menu");
  for (const item of pendingUpdates) {
    const entry = document.createElement("button");
    entry.type = "button";
    entry.setAttribute("role", "menuitem");
    entry.textContent = t("ignoreUpdate", { name: item.name, version: item.version });
    entry.addEventListener("click", () => {
      closeUpdateMenu();
      void ignorePendingUpdates([item]);
    });
    menu.append(entry);
  }
  if (pendingUpdates.length > 1) {
    const divider = document.createElement("div");
    divider.className = "aaalice-workflow-hub-updates-menu-divider";
    const all = document.createElement("button");
    all.type = "button";
    all.setAttribute("role", "menuitem");
    all.textContent = t("ignoreAllUpdates");
    all.addEventListener("click", () => {
      const items = [...pendingUpdates];
      closeUpdateMenu();
      void ignorePendingUpdates(items);
    });
    menu.append(divider, all);
  }
  document.body.append(menu);
  const x = Math.min(event.clientX, window.innerWidth - menu.offsetWidth - 8);
  const y = Math.min(event.clientY, window.innerHeight - menu.offsetHeight - 8);
  menu.style.left = `${Math.max(4, x)}px`;
  menu.style.top = `${Math.max(4, y)}px`;
  document.addEventListener("pointerdown", handleUpdateMenuOutside, true);
  document.addEventListener("keydown", handleUpdateMenuKeydown, true);
}

function bindUpdateButtonInteractions(button) {
  if (button.dataset.updateInteractionsBound) return;
  button.dataset.updateInteractionsBound = "1";
  button.addEventListener("pointerenter", showUpdateTooltip);
  button.addEventListener("pointerleave", hideUpdateTooltip);
  button.addEventListener("contextmenu", openUpdateMenu);
}

function applyPendingBadge() {
  const count = pendingUpdates.length;
  const button = document.querySelector(`button[aria-label="${TOOLTIP}"]`);
  if (!button) {
    // The action bar button renders asynchronously after extension setup
    if (badgeAttempts < 30) {
      badgeAttempts += 1;
      window.setTimeout(applyPendingBadge, 1000);
    }
    return;
  }
  bindUpdateButtonInteractions(button);
  // The update list replaces ComfyUI's generic tooltip while the badge is active.
  button.$_ptooltipDisabled = count > 0;
  if (count > 0) button.setAttribute("data-update-count", String(count));
  else button.removeAttribute("data-update-count");
}

async function notifyWorkflowUpdates() {
  try {
    const response = await fetch("/workflow-hub/api/v1/update-notifications", {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json", "Cache-Control": "no-cache", ...comfyUserHeaders() },
      body: "{}",
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const result = await response.json();
    scheduleWorkflowUpdateCheck(result.next_check_at);
    setPendingUpdates(result.pending);
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
      position: relative;
      padding: 6px;
      border: 1px solid transparent;
      border-radius: 4px;
      background-color: var(--primary-bg) !important;
      transition: background-color 0.2s ease;
    }

    button[aria-label="${TOOLTIP}"]:hover {
      background-color: var(--primary-hover-bg) !important;
    }

    button[aria-label="${TOOLTIP}"][data-update-count]::after {
      content: "";
      position: absolute;
      top: 1px;
      right: 0;
      width: 9px;
      height: 9px;
      border-radius: 50%;
      background: #d9485f;
      box-shadow: 0 1px 4px rgb(0 0 0 / 40%);
      pointer-events: none;
    }

    #${TOOLTIP_ID} {
      position: fixed;
      z-index: 10001;
      box-sizing: border-box;
      max-width: 332px;
      padding: 10px 12px;
      border-radius: 8px;
      background: var(--p-overlay-modal-background, var(--p-content-background, #1e1e1e));
      color: var(--p-text-color, #e8e8e8);
      box-shadow: 0 8px 24px rgb(0 0 0 / 35%);
      font-size: 13px;
      line-height: 1.5;
      pointer-events: none;
    }

    #${TOOLTIP_ID} .aaalice-workflow-hub-updates-tooltip-row {
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 12px;
      padding: 2px 0;
    }

    #${TOOLTIP_ID} .aaalice-workflow-hub-updates-tooltip-row span {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    #${TOOLTIP_ID} .aaalice-workflow-hub-updates-tooltip-row strong {
      flex: none;
      color: var(--p-primary-color, #7db4d8);
    }

    #${TOOLTIP_ID} .aaalice-workflow-hub-updates-tooltip-row.more {
      color: var(--p-text-muted-color, #9a9a9a);
    }

    #${TOOLTIP_ID} .aaalice-workflow-hub-updates-tooltip-hint {
      margin-top: 8px;
      padding-top: 8px;
      border-top: 1px solid rgb(128 128 128 / 20%);
      color: var(--p-text-muted-color, #9a9a9a);
      font-size: 12px;
    }

    #${MENU_ID} {
      position: fixed;
      z-index: 10002;
      min-width: 200px;
      max-width: 340px;
      padding: 4px;
      border-radius: 8px;
      background: var(--p-overlay-modal-background, var(--p-content-background, #1e1e1e));
      color: var(--p-text-color, #e8e8e8);
      box-shadow: 0 8px 24px rgb(0 0 0 / 35%);
      font-size: 13px;
    }

    #${MENU_ID} button {
      display: block;
      width: 100%;
      padding: 7px 10px;
      border: none;
      border-radius: 5px;
      background: transparent;
      color: inherit;
      font: inherit;
      text-align: left;
      cursor: pointer;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    #${MENU_ID} button:hover,
    #${MENU_ID} button:focus-visible {
      background: var(--p-content-hover-background, rgb(255 255 255 / 8%));
      outline: none;
    }

    #${MENU_ID} .aaalice-workflow-hub-updates-menu-divider {
      height: 1px;
      margin: 4px 6px;
      background: rgb(128 128 128 / 20%);
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
  if (event.data?.type === "AAALICE_WORKFLOW_HUB_SETTINGS_CHANGED" || event.data?.type === "AAALICE_WORKFLOW_HUB_UPDATES_CHANGED") {
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
      label: "Aaalice Workflow Hub v1.1.0",
      url: "https://github.com/Aaalice233/ComfyUI-Aaalice-Workflow-Hub",
      icon: "pi pi-box",
    },
  ],
});
