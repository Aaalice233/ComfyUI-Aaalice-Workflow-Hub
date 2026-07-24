import { app } from "../../scripts/app.js";

const CHANNEL_NAME = "aaalice-workflow-hub";
const PAGE = "/workflow-hub";
const TOOLTIP = "打开工作流中心（Shift+点击在新窗口打开） / Open Workflow Hub";
const ICON_CLASS = "aaalice-workflow-hub-icon";
const ICON_STYLE_ID = "aaalice-workflow-hub-icon-style";
const MODAL_ID = "aaalice-workflow-hub-modal";
const LIBRARY_BIG_SVG = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="black" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="8" height="18" x="3" y="3" rx="1"/><path d="M7 3v18"/><path d="M20.4 18.9c.2.5-.1 1.1-.6 1.3l-1.9.7c-.5.2-1.1-.1-1.3-.6L11.1 5.1c-.2-.5.1-1.1.6-1.3l1.9-.7c.5-.2 1.1.1 1.3.6Z"/></svg>`;
const X_SVG = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="black" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>`;

function installIconStyle() {
  if (document.getElementById(ICON_STYLE_ID)) return;

  const iconMask = `url("data:image/svg+xml,${encodeURIComponent(LIBRARY_BIG_SVG)}")`;
  const closeMask = `url("data:image/svg+xml,${encodeURIComponent(X_SVG)}")`;
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
      background: rgb(5 8 12 / 55%);
      backdrop-filter: blur(6px);
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

    .aaalice-workflow-hub-header {
      display: flex;
      min-height: 48px;
      padding: 0 10px 0 18px;
      align-items: center;
      justify-content: space-between;
      background: rgb(255 255 255 / 3%);
      box-shadow: inset 0 -1px rgb(255 255 255 / 5%);
    }

    .aaalice-workflow-hub-title {
      color: var(--input-text, #e7e9ed);
      font-size: 14px;
      font-weight: 600;
      letter-spacing: 0.01em;
    }

    .aaalice-workflow-hub-close {
      display: grid;
      width: 32px;
      height: 32px;
      padding: 0;
      border: 0;
      border-radius: 8px;
      place-items: center;
      color: var(--input-text, #d3d6dc);
      background: transparent;
      cursor: pointer;
      transition: background-color 0.16s ease, color 0.16s ease;
    }

    .aaalice-workflow-hub-close:hover,
    .aaalice-workflow-hub-close:focus-visible {
      color: #fff;
      background: rgb(255 255 255 / 9%);
      outline: none;
    }

    .aaalice-workflow-hub-close::before {
      width: 18px;
      height: 18px;
      background: currentColor;
      content: "";
      -webkit-mask: ${closeMask} center / contain no-repeat;
      mask: ${closeMask} center / contain no-repeat;
    }

    .aaalice-workflow-hub-frame {
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
  modal.setAttribute("aria-labelledby", `${MODAL_ID}-title`);

  const panel = document.createElement("section");
  panel.className = "aaalice-workflow-hub-panel";

  const header = document.createElement("header");
  header.className = "aaalice-workflow-hub-header";

  const title = document.createElement("strong");
  title.id = `${MODAL_ID}-title`;
  title.className = "aaalice-workflow-hub-title";
  title.textContent = "工作流中心 · Workflow Hub";

  const closeButton = document.createElement("button");
  closeButton.type = "button";
  closeButton.className = "aaalice-workflow-hub-close";
  closeButton.setAttribute("aria-label", "关闭工作流中心 / Close Workflow Hub");
  closeButton.addEventListener("click", closeHub);

  const frame = document.createElement("iframe");
  frame.className = "aaalice-workflow-hub-frame";
  frame.src = PAGE;
  frame.title = "工作流中心 / Workflow Hub";
  frame.addEventListener("load", () => {
    frame.contentDocument?.addEventListener("keydown", handleHubKeydown, true);
  });

  header.append(title, closeButton);
  panel.append(header, frame);
  modal.append(panel);
  modal.addEventListener("click", (event) => {
    if (event.target === modal) closeHub();
  });
  document.body.appendChild(modal);
  document.addEventListener("keydown", handleHubKeydown, true);
  closeButton.focus();
}

function openHub(event) {
  const url = `${window.location.origin}${PAGE}`;
  if (event?.shiftKey) {
    window.open(url, "_blank", "width=1240,height=840,resizable=yes,scrollbars=yes,status=yes");
    return;
  }
  openEmbeddedHub();
}

const channel = new BroadcastChannel(CHANNEL_NAME);
channel.onmessage = (event) => {
  if (event.data?.type !== "WORKFLOW_HUB_CANVAS_REQUEST") return;
  try {
    const workflow = app.graph?.serialize?.();
    if (!workflow) return;
    const name = app.graph?.extra?.workflowName || document.title?.replace(/\s*-\s*ComfyUI.*$/, "") || "workflow";
    channel.postMessage({ type: "WORKFLOW_HUB_CANVAS_RESPONSE", workflow, name });
  } catch (error) {
    console.error("Workflow Hub: unable to serialize current canvas", error);
  }
};

installIconStyle();

app.registerExtension({
  name: "Aaalice.WorkflowHub",
  actionBarButtons: [
    {
      icon: ICON_CLASS,
      tooltip: TOOLTIP,
      onClick: openHub,
    },
  ],
  aboutPageBadges: [
    {
      label: "Aaalice Workflow Hub v1.0.0",
      url: "https://github.com/Aaalice233/ComfyUI-Aaalice-Workflow-Hub",
      icon: "pi pi-box",
    },
  ],
});
