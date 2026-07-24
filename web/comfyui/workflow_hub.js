import { app } from "../../scripts/app.js";

const CHANNEL_NAME = "aaalice-workflow-hub";
const PAGE = "/workflow-hub";
const TOOLTIP = "打开工作流中心（Shift+点击在新窗口打开） / Open Workflow Hub";

function openHub(event) {
  const url = `${window.location.origin}${PAGE}`;
  if (event?.shiftKey) {
    window.open(url, "_blank", "width=1240,height=840,resizable=yes,scrollbars=yes,status=yes");
    return;
  }
  window.open(url, "aaalice-workflow-hub");
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

app.registerExtension({
  name: "Aaalice.WorkflowHub",
  actionBarButtons: [
    {
      icon: "icon-[lucide--library-big] size-4",
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
