export interface CanvasSnapshot {
  name: string;
  workflow: Record<string, unknown>;
}

export const CHANNEL_NAME = "aaalice-workflow-hub";

export function requestCanvas(timeout = 3000): Promise<CanvasSnapshot> {
  return new Promise((resolve, reject) => {
    const channel = new BroadcastChannel(CHANNEL_NAME);
    const timer = window.setTimeout(() => {
      channel.close();
      reject(new Error("canvas_unavailable"));
    }, timeout);
    channel.onmessage = (event) => {
      if (event.data?.type !== "WORKFLOW_HUB_CANVAS_RESPONSE") return;
      clearTimeout(timer);
      channel.close();
      resolve({ name: event.data.name || "workflow", workflow: event.data.workflow });
    };
    channel.postMessage({ type: "WORKFLOW_HUB_CANVAS_REQUEST" });
  });
}
