import { describe, expect, it, vi } from "vitest";

import { openWorkflowInComfyUI } from "../../web/comfyui/workflow_loader.js";

const payload = {
  path: "Example-v1.0.json",
  workflow: { version: 0.4, nodes: [] },
};

describe("openWorkflowInComfyUI", () => {
  it("opens downloaded files as native persisted ComfyUI workflows", async () => {
    const persistedWorkflow = {
      isLoaded: false,
      activeState: { version: 0.4, nodes: [{ id: 1 }] },
      load: vi.fn().mockImplementation(function load() {
        this.isLoaded = true;
      }),
    };
    const workflowStore = {
      syncWorkflows: vi.fn().mockResolvedValue(undefined),
      getWorkflowByPath: vi.fn().mockReturnValue(persistedWorkflow),
    };
    const app = {
      extensionManager: { workflow: workflowStore },
      loadGraphData: vi.fn().mockResolvedValue(undefined),
    };

    await openWorkflowInComfyUI(app, payload);

    expect(workflowStore.syncWorkflows).toHaveBeenCalledOnce();
    expect(workflowStore.getWorkflowByPath).toHaveBeenCalledWith("workflows/Example-v1.0.json");
    expect(persistedWorkflow.load).toHaveBeenCalledOnce();
    expect(app.loadGraphData).toHaveBeenCalledWith(
      persistedWorkflow.activeState,
      true,
      true,
      persistedWorkflow,
    );
  });

  it("does not reload the workflow that is already active", async () => {
    const persistedWorkflow = {
      isLoaded: true,
      activeState: { version: 0.4, nodes: [{ id: 2 }] },
      load: vi.fn(),
    };
    const workflowStore = {
      syncWorkflows: vi.fn().mockResolvedValue(undefined),
      getWorkflowByPath: vi.fn().mockReturnValue(persistedWorkflow),
      isActive: vi.fn().mockReturnValue(true),
    };
    const app = {
      extensionManager: { workflow: workflowStore },
      loadGraphData: vi.fn(),
    };

    await openWorkflowInComfyUI(app, payload);

    expect(workflowStore.isActive).toHaveBeenCalledWith(persistedWorkflow);
    expect(persistedWorkflow.load).not.toHaveBeenCalled();
    expect(app.loadGraphData).not.toHaveBeenCalled();
  });

  it("preserves an already loaded workflow state", async () => {
    const persistedWorkflow = {
      isLoaded: true,
      activeState: { version: 0.4, nodes: [{ id: 2 }] },
      load: vi.fn(),
    };
    const app = {
      extensionManager: {
        workflow: {
          syncWorkflows: vi.fn().mockResolvedValue(undefined),
          getWorkflowByPath: vi.fn().mockReturnValue(persistedWorkflow),
          isActive: vi.fn().mockReturnValue(false),
        },
      },
      loadGraphData: vi.fn().mockResolvedValue(undefined),
    };

    await openWorkflowInComfyUI(app, payload);

    expect(persistedWorkflow.load).not.toHaveBeenCalled();
    expect(app.loadGraphData).toHaveBeenCalledWith(
      persistedWorkflow.activeState,
      true,
      true,
      persistedWorkflow,
    );
  });

  it("fails clearly when ComfyUI cannot find the downloaded persisted workflow", async () => {
    const app = {
      extensionManager: {
        workflow: {
          syncWorkflows: vi.fn().mockResolvedValue(undefined),
          getWorkflowByPath: vi.fn().mockReturnValue(undefined),
        },
      },
      loadGraphData: vi.fn(),
    };

    await expect(openWorkflowInComfyUI(app, payload)).rejects.toMatchObject({
      code: "workflow_load.missing_from_storage",
      params: { path: "workflows/Example-v1.0.json" },
    });
    expect(app.loadGraphData).not.toHaveBeenCalled();
  });

  it("keeps the filename when the native workflow store API is unavailable", async () => {
    const app = {
      extensionManager: {},
      loadGraphData: vi.fn().mockResolvedValue(undefined),
    };

    await openWorkflowInComfyUI(app, payload);

    expect(app.loadGraphData).toHaveBeenCalledWith(
      payload.workflow,
      true,
      true,
      "Example-v1.0.json",
    );
  });

  it("rejects an invalid workflow payload", async () => {
    await expect(
      openWorkflowInComfyUI({ loadGraphData: vi.fn() }, { ...payload, workflow: [] }),
    ).rejects.toMatchObject({ code: "workflow_load.invalid_payload" });
  });

  it.each(["", "../Example.json", "/Example.json", "folder\\Example.json", "Example.png"])(
    "rejects an invalid workflow path: %s",
    async (path) => {
      await expect(
        openWorkflowInComfyUI({ loadGraphData: vi.fn() }, { ...payload, path }),
      ).rejects.toMatchObject({ code: "workflow_load.invalid_path" });
    },
  );
});
