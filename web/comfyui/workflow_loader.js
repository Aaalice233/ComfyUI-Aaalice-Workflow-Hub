export class WorkflowLoadError extends Error {
  constructor(code, params = {}) {
    super(code);
    this.code = code;
    this.params = params;
  }
}

function relativeWorkflowPath(value) {
  if (typeof value !== "string" || !value || value.includes("\\") || value.includes("\0")) {
    throw new WorkflowLoadError("workflow_load.invalid_path");
  }
  const parts = value.split("/");
  if (parts.some((part) => !part || part === "." || part === "..") || !value.toLowerCase().endsWith(".json")) {
    throw new WorkflowLoadError("workflow_load.invalid_path");
  }
  return parts.join("/");
}

export async function openWorkflowInComfyUI(app, payload) {
  if (!payload?.workflow || typeof payload.workflow !== "object" || Array.isArray(payload.workflow)) {
    throw new WorkflowLoadError("workflow_load.invalid_payload");
  }

  const path = relativeWorkflowPath(payload.path);
  const workflowStore = app.extensionManager?.workflow;
  if (
    typeof workflowStore?.syncWorkflows === "function" &&
    typeof workflowStore?.getWorkflowByPath === "function"
  ) {
    await workflowStore.syncWorkflows();
    const persistedWorkflow = workflowStore.getWorkflowByPath(`workflows/${path}`);
    if (!persistedWorkflow) {
      throw new WorkflowLoadError("workflow_load.missing_from_storage", { path: `workflows/${path}` });
    }
    if (typeof workflowStore.isActive === "function" && workflowStore.isActive(persistedWorkflow)) return;
    if (!persistedWorkflow.isLoaded) await persistedWorkflow.load();
    await app.loadGraphData(persistedWorkflow.activeState, true, true, persistedWorkflow);
    return;
  }

  await app.loadGraphData(payload.workflow, true, true, path);
}
